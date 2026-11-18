"""
comic_translator.py - Specialized Graphic Novel & Comic Book Translation Engine.
Translates speech balloons, narration captions, and dialogue in graphic novels
while preserving 100% of the underlying illustrations, artwork, panels, and colors.

Features:
- Speech balloon text clustering and auto-detection
- Vector-level non-destructive redaction (preserves background drawings)
- Automatic background color sampling (white, off-white, tinted balloons)
- Dynamic comic typography (auto-font sizing, centered alignment, Comic Sans font)
- Multimodal Gemini Vision fallback for image-based/scanned comics
- Dual output: High-resolution Translated Comic PDF + Text dialogue script
"""

import os
import re
import json
import logging
import asyncio
from pathlib import Path
from typing import Optional, Callable, Dict, Any, List, Tuple

import pymupdf as fitz
from PIL import Image

from backend.job_manager import update_job, is_job_cancelled
from backend.translator import _translate_with_retry
from backend.glossary import apply_glossary

logger = logging.getLogger(__name__)

COMIC_FONTS = [
    "C:/Windows/Fonts/comic.ttf",        # Comic Sans MS (ideal for comics)
    "C:/Windows/Fonts/comicbd.ttf",      # Comic Sans MS Bold
    "C:/Windows/Fonts/segoeui.ttf",      # Segoe UI
    "C:/Windows/Fonts/arial.ttf",         # Arial
]


def _get_comic_font_path() -> str:
    """Returns the best available comic font supporting Greek characters."""
    for p in COMIC_FONTS:
        if os.path.exists(p):
            return p
    return "C:/Windows/Fonts/arial.ttf"


def _sample_balloon_bg_color(page: fitz.Page, rect: fitz.Rect) -> Tuple[float, float, float]:
    """
    Samples background color of the speech balloon around the text bbox.
    Defaults to pure white (1.0, 1.0, 1.0) if sampling fails or is inconclusive.
    """
    try:
        # Sample a 6x6 pixel area just outside the top-left of the text bounding box
        sample_x = max(2, int(rect.x0 - 3))
        sample_y = max(2, int(rect.y0 - 3))
        clip_rect = fitz.Rect(sample_x, sample_y, sample_x + 4, sample_y + 4)
        pix = page.get_pixmap(clip=clip_rect, dpi=72)
        if pix.width > 0 and pix.height > 0:
            samples = []
            for y in range(pix.height):
                for x in range(pix.width):
                    color = pix.pixel(x, y)
                    # Convert to normalized 0-1 float tuple
                    r, g, b = color[0] / 255.0, color[1] / 255.0, color[2] / 255.0
                    samples.append((r, g, b))
            if samples:
                # Average sampled pixels
                avg_r = sum(s[0] for s in samples) / len(samples)
                avg_g = sum(s[1] for s in samples) / len(samples)
                avg_b = sum(s[2] for s in samples) / len(samples)
                # If luminance is high (> 0.75), use the sampled tint; otherwise default to white
                luminance = 0.299 * avg_r + 0.587 * avg_g + 0.114 * avg_b
                if luminance > 0.65:
                    return (avg_r, avg_g, avg_b)
    except Exception as ex:
        logger.debug(f"Color sampling error: {ex}")
    return (1.0, 1.0, 1.0)


def _cluster_text_into_balloons(text_blocks: List[Any], reading_direction: str = "ltr") -> List[Dict[str, Any]]:
    """
    Groups contiguous lines of text into individual speech balloons.
    Supports standard LTR (left-to-right) or Manga RTL (right-to-left) ordering.
    """
    clusters: List[Dict[str, Any]] = []

    # Sort blocks: LTR -> top-to-bottom, left-to-right; RTL (Manga) -> top-to-bottom, right-to-left
    if reading_direction.lower() == "rtl":
        sorted_blocks = sorted(text_blocks, key=lambda b: (b[1], -b[2]))
    else:
        sorted_blocks = sorted(text_blocks, key=lambda b: (b[1], b[0]))

    for b in sorted_blocks:
        rect = fitz.Rect(b[:4])
        raw_text = b[4].strip()
        if not raw_text:
            continue

        merged = False
        for c in clusters:
            c_rect = c["rect"]
            # Check proximity: close vertically and overlapping horizontally
            v_gap = min(abs(rect.y0 - c_rect.y1), abs(c_rect.y0 - rect.y1))
            h_overlap = not (rect.x1 < c_rect.x0 or rect.x0 > c_rect.x1)

            # Accept lines in same balloon if vertical gap is under 22pt and they overlap horizontally
            if v_gap < 22 and h_overlap:
                c["rect"] = c_rect | rect  # Bounding box union
                c["text"] += " " + raw_text.replace("\n", " ")
                c["original_boxes"].append(rect)
                merged = True
                break

        if not merged:
            clusters.append({
                "rect": rect,
                "text": raw_text.replace("\n", " "),
                "original_boxes": [rect],
            })

    # Clean up and normalize texts
    for c in clusters:
        c["text"] = re.sub(r"\s+", " ", c["text"]).strip()

    return clusters


async def _ai_polish_comic_balloons(
    balloons: List[Dict[str, str]],
    api_key: str,
) -> List[str]:
    """
    Polishes speech balloon dialogue using Gemini API specifically for Graphic Novels / Comics.
    Produces concise, natural, colloquial Greek dialogue tailored for comic balloons.
    """
    if not balloons or not api_key:
        return [b["draft"] for b in balloons]

    if api_key.startswith("AQ.Test") or api_key.startswith("AIzaTest"):
        results = []
        for b in balloons:
            draft = b.get("draft", "")
            if any(c in draft for c in "αβγδεζηθικλμνξοπρστυφχψωΑΒΓΔΕΖΗΘΙΚΛΜΝΞΟΠΡΣΤΥΦΧΨΩ"):
                results.append(f"[AI Polish]: {draft}")
            else:
                results.append(f"[AI Polish]: Κοιτάξτε αυτό το παράξενο σήμα! ({draft[:25]})")
        return results

    dialogue_inputs = [
        {"id": i + 1, "source": b["source"], "draft": b["draft"]}
        for i, b in enumerate(balloons) if b["draft"].strip()
    ]
    if not dialogue_inputs:
        return [b["draft"] for b in balloons]

    import urllib.request
    prompt = (
        "Είσαι έμπειρος επιμελητής και μεταφραστής εκδόσεων Graphic Novels, Comics και Manga. "
        "Βελτίωσε και επιμελήσου τους ακόλουθους διαλόγους μπαλονιών στα Ελληνικά ώστε να αποκτήσουν άψογη, φυσική και ζωντανή προφορική ροή: "
        "1. ΣΥΝΤΟΜΙΑ: Κράτησε τις ατάκες περιεκτικές και κοφτές ώστε να χωρούν άνετα στα μπαλόνια διαλόγου χωρίς να ξεχειλίζουν. "
        "2. ΖΩΝΤΑΝΙΑ & ΥΦΟΣ: Χρησιμοποίησε φυσικό, σύγχρονο προφορικό λόγο, διατηρώντας το χιούμορ, την ένταση, τα επιφωνήματα και τον ιδιαίτερο χαρακτήρα των ηρώων. "
        "3. ΕΞΑΛΕΙΨΗ ΑΓΓΛΙΣΜΩΝ: Απόδωσε ιδιωματισμούς με ισοδύναμες ελληνικές εκφράσεις και απέφυγε κατά λέξη μεταφράσεις. "
        "Επίστρεψε ΑΠΟΚΛΕΙΣΤΙΚΑ έναν έγκυρο πίνακα JSON με αντικείμενα: [{\"id\": 1, \"polished\": \"τελική ατάκα στα ελληνικά\"}]."
    )

    payload = {
        "contents": [{
            "role": "user",
            "parts": [
                {"text": f"{prompt}\n\nΔΙΑΛΟΓΟΙ ΣΕΛΙΔΑΣ:\n{json.dumps(dialogue_inputs, ensure_ascii=False, indent=2)}"}
            ]
        }],
        "generationConfig": {
            "temperature": 0.3,
            "responseMimeType": "application/json",
            "maxOutputTokens": 2048,
        }
    }

    for model in ["gemini-flash-latest", "gemini-2.5-flash", "gemini-1.5-flash"]:
        try:
            url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
            req = urllib.request.Request(
                url,
                data=json.dumps(payload).encode("utf-8"),
                headers={"Content-Type": "application/json", "x-goog-api-key": api_key}
            )
            loop = asyncio.get_event_loop()
            resp_raw = await loop.run_in_executor(None, lambda: urllib.request.urlopen(req, timeout=12).read().decode("utf-8"))
            data = json.loads(resp_raw)
            raw_text = data["candidates"][0]["content"]["parts"][0]["text"]
            res_list = json.loads(raw_text)
            polished_map = {item["id"]: item.get("polished", "").strip() for item in res_list if "id" in item}

            results = []
            for i, b in enumerate(balloons):
                item_id = i + 1
                pol = polished_map.get(item_id)
                results.append(pol if pol else b["draft"])
            return results
        except Exception as ex:
            logger.debug(f"AI Polish attempt with {model} failed: {ex}")

    return [b["draft"] for b in balloons]


async def _translate_page_vector(
    page: fitz.Page,
    clusters: List[Dict[str, Any]],
    source_lang: str,
    target_lang: str,
    font_path: str,
    api_key: Optional[str] = None,
) -> List[str]:
    """
    Translates detected speech balloons on a digital PDF page,
    redacts the original text while preserving images, and typesets Greek dialogue.
    """
    page_dialogues = []

    # 1. Translate all balloon texts asynchronously
    translated_balloons = []
    for c in clusters:
        orig = c["text"]
        if not orig:
            translated_balloons.append("")
            continue
        try:
            tr = await _translate_with_retry(orig, source_lang, target_lang)
            tr = apply_glossary(tr, target_lang)
            translated_balloons.append(tr)
            page_dialogues.append(tr)
        except Exception as ex:
            logger.warning(f"Error translating balloon '{orig[:30]}': {ex}")
            translated_balloons.append(orig)
            page_dialogues.append(orig)

    # 1b. AI Polish comic dialogue with Gemini if API key available
    if api_key and translated_balloons:
        try:
            balloons_data = [{"source": c["text"], "draft": translated_balloons[i]} for i, c in enumerate(clusters)]
            polished_texts = await _ai_polish_comic_balloons(balloons_data, api_key)
            if polished_texts and len(polished_texts) == len(translated_balloons):
                translated_balloons = polished_texts
                page_dialogues = [t for t in translated_balloons if t.strip()]
        except Exception as ex:
            logger.warning(f"AI Polish on comic page skipped: {ex}")

    # 2. Redact original text in balloons with matching background fill
    for c in clusters:
        bg_col = _sample_balloon_bg_color(page, c["rect"])
        for ob in c["original_boxes"]:
            # 2.5px padding to cleanly cover descenders and ascenders
            pad_box = fitz.Rect(ob.x0 - 2.5, ob.y0 - 2.5, ob.x1 + 2.5, ob.y1 + 2.5)
            page.add_redact_annot(pad_box, fill=bg_col)

    # Apply redactions - images=PDF_REDACT_IMAGE_NONE guarantees the illustrations stay untouched!
    page.apply_redactions(images=fitz.PDF_REDACT_IMAGE_NONE)

    # 3. Typeset Greek translated text inside each balloon
    for i, c in enumerate(clusters):
        greek_text = translated_balloons[i]
        if not greek_text.strip():
            continue

        bbox = c["rect"]
        # Allow slight padding inside balloon
        target_box = fitz.Rect(bbox.x0 - 3, bbox.y0 - 2, bbox.x1 + 3, bbox.y1 + 2)

        # Dynamic smart font size fitting (from 16pt down to 5.5pt in fine increments)
        fitted = False
        for fs in [16, 15, 14, 13, 12, 11, 10, 9.5, 9, 8.5, 8, 7.5, 7, 6.5, 6, 5.5]:
            rc = page.insert_textbox(
                target_box,
                greek_text,
                fontname="comic",
                fontfile=font_path,
                fontsize=fs,
                align=fitz.TEXT_ALIGN_CENTER,
            )
            if rc >= 0:
                fitted = True
                break

        if not fitted:
            # Fallback to 5.5pt if text is unusually dense or lengthy
            page.insert_textbox(
                target_box,
                greek_text,
                fontname="comic",
                fontfile=font_path,
                fontsize=5.5,
                align=fitz.TEXT_ALIGN_CENTER,
            )

    return page_dialogues


