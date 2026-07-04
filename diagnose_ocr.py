"""
Run from the project root with your venv active:
    py diagnose_ocr.py

Prints which font demo_login_app actually picked, then renders the same
login_form screenshot the failing test uses and shows exactly what
Tesseract reads off it -- so we can see whether it's a font fallback
issue or something else.
"""
from pathlib import Path
import tempfile

from target_app.demo_login_app import render_login_screen, resolve_font, _FONT_CANDIDATES
from agents.vision.locator import locate_text

font = resolve_font(22)
print("Font object:", font)
print("Is FreeTypeFont (real TTF loaded)?", type(font).__name__ == "FreeTypeFont")
print()
print("Candidate paths checked, and whether they exist on this machine:")
for p in _FONT_CANDIDATES:
    print(f"  {'[EXISTS]' if Path(p).exists() else '[missing]'}  {p}")
print()

with tempfile.TemporaryDirectory() as d:
    path = Path(d) / "login_form.png"
    render_login_screen("login_form", path)

    for target in ["Login Button", "Username Field", "Password Field", "Submit Button"]:
        result = locate_text(str(path), target)
        print(f"target={target!r:20} found={result.found} confidence={result.confidence:.3f} matched_text={result.matched_text!r}")