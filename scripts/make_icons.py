"""
make_icons.py - Draws BookApp's icon (a stack of books on the app's violet-cyan gradient) and writes every size
browsers and phones ask for into frontend/:

  icon.svg              tab icon for Chrome, Firefox, Edge (sharp at any size)
  favicon.ico           16/32/48 px, for Safari and older browsers
  icon-32.png           PNG tab icon (Safari)
  apple-touch-icon.png  180 px, square and opaque: iPhone/iPad home screen ("Add to Home Screen"); iOS rounds it
  icon-192.png, icon-512.png   for manifest.json (Android home screen, installed app)

Run: python scripts/make_icons.py   (needs PyMuPDF and Pillow, both in requirements.txt)
"""
import io
from pathlib import Path

import pymupdf
from PIL import Image, ImageDraw

FRONTEND = Path(__file__).resolve().parent.parent / "frontend"


def book(x: int, y: int, w: int, h: int, color: str) -> str:
    """One book lying flat, spine towards the viewer: cover colour, two light bands, a shaded lower edge."""
    return (
        f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="12" fill="{color}"/>'
        f'<rect x="{x}" y="{y + h - 12}" width="{w}" height="12" rx="6" fill="#000" fill-opacity=".16"/>'
        f'<rect x="{x + 30}" y="{y}" width="16" height="{h}" fill="#fff" fill-opacity=".85"/>'
        f'<rect x="{x + w - 46}" y="{y}" width="16" height="{h}" fill="#fff" fill-opacity=".85"/>'
        f'<rect x="{x + 70}" y="{y + h / 2 - 7}" width="{w - 140}" height="14" rx="7" fill="#fff" fill-opacity=".35"/>'
    )


VIOLET, CYAN = "#7c3aed", "#06b6d4"
RADIUS = 112  # of 512


def books_svg() -> str:
    return (
        '<ellipse cx="256" cy="414" rx="178" ry="20" fill="#000" fill-opacity=".18"/>'
        + book(84, 324, 344, 82, "#f59e0b")
        + book(116, 244, 296, 80, "#10b981")
        + f'<g transform="rotate(-7 250 200)">{book(102, 166, 300, 78, "#f43f5e")}</g>'
    )


def icon_svg() -> str:
    return (
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 512 512" width="512" height="512">'
        '<defs><linearGradient id="bg" x1="0" y1="0" x2="1" y2="1">'
        f'<stop offset="0" stop-color="{VIOLET}"/><stop offset="1" stop-color="{CYAN}"/></linearGradient></defs>'
        f'<rect width="512" height="512" rx="{RADIUS}" fill="url(#bg)"/>{books_svg()}</svg>'
    )


def render_books(size: int) -> Image.Image:
    """The books alone on transparency (MuPDF draws no SVG gradients, so the background is painted by Pillow)."""
    svg = f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 512 512" width="512" height="512">{books_svg()}</svg>'
    doc = pymupdf.open(stream=svg.encode("utf-8"), filetype="svg")
    zoom = size / doc[0].rect.width
    pix = doc[0].get_pixmap(matrix=pymupdf.Matrix(zoom, zoom), alpha=True)
    return Image.open(io.BytesIO(pix.tobytes("png"))).convert("RGBA")


def background(size: int, rounded: bool) -> Image.Image:
    """The violet-to-cyan diagonal gradient, as a rounded square or a full one."""
    ramp = Image.linear_gradient("L").rotate(45, expand=True)
    side = ramp.size[0]
    ramp = ramp.crop((side // 2 - 91, side // 2 - 91, side // 2 + 91, side // 2 + 91)).resize((size, size))
    img =Image.composite(Image.new("RGBA", (size, size), CYAN), Image.new("RGBA", (size, size), VIOLET), ramp)
    if rounded:
        mask = Image.new("L", (size, size), 0)
        ImageDraw.Draw(mask).rounded_rectangle((0, 0, size - 1, size - 1), radius=RADIUS * size // 512, fill=255)
        img.putalpha(mask)
    return img


def main() -> None:
    (FRONTEND / "icon.svg").write_text(icon_svg(), encoding="utf-8")
    books = render_books(1024)  # drawn large, scaled down: smooth edges at every size
    big = Image.alpha_composite(background(1024, rounded=True), books)
    for size, name in ((32, "icon-32.png"), (192, "icon-192.png"), (512, "icon-512.png")):
        big.resize((size, size), Image.LANCZOS).save(FRONTEND / name, optimize=True)
    big.save(FRONTEND / "favicon.ico", sizes=[(16, 16), (32, 32), (48, 48)])
    # iOS draws its own rounded corners and shows transparency as black: a full, opaque square
    square = Image.alpha_composite(background(1024, rounded=False), books).resize((180, 180), Image.LANCZOS)
    square.convert("RGB").save(FRONTEND / "apple-touch-icon.png", optimize=True)
    print("Icons written to", FRONTEND)


if __name__ == "__main__":
    main()
