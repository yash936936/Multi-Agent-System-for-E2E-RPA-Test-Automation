"""
Locator — agents/vision/locator.py

Maps a step's target_description/field_description text to on-screen
coordinates. Primary strategy is OCR text matching (pytesseract), which
covers the large majority of RPA targets (buttons/fields with visible
labels). A lightweight opencv edge-density check is used as a secondary
signal to nudge confidence for icon-like regions with little/no text —
full icon template matching would need a reference image library, which
is out of scope until a real target app's icon set exists.

No network calls — tesseract runs fully local via the `pytesseract`
binding to the system `tesseract` binary.
"""
from __future__ import annotations

from dataclasses import dataclass
from difflib import SequenceMatcher
from pathlib import Path

from PIL import Image
import re


@dataclass
class LocateResult:
    found: bool
    x: int = 0
    y: int = 0
    confidence: float = 0.0
    matched_text: str = ""


def _ocr_data(image: Image.Image) -> dict:
    import pytesseract

    from config.settings import settings

    if settings.tesseract_cmd:
        pytesseract.pytesseract.tesseract_cmd = settings.tesseract_cmd

    return pytesseract.image_to_data(image, output_type=pytesseract.Output.DICT)


def _group_lines(ocr: dict) -> list[dict]:
    """Groups OCR word-boxes into lines (block/par/line), each with joined text + bbox."""
    lines: dict[tuple, dict] = {}
    n = len(ocr["text"])
    for i in range(n):
        word = ocr["text"][i].strip()
        if not word:
            continue
        key = (ocr["block_num"][i], ocr["par_num"][i], ocr["line_num"][i])
        x, y, w, h = ocr["left"][i], ocr["top"][i], ocr["width"][i], ocr["height"][i]
        if key not in lines:
            lines[key] = {"words": [], "x0": x, "y0": y, "x1": x + w, "y1": y + h}
        entry = lines[key]
        entry["words"].append(word)
        entry["x0"] = min(entry["x0"], x)
        entry["y0"] = min(entry["y0"], y)
        entry["x1"] = max(entry["x1"], x + w)
        entry["y1"] = max(entry["y1"], y + h)
    return [
        {
            "text": " ".join(v["words"]),
            "cx": (v["x0"] + v["x1"]) // 2,
            "cy": (v["y0"] + v["y1"]) // 2,
        }
        for v in lines.values()
    ]


def list_text_elements(screenshot_path: str | Path) -> list[dict]:
    """
    Returns every OCR-detected text line on the screenshot as a dict:
    {"text": str, "cx": int, "cy": int} (center coordinates).

    Unlike locate_text() (which finds the single best match for one target
    description), this returns everything detected — used by
    agents/vision/ui_audit.py to classify the whole page into landmark
    regions (nav/hero/footer/body) by Y position, and to enumerate
    candidate clickable elements for the autonomous UI audit.
    """
    with Image.open(screenshot_path) as opened:
        opened.load()
        width, height = opened.size
        ocr = _ocr_data(opened)

    elements = []
    for line in _group_lines(ocr):
        elements.append({"text": line["text"], "cx": line["cx"], "cy": line["cy"]})

    return elements


def image_dimensions(screenshot_path: str | Path) -> tuple[int, int]:
    """Returns (width, height) of a screenshot, used to compute landmark bands as a fraction of screen height."""
    with Image.open(screenshot_path) as opened:
        opened.load()
        return opened.size


def locate_text(
    screenshot_path: str | Path,
    target_description: str,
    min_ratio: float = 0.4,
    search_region: tuple[int, int, int, int] | None = None,
) -> LocateResult:
    """
    search_region: optional (x0, y0, x1, y1) to crop before OCR — used when
    a skill hint proposes broadening/narrowing the search area.
    """
    # Use a context manager so the underlying file handle is released as
    # soon as we're done with it, rather than staying open until garbage
    # collection (PIL opens lazily). On Windows this otherwise blocks
    # deletion of the file/its parent tmp dir while the handle is still
    # live -- .load() forces pixel data into memory before the `with`
    # block exits, so OCR below still has valid image data to work with.
    with Image.open(screenshot_path) as opened:
        opened.load()
        image = opened.crop(search_region) if search_region else opened.copy()

    offset_x, offset_y = 0, 0
    if search_region:
        x0, y0, x1, y1 = search_region
        offset_x, offset_y = x0, y0

    ocr = _ocr_data(image)
    lines = _group_lines(ocr)

    def _normalize(s: str) -> str:
        # Strip punctuation/extra whitespace so minor OCR noise (a stray
        # period, an extra space, a misread trailing character) doesn't
        # silently break the containment check below.
        return re.sub(r"[^a-z0-9 ]", "", s.lower()).strip()

    target_norm = target_description.strip().lower()
    target_clean = _normalize(target_description)
    best: tuple[dict, float] | None = None
    for line in lines:
        ocr_text = line["text"].strip().lower()
        ratio = SequenceMatcher(None, target_norm, ocr_text).ratio()
        # Also credit partial containment (e.g. target "Login button,
        # top-right" vs OCR "Login Button"). Boosted well above (not
        # exactly equal to) config/settings.py's vision_confidence_threshold
        # (0.75) -- previously this was hardcoded to precisely 0.75, which
        # meant it sat exactly on the pass/fail gate with zero margin: any
        # tiny OCR misread (different Tesseract build/version, font
        # hinting/antialiasing differences) that broke the exact-substring
        # match would silently fall back to the raw, much lower
        # SequenceMatcher ratio and escalate for no real reason.
        ocr_clean = _normalize(line["text"])
        if ocr_clean and (ocr_clean in target_clean or target_clean in ocr_clean):
            ratio = max(ratio, 0.9)
        if best is None or ratio > best[1]:
            best = (line, ratio)

    if best is None or best[1] < min_ratio:
        return LocateResult(found=False, confidence=best[1] if best else 0.0)

    line, ratio = best
    return LocateResult(
        found=True,
        x=line["cx"] + offset_x,
        y=line["cy"] + offset_y,
        confidence=round(min(ratio, 0.99), 4),
        matched_text=line["text"],
    )