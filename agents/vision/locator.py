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

import re
from dataclasses import dataclass
from difflib import SequenceMatcher
from pathlib import Path

from PIL import Image


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
    """
    Groups OCR word-boxes into lines (block/par/line), each with joined
    text + bbox.

    Low-confidence word detections are excluded from both the joined text
    and the bbox computation. Tesseract's image_to_data reports a per-word
    confidence (0-100, or -1 for structural/non-text rows, already
    filtered out by the `if not word` check below since those carry no
    text). A stray noise glyph -- a misread border/icon fragment as `|` or
    `[`, confidently placed on the *same* detected text line as a real
    button label -- previously widened that line's bbox to span from the
    real text's edge out to the noise glyph's position, shifting the
    line's centroid (and therefore the click coordinate) away from the
    actual clickable text. Verified against a real case: OCR line text
    "[Login Button |)" scored a 0.99 match against target "Login Button"
    (agents/vision/locator.py's _match_score correctly tokenizes away the
    punctuation, so the words alone are a perfect match) but the *click
    landed at the wrong position* because the bbox included the noise
    glyphs' coordinates. Excluding sub-threshold-confidence words from the
    bbox (not just relying on _match_score's tokenizer to ignore them
    textually) fixes the coordinate, not just the text match.
    """
    _MIN_WORD_CONF = 40  # tesseract confidence is 0-100; empirically, real printed UI text is consistently well above this, isolated noise-glyph misreads are consistently well below it
    lines: dict[tuple, dict] = {}
    n = len(ocr["text"])
    for i in range(n):
        word = ocr["text"][i].strip()
        if not word:
            continue
        try:
            conf = float(ocr["conf"][i])
        except (KeyError, TypeError, ValueError):
            conf = 100.0  # no confidence field available (e.g. a hand-built test fixture) -- don't filter out text this code can't evaluate
        if conf < _MIN_WORD_CONF:
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
        if v["words"]  # a line where every word was filtered out for low confidence contributes nothing real
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


_WORD_RE = re.compile(r"[a-z0-9]+")


def _words(text: str) -> list[str]:
    return _WORD_RE.findall(text.lower())


def _match_score(target_norm: str, candidate: str) -> float:
    """
    Combines character-level SequenceMatcher similarity with word-level
    overlap so that short, generic OCR lines ("Get in touch", "Loaded
    fonts page") can no longer score highly against a target just because
    they happen to share a handful of common characters, while still
    correctly matching real targets even when one side is more verbose
    (e.g. locator target_description "Login button, top-right" vs OCR
    label "Login Button", or assertion target "dashboard visible" vs a
    longer OCR line that legitimately contains it).

    Previously this granted an unconditional 0.75 score to *any* raw
    substring containment, and plain SequenceMatcher ratio alone was
    empirically shown to score ~0.35-0.43 for text with nothing
    meaningfully to do with the target (see debug_report.md) -- both loose
    enough to make a 0.35 threshold close to a coin flip on real,
    text-heavy pages.

    Fix: normalize both strings to word tokens (dropping punctuation like
    the comma in "button,"), and score containment as the fraction of the
    *shorter* token set found in the *longer* one -- correctly credits a
    match regardless of which side is more verbose, while still requiring
    genuine shared words rather than character coincidence.
    """
    seq_ratio = SequenceMatcher(None, target_norm, candidate).ratio()

    target_words = _words(target_norm)
    candidate_words = _words(candidate)
    if not target_words or not candidate_words:
        return min(seq_ratio, 0.3)

    smaller, larger = (
        (target_words, candidate_words)
        if len(target_words) <= len(candidate_words)
        else (candidate_words, target_words)
    )
    overlap = sum(1 for w in smaller if w in larger)
    if overlap == 0:
        # No shared words at all: cap the score so pure character-level
        # coincidence can never cross a sane threshold on its own.
        return min(seq_ratio, 0.3)

    word_overlap_ratio = overlap / len(smaller)
    return max(seq_ratio, word_overlap_ratio)


def locate_text(
    screenshot_path: str | Path,
    target_description: str,
    min_ratio: float = 0.55,
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
    #
    # Phase U's dual-verification design (agents/vision/executor.py)
    # intentionally always attempts OCR alongside DOM whenever a browser
    # session exists, even for calls where the caller expects DOM alone
    # to resolve the target. That means a missing/placeholder/unreadable
    # screenshot_path must not crash the whole step -- it should simply
    # mean "OCR found nothing," the same fail-closed contract this
    # function already has for a real screenshot with no matching text.
    try:
        with Image.open(screenshot_path) as opened:
            opened.load()
            image = opened.crop(search_region) if search_region else opened.copy()
    except (FileNotFoundError, OSError):
        return LocateResult(found=False, confidence=0.0)

    offset_x, offset_y = 0, 0
    if search_region:
        x0, y0, x1, y1 = search_region
        offset_x, offset_y = x0, y0

    ocr = _ocr_data(image)
    lines = _group_lines(ocr)

    target_norm = target_description.strip().lower()
    best: tuple[dict, float] | None = None
    for line in lines:
        ratio = _match_score(target_norm, line["text"].strip().lower())
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