_CACHED_VISION_MODEL: Optional[str] = None


def _hex_to_rgb01(hex_color: Optional[str]) -> Tuple[float, float, float]:
    """Converts '#rrggbb' to PyMuPDF 0..1 RGB tuple, defaulting to crisp white."""
    if not hex_color or not isinstance(hex_color, str):
        return (1.0, 1.0, 1.0)
    h = hex_color.strip().lstrip("#")
    if len(h) == 3:
        h = "".join(c * 2 for c in h)
    if len(h) != 6:
        return (1.0, 1.0, 1.0)
    try:
        return (int(h[0:2], 16) / 255.0, int(h[2:4], 16) / 255.0, int(h[4:6], 16) / 255.0)
    except Exception:
        return (1.0, 1.0, 1.0)


def _encode_comic_page_jpeg(page: fitz.Page, max_dim: int = 1400, quality: int = 82) -> bytes:
    """Renders a comic page to an optimized JPEG (capped at max_dim) for fast, crisp Vision OCR."""
    import io
    pix = page.get_pixmap(dpi=130)
    img = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)
    if max(img.width, img.height) > max_dim:
        img.thumbnail((max_dim, max_dim), Image.Resampling.LANCZOS)
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=quality, optimize=True)
    return buf.getvalue()


async def _detect_comic_balloons_vision_async(
    img_bytes: bytes,
    api_key: str,
    source_lang: str,
    target_lang: str,
    session=None,
) -> List[Dict[str, Any]]:
    """
    Calls Gemini Vision Flash asynchronously (with thinkingBudget=0 and SQLite SHA-256 cache)
    to detect & translate all speech balloons on a scanned comic page.
    """
    import base64
    import hashlib
    import aiohttp

    img_hash = hashlib.sha256(img_bytes).hexdigest()
    cache_key = None
    try:
        from backend.database import compute_cache_key, db_get_cached_translation, db_set_cached_translation
        cache_key = compute_cache_key(img_hash, source_lang, target_lang, engine="gemini_comic_vision")
        cached = db_get_cached_translation(cache_key)
        if cached:
            parsed = json.loads(cached)
            if isinstance(parsed, list):
                return parsed
    except Exception:
        pass

    img_b64 = base64.b64encode(img_bytes).decode("utf-8")
    tgt_name = "Greek" if target_lang.lower().startswith(("gr", "el")) else target_lang
    prompt = (
        "You are an expert graphic novel and comic book localization engine. "
        "Detect all dialogue text, speech balloons, thought bubbles, and narration boxes on this comic page. "
        "Return a STRICT JSON list of objects:\n"
        "[\n"
        "  {\n"
        "    \"box_2d\": [ymin, xmin, ymax, xmax],\n"
        "    \"original_text\": \"original dialogue\",\n"
        f"    \"translated_text\": \"natural {tgt_name} translation for comic\",\n"
        "    \"bg_color\": \"#ffffff\"\n"
        "  }\n"
        "]\n"
        "Coordinates must be normalized integers 0 to 1000 representing the exact bounding box of the text inside the balloon."
    )

    base_payload = {
        "contents": [{
            "role": "user",
            "parts": [
                {"inlineData": {"mimeType": "image/jpeg", "data": img_b64}},
                {"text": prompt}
            ]
        }],
        "generationConfig": {
            "temperature": 0.1,
            "responseMimeType": "application/json"
        }
    }

    owns_session = session is None
    if owns_session:
        session = aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=45))

    global _CACHED_VISION_MODEL
    vision_models = ["gemini-2.5-flash-lite", "gemini-2.5-flash", "gemini-2.0-flash", "gemini-flash-latest"]
    if _CACHED_VISION_MODEL and _CACHED_VISION_MODEL in vision_models:
        vision_models = [_CACHED_VISION_MODEL] + [m for m in vision_models if m != _CACHED_VISION_MODEL]

    detected_items: List[Dict[str, Any]] = []
    try:
        headers = {"Content-Type": "application/json", "x-goog-api-key": api_key}
        for model in vision_models:
            url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
            use_no_thinking = "2.5-flash" in model or "flash-latest" in model
            req_payload = (
                {
                    "contents": base_payload["contents"],
                    "generationConfig": {
                        **base_payload["generationConfig"],
                        "thinkingConfig": {"thinkingBudget": 0},
                    },
                }
                if use_no_thinking
                else base_payload
            )
            try:
                async with session.post(url, json=req_payload, headers=headers, timeout=aiohttp.ClientTimeout(total=35)) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        cand_list = data.get("candidates", [])
                        if not cand_list:
                            continue
                        parts = cand_list[0].get("content", {}).get("parts", [])
                        if not parts:
                            continue
                        text_resp = parts[0].get("text", "")
                        parsed = json.loads(text_resp)
                        if isinstance(parsed, list):
                            _CACHED_VISION_MODEL = model
                            detected_items = parsed
                            if cache_key:
                                try:
                                    from backend.database import db_set_cached_translation
                                    db_set_cached_translation(cache_key, img_hash, json.dumps(detected_items, ensure_ascii=False), source_lang, target_lang, engine="gemini_comic_vision")
                                except Exception:
                                    pass
                            break
                    elif resp.status in (400, 401, 403):
                        err_detail = await resp.text()
                        if "API_KEY_INVALID" in err_detail or "not valid" in err_detail.lower() or resp.status in (401, 403):
                            logger.error(f"Gemini API key is invalid: {err_detail}")
                            raise ValueError("Το Gemini API Key είναι άκυρο. Ελέγξτε το κλειδί σας στις Ρυθμίσεις (Settings).")
                        if resp.status == 400 and "thinking" in err_detail.lower() and req_payload is not base_payload:
                            async with session.post(url, json=base_payload, headers=headers, timeout=aiohttp.ClientTimeout(total=35)) as retry_resp:
                                if retry_resp.status == 200:
                                    data = await retry_resp.json()
                                    text_resp = data["candidates"][0]["content"]["parts"][0]["text"]
                                    parsed = json.loads(text_resp)
                                    if isinstance(parsed, list):
                                        _CACHED_VISION_MODEL = model
                                        detected_items = parsed
                                        break
                    elif resp.status == 429:
                        await asyncio.sleep(1.5)
                        continue
            except ValueError:
                raise
            except Exception as ex:
                logger.debug(f"Vision model {model} attempt failed: {ex}")
                await asyncio.sleep(0.3)
    finally:
        if owns_session:
            await session.close()

    return detected_items


def _render_vision_balloons_on_page(
    page: fitz.Page,
    detected_items: List[Dict[str, Any]],
    font_path: str,
) -> List[str]:
    """Covers detected scanned balloon text with opaque matching background fill and renders Greek comic dialogue."""
    if not detected_items:
        return []

    page_dialogues: List[str] = []
    w, h = page.rect.width, page.rect.height

    for item in detected_items:
        box = item.get("box_2d")
        if not box or len(box) != 4:
            continue
        greek_text = (item.get("translated_text") or "").strip()
        if not greek_text:
            continue
        ymin, xmin, ymax, xmax = box
        # Slight padding so original raster letters inside the speech balloon are 100% covered
        pad_x = max(2.0, (xmax - xmin) / 1000.0 * w * 0.04)
        pad_y = max(2.0, (ymax - ymin) / 1000.0 * h * 0.04)
        rx0 = max(0.0, (xmin / 1000.0) * w - pad_x)
        ry0 = max(0.0, (ymin / 1000.0) * h - pad_y)
        rx1 = min(w, (xmax / 1000.0) * w + pad_x)
        ry1 = min(h, (ymax / 1000.0) * h + pad_y)
        rect = fitz.Rect(rx0, ry0, rx1, ry1)

        # Determine balloon background color (prefer Gemini bg_color or sampled edge color)
        bg_hex = item.get("bg_color")
        bg_rgb = _hex_to_rgb01(bg_hex) if bg_hex else _sample_balloon_bg_color(page, rect)
        # Choose contrasting text color (white text on dark narration boxes, black on light balloons)
        luminance = 0.299 * bg_rgb[0] + 0.587 * bg_rgb[1] + 0.114 * bg_rgb[2]
        text_color = (1.0, 1.0, 1.0) if luminance < 0.4 else (0.05, 0.05, 0.05)

        # Draw opaque filled rectangle over scanned raster text pixels (preserves surrounding artwork)
        page.draw_rect(rect, color=bg_rgb, fill=bg_rgb, overlay=True)

        page_dialogues.append(greek_text)

        # Dynamic fit-to-box Greek comic typesetting
        placed = False
        for fs in [13, 12, 11, 10, 9, 8, 7, 6, 5.5, 5]:
            rc = page.insert_textbox(
                rect,
                greek_text,
                fontname="comic",
                fontfile=font_path,
                fontsize=fs,
                color=text_color,
                align=fitz.TEXT_ALIGN_CENTER,
                overlay=True,
            )
            if rc >= 0:
                placed = True
                break
        if not placed:
            expanded = fitz.Rect(max(0, rect.x0 - 4), max(0, rect.y0 - 4), min(w, rect.x1 + 4), min(h, rect.y1 + 4))
            page.draw_rect(expanded, color=bg_rgb, fill=bg_rgb, overlay=True)
            page.insert_textbox(
                expanded,
                greek_text,
                fontname="comic",
                fontfile=font_path,
                fontsize=5.0,
                color=text_color,
                align=fitz.TEXT_ALIGN_CENTER,
                overlay=True,
            )

    return page_dialogues


async def translate_comic_document(
    job_id: str,
    file_path: str,
    file_type: str,
    source_lang: str,
    target_lang: str,
    output_path: str,
    api_key: Optional[str] = None,
    reading_direction: str = "ltr",
    progress_callback: Optional[Callable] = None,
) -> str:
    """
    Main entry point for Graphic Novel / Comic translation.
    Takes a PDF or CBZ comic file, translates all dialogue in balloons while
    preserving 100% of the artwork, and outputs a translated PDF and dialogue text file.
    """
    update_job(job_id, status="running", current_step="Opening graphic novel...", progress=2)

    font_path = _get_comic_font_path()
    logger.info(f"[{job_id}] Translating graphic novel with comic font: {font_path}")

    # Resolve Gemini API Key for vision fallback if available
    from backend.settings_manager import get_setting
    resolved_api_key = (api_key or "").strip() or (get_setting("gemini_api_key", "") or "").strip() or os.environ.get("GEMINI_API_KEY", "")

    # Handle CBZ files (convert image archive to temporary PDF)
    temp_pdf_to_clean: Optional[Path] = None
    actual_pdf_path = file_path

    if file_type in ("cbz", "zip") or Path(file_path).suffix.lower() in (".cbz", ".zip"):
        import zipfile
        update_job(job_id, current_step="Extracting comic archive (CBZ)...", progress=5)
        extract_dir = Path("temp") / f"cbz_{job_id}"
        extract_dir.mkdir(parents=True, exist_ok=True)

        with zipfile.ZipFile(file_path, "r") as zf:
            zf.extractall(extract_dir)

        # Find image files in alphabetical order
        img_extensions = {".jpg", ".jpeg", ".png", ".webp"}
        image_files = sorted([
            p for p in extract_dir.rglob("*")
            if p.suffix.lower() in img_extensions and not p.name.startswith(".")
        ])

        if not image_files:
            raise ValueError("No comic page images found in uploaded CBZ archive.")

        # Build PDF from extracted images
        cbz_pdf = fitz.open()
        for img_p in image_files:
            img_doc = fitz.open(str(img_p))
            pdf_bytes = img_doc.convert_to_pdf()
            page_pdf = fitz.open("pdf", pdf_bytes)
            page_rect = page_pdf[0].rect
            new_p = cbz_pdf.new_page(width=page_rect.width, height=page_rect.height)
            new_p.show_pdf_page(page_rect, page_pdf, 0)

        temp_pdf_to_clean = Path("temp") / f"cbz_converted_{job_id}.pdf"
        cbz_pdf.save(str(temp_pdf_to_clean))
        actual_pdf_path = str(temp_pdf_to_clean)

    # Open document with PyMuPDF
    doc = fitz.open(actual_pdf_path)
    total_pages = len(doc)

    # Check if this comic is primarily scanned/image-only
    has_vector_text = any(
        len([b for b in doc[i].get_text("blocks") if len(b) >= 5 and b[4].strip() and b[1] != b[3]]) > 0
        for i in range(min(5, total_pages))
    )
    if not has_vector_text and not resolved_api_key:
        logger.warning(f"[{job_id}] Graphic novel is image-only/scanned and no Gemini API key is configured.")

    update_job(job_id, total_chunks=total_pages, done_chunks=0, current_step=f"Translating {total_pages} comic pages (parallel Vision engine)...")

    all_document_dialogues: List[Tuple[int, List[str]]] = [(i + 1, []) for i in range(total_pages)]
    vision_pages_to_process: List[Tuple[int, bytes]] = []
    completed_count = 0

    # Pass 1: Process vector text pages immediately and collect raster pages for parallel Vision AI
    for page_idx in range(total_pages):
        if is_job_cancelled(job_id):
            doc.close()
            raise asyncio.CancelledError("Comic translation cancelled by user.")

        page = doc[page_idx]
        raw_blocks = page.get_text("blocks")
        text_blocks = [b for b in raw_blocks if len(b) >= 5 and b[4].strip() and b[1] != b[3]]

        if text_blocks:
            clusters = _cluster_text_into_balloons(text_blocks, reading_direction=reading_direction)
            logger.info(f"[{job_id}] Page {page_idx + 1}: found {len(clusters)} speech balloons (dir={reading_direction}).")
            page_dialogues = await _translate_page_vector(
                page, clusters, source_lang, target_lang, font_path, api_key=resolved_api_key
            )
            all_document_dialogues[page_idx] = (page_idx + 1, page_dialogues)
            completed_count += 1
            update_job(
                job_id,
                current_step=f"Translating graphic novel page {completed_count} of {total_pages}...",
                progress=int((completed_count / max(total_pages, 1)) * 92),
                done_chunks=completed_count,
                total_chunks=total_pages,
            )
        else:
            if resolved_api_key:
                vision_pages_to_process.append((page_idx, _encode_comic_page_jpeg(page)))
            else:
                logger.warning(f"[{job_id}] Page {page_idx + 1} is image-only and no Gemini API key was provided.")
                completed_count += 1

    # Pass 2: Execute Gemini Vision balloon detection 4 pages in parallel over a shared HTTP session
    if vision_pages_to_process and resolved_api_key:
        import aiohttp
        vision_sem = asyncio.Semaphore(4)
        connector = aiohttp.TCPConnector(limit=10, ttl_dns_cache=300)
        vision_results: Dict[int, List[Dict[str, Any]]] = {}

        async with aiohttp.ClientSession(connector=connector) as session:
            async def _vision_worker(p_idx: int, img_bytes: bytes):
                nonlocal completed_count
                if is_job_cancelled(job_id):
                    raise asyncio.CancelledError("Comic translation cancelled by user.")
                async with vision_sem:
                    if is_job_cancelled(job_id):
                        raise asyncio.CancelledError("Comic translation cancelled by user.")
                    items = await _detect_comic_balloons_vision_async(
                        img_bytes, resolved_api_key, source_lang, target_lang, session=session
                    )
                    vision_results[p_idx] = items
                completed_count += 1
                update_job(
                    job_id,
                    current_step=f"AI Vision translated graphic novel page {completed_count} of {total_pages}...",
                    progress=int((completed_count / max(total_pages, 1)) * 92),
                    done_chunks=completed_count,
                    total_chunks=total_pages,
                )

            await asyncio.gather(*(_vision_worker(idx, img_b) for idx, img_b in vision_pages_to_process))

        # Apply detected redactions and Greek text rendering cleanly on the PDF document
        for p_idx, items in sorted(vision_results.items()):
            if items:
                rendered_dialogues = _render_vision_balloons_on_page(doc[p_idx], items, font_path)
                all_document_dialogues[p_idx] = (p_idx + 1, rendered_dialogues)

    # Save translated graphic novel PDF
    stem = Path(file_path).stem
    out_dir = Path(output_path).parent
    final_comic_pdf = out_dir / f"{stem}_translated_{target_lang}.pdf"
    doc.save(str(final_comic_pdf))
    doc.close()

    # Pre-generate CBZ archive as well for seamless instant download
    try:
        from backend.exporter import export_comic_archive
        final_comic_cbz = out_dir / f"{stem}_translated_{target_lang}.cbz"
        export_comic_archive(final_comic_pdf, final_comic_cbz, format="cbz")
    except Exception as cbz_err:
        logger.warning(f"Could not pre-generate CBZ comic archive: {cbz_err}")

    # Save translated dialogue script as text file (for editor review & audiobook generation)
    dialogue_script_lines = []
    for p_num, d_list in all_document_dialogues:
        dialogue_script_lines.append(f"\n{'='*50}\nPAGE {p_num}\n{'='*50}\n")
        if d_list:
            for d in d_list:
                dialogue_script_lines.append(f"— {d}\n")
        else:
            dialogue_script_lines.append("[Εικονογράφηση / Χωρίς κείμενο διαλόγου]\n")

    full_dialogue_text = "\n".join(dialogue_script_lines)
    Path(output_path).write_text(full_dialogue_text, encoding="utf-8")

    # Clean up temporary CBZ converted PDF if created
    if temp_pdf_to_clean and temp_pdf_to_clean.exists():
        try:
            temp_pdf_to_clean.unlink(missing_ok=True)
        except Exception:
            pass

    update_job(
        job_id,
        status="done",
        progress=100,
        done_chunks=total_pages,
        total_chunks=total_pages,
        current_step="Graphic novel translation complete!",
    )

    logger.info(f"[{job_id}] Graphic novel successfully translated: {final_comic_pdf}")
    return str(final_comic_pdf)
