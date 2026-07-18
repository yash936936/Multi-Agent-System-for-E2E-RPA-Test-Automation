"""
Tests for agents/vision/locator.py -- specifically the two bugs found
from a real Windows pytest run against a live browser (not reproducible
in a sandbox without a real Chromium binary, so these are synthetic/unit
reproductions of the exact failure shapes seen there):

1. locate_text() crashed with an unhandled FileNotFoundError when given
   a missing/placeholder screenshot path, even though Phase U's
   dual-verification design (agents/vision/executor.py) intentionally
   always attempts OCR alongside DOM whenever a browser session exists --
   including calls where the caller expects DOM alone to resolve the
   target and never provides a real screenshot at all.

2. _group_lines() let a low-confidence noise-glyph OCR detection (a
   misread border/icon fragment as e.g. '|' or '[') widen a real text
   line's bounding box, skewing its centroid away from the actual
   clickable text -- even though _match_score()'s word-tokenizer
   correctly scored the *text* as a match (punctuation is stripped before
   comparison), the *coordinates* were wrong, so the resulting click
   missed the real target. Real captured case: OCR line "[Login Button
   |)" scored 0.99 confidence against target "Login Button" but the click
   dispatched to a position offset from the actual button.
"""
from __future__ import annotations

from agents.vision.locator import _group_lines, locate_text


def test_locate_text_missing_screenshot_fails_closed_not_a_crash():
    """A missing screenshot_path must return found=False, not raise --
    Phase U calls this unconditionally even when a browser session is
    expected to resolve everything via DOM, so a placeholder/nonexistent
    path is an expected input, not an error condition."""
    result = locate_text("/tmp/definitely_does_not_exist_aura_test.png", "Login Button")
    assert result.found is False
    assert result.confidence == 0.0


def test_locate_text_unreadable_file_fails_closed_not_a_crash(tmp_path):
    """A path that exists but isn't a valid image (e.g. a truncated/
    corrupt file, or a stray non-image file at that path) must also fail
    closed via the same OSError branch PIL's UnidentifiedImageError
    subclasses, not propagate a raw exception."""
    bad_file = tmp_path / "not_an_image.png"
    bad_file.write_bytes(b"this is not valid image data")
    result = locate_text(str(bad_file), "Login Button")
    assert result.found is False
    assert result.confidence == 0.0


def _ocr_row(text, conf, left, top, width=None, height=16, block=1, par=1, line=1):
    width = width if width is not None else max(8, len(text) * 10)
    return {"text": text, "conf": conf, "left": left, "top": top, "width": width, "height": height, "block_num": block, "par_num": par, "line_num": line}


def _build_ocr_dict(rows: list[dict]) -> dict:
    keys = ["text", "conf", "left", "top", "width", "height", "block_num", "par_num", "line_num"]
    return {k: [r[k] for r in rows] for k in keys}


def test_group_lines_excludes_low_confidence_noise_from_text_and_bbox():
    """
    Reproduces the real captured bug: a genuine 'Login Button' detection
    (high confidence) sharing tesseract's line grouping with low-
    confidence noise-glyph misreads on either side. The noise must not
    appear in the joined text, and must not widen the bbox/skew the
    centroid.
    """
    rows = [
        _ocr_row("[", 12, left=50, top=18, width=8),       # noise glyph, low confidence
        _ocr_row("Login", 96, left=100, top=18, width=55),  # real text, high confidence
        _ocr_row("Button", 94, left=160, top=18, width=60),  # real text, high confidence
        _ocr_row("|", 8, left=280, top=19, width=6),        # noise glyph, low confidence
        _ocr_row(")", 5, left=300, top=19, width=6),        # noise glyph, low confidence
    ]
    lines = _group_lines(_build_ocr_dict(rows))

    assert len(lines) == 1
    line = lines[0]
    assert line["text"] == "Login Button", f"noise glyphs leaked into joined text: {line['text']!r}"
    # Real text spans x=[100, 220] -- centroid should be ~160, not skewed
    # toward the noise glyphs at x=50 or x=306 (which would happen if the
    # bbox spanned the full [50, 306] noise-inclusive range: cx=178).
    assert 150 <= line["cx"] <= 170, f"bbox/centroid skewed by noise glyphs: cx={line['cx']}"


def test_group_lines_all_high_confidence_words_unaffected():
    """A normal, fully-legible OCR line (all words high confidence) must
    behave exactly as before -- this fix should never filter real text."""
    rows = [
        _ocr_row("Sign", 92, left=100, top=18, width=45),
        _ocr_row("In", 90, left=150, top=18, width=25),
    ]
    lines = _group_lines(_build_ocr_dict(rows))
    assert len(lines) == 1
    assert lines[0]["text"] == "Sign In"


def test_group_lines_missing_conf_field_does_not_filter_anything():
    """A hand-built OCR dict without a 'conf' key (e.g. an older test
    fixture, or a caller that doesn't populate it) must not have its text
    silently dropped -- the confidence filter degrades to a no-op rather
    than a false rejection when confidence data simply isn't available."""
    ocr = {
        "text": ["Login", "Button"],
        "left": [100, 160],
        "top": [18, 18],
        "width": [55, 60],
        "height": [16, 16],
        "block_num": [1, 1],
        "par_num": [1, 1],
        "line_num": [1, 1],
    }
    lines = _group_lines(ocr)
    assert len(lines) == 1
    assert lines[0]["text"] == "Login Button"


def test_group_lines_line_with_only_noise_produces_no_line():
    """If every word on a detected line is below the confidence
    threshold, that line contributes nothing -- not an empty-text line
    with a bogus bbox."""
    rows = [
        _ocr_row("|", 5, left=50, top=18, width=6),
        _ocr_row(")", 3, left=60, top=18, width=6),
    ]
    lines = _group_lines(_build_ocr_dict(rows))
    assert lines == []
