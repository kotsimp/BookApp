try:
    import _sandbox_guard  # noqa: F401  (never run against the real jobs, keys or port 8000)
except ImportError:
    from tests import _sandbox_guard  # noqa: F401
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from backend.parsers import _clean_page_blocks
import pymupdf

def test_initial_pages_and_header_cleanup():
    doc = pymupdf.open()
    
    # Page 0: Cover (image-only or blank)
    doc.new_page(width=432, height=648)
    
    # Page 1: TOC
    p1 = doc.new_page(width=432, height=648)
    p1.insert_text(pymupdf.Point(46, 100), "Blindsight\nPeter Watts\nPrologue 6\nTheseus 11")
    
    # Page 2: Prologue start with running header
    p2 = doc.new_page(width=432, height=648)
    p2.insert_text(pymupdf.Point(46, 35), "Peter Watts\n6\nBlindsight") # Header
    p2.insert_text(pymupdf.Point(46, 120), "Prologue\n\"Try to touch the past. It is not real.\"")
    p2.insert_text(pymupdf.Point(46, 160), "It didn't start out here. If ten-year-")
    
    # Page 3: Sentence continuation across page boundary at top margin
    p3 = doc.new_page(width=432, height=648)
    p3.insert_text(pymupdf.Point(46, 35), "Peter Watts\n7\nBlindsight") # Header
    p3.insert_text(pymupdf.Point(46, 52), "olds would go up against six bigger kids") # Sentence continuation!
    p3.insert_text(pymupdf.Point(46, 90), "I just stood there.")
    
    pdf_bytes = doc.tobytes()
    doc_reloaded = pymupdf.open(stream=pdf_bytes, filetype="pdf")
    
    # Verify clean_page_blocks
    c1 = _clean_page_blocks(doc_reloaded[1])
    assert "Blindsight" in c1
    assert "Prologue" in c1
    
    c2 = _clean_page_blocks(doc_reloaded[2])
    assert "Prologue" in c2
    assert "Try to touch the past" in c2
    assert "Peter Watts" not in c2, "Running header should be stripped"
    
    c3 = _clean_page_blocks(doc_reloaded[3])
    assert "olds would go up against six bigger kids" in c3, "Sentence continuation at top must NOT be stripped!"
    assert "I just stood there" in c3
    assert "Peter Watts" not in c3, "Running header should be stripped"
    
    print("ALL INITIAL PAGES AND HEADER PRESERVATION CHECKS PASSED!")

if __name__ == "__main__":
    test_initial_pages_and_header_cleanup()
