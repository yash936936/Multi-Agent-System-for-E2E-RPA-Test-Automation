"""
Demo login app — target_app/demo_login_app.py

A minimal Tkinter login form used purely as the "app under test" for
manual demos and integration tests. Matches the fields referenced in
requirements_input/example_login_flow.md (Login button, Username field,
Password field, Submit button, Dashboard).

Run directly on a machine with a display:

    python target_app/demo_login_app.py

Then point `aura execute TC-LOGIN-FLOW-001` at it once Phase 6's CLI
wiring is in place. This file requires a live display (Tkinter/Tk) and
is not imported by any automated test — tests/test_run_engine.py instead
uses render_login_screen() below to produce the same visual layout as a
static PNG, so the run engine can be exercised in headless CI without a
real window manager.
"""
from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

# Candidate TrueType font paths across the OSes AURA might actually be
# developed/tested on (Linux/CI, macOS, Windows). We try these in order
# and fall back to Pillow's built-in bitmap font if none exist, so this
# module (and tests/test_vision.py, which reuses resolve_font()) never
# hard-fails just because a specific distro's font package isn't
# installed -- OCR accuracy is what matters for the tests, not which font
# renders it.
_FONT_CANDIDATES = [
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",          # Debian/Ubuntu
    "/usr/share/fonts/dejavu/DejaVuSans-Bold.ttf",                    # Fedora/RHEL
    "/usr/local/share/fonts/DejaVuSans-Bold.ttf",                     # manual installs
    "/System/Library/Fonts/Supplemental/Arial Bold.ttf",              # macOS
    "/Library/Fonts/Arial Bold.ttf",                                  # macOS (older)
    "C:\\Windows\\Fonts\\arialbd.ttf",                                # Windows (Arial Bold)
    "C:\\Windows\\Fonts\\segoeuib.ttf",                               # Windows (Segoe UI Bold)
]

_font_cache: dict[int, "ImageFont.ImageFont | ImageFont.FreeTypeFont"] = {}


def resolve_font(size: int = 22) -> "ImageFont.ImageFont | ImageFont.FreeTypeFont":
    """
    Returns a usable font at the given size, trying real TrueType fonts
    first (better OCR results — pytesseract reads clean vector-rendered
    text far more reliably than Pillow's tiny built-in bitmap font) and
    falling back to ImageFont.load_default() if nothing on this machine
    matches _FONT_CANDIDATES.
    """
    if size in _font_cache:
        return _font_cache[size]

    for path in _FONT_CANDIDATES:
        if Path(path).exists():
            font = ImageFont.truetype(path, size)
            _font_cache[size] = font
            return font

    # Nothing found: Pillow's bundled default font. Newer Pillow (>=10.1)
    # accepts a `size` kwarg here; older versions ignore it and always
    # render at a small fixed size, which still works for OCR, just less
    # crisply -- acceptable as a last-resort fallback.
    try:
        font = ImageFont.load_default(size=size)
    except TypeError:
        font = ImageFont.load_default()
    _font_cache[size] = font
    return font


FONT_PATH = _FONT_CANDIDATES[0]  # kept for backwards-compat with any external reference


class DemoLoginApp:
    def __init__(self) -> None:
        import tkinter as tk  # deferred: only needed if you actually launch the GUI

        self.root = tk.Tk()
        self.root.title("AURA Demo App")
        self.root.geometry("800x600")

        self.login_btn = tk.Button(self.root, text="Login Button", command=self._show_login_form)
        self.login_btn.place(x=650, y=20)

        self.username_label = tk.Label(self.root, text="Username Field")
        self.password_label = tk.Label(self.root, text="Password Field")
        self.username_entry = tk.Entry(self.root)
        self.password_entry = tk.Entry(self.root, show="*")
        self.submit_btn = tk.Button(self.root, text="Submit Button", command=self._submit)

        self.dashboard_label = tk.Label(self.root, text="Dashboard Visible", font=("DejaVu Sans", 20))

        self._form_visible = False

    def _show_login_form(self) -> None:
        self.username_label.place(x=200, y=100)
        self.username_entry.place(x=200, y=125)
        self.password_label.place(x=200, y=170)
        self.password_entry.place(x=200, y=195)
        self.submit_btn.place(x=200, y=240)
        self._form_visible = True

    def _submit(self) -> None:
        for w in (self.username_label, self.username_entry, self.password_label, self.password_entry, self.submit_btn):
            w.place_forget()
        self.dashboard_label.place(x=250, y=250)

    def run(self) -> None:
        self.root.mainloop()


# --------------------------------------------------------------------------
# Headless-safe static-screenshot renderer, used by the test harness and by
# anyone who wants to see what each screen state looks like without a
# display. Deliberately mirrors the coordinates above.
# --------------------------------------------------------------------------

_SCREENS = {
    "initial": [("Login Button", (630, 20))],
    "login_form": [
        ("Login Button", (630, 20)),
        ("Username Field", (200, 100)),
        ("Password Field", (200, 170)),
        ("Submit Button", (200, 240)),
    ],
    "dashboard": [("Dashboard Visible", (250, 250))],
}


def render_login_screen(state: str, out_path: str | Path, size: tuple[int, int] = (800, 600)) -> Path:
    if state not in _SCREENS:
        raise ValueError(f"Unknown demo app state '{state}'. Valid: {list(_SCREENS)}")

    img = Image.new("RGB", size, color="white")
    draw = ImageDraw.Draw(img)
    font = resolve_font(22)
    for text, pos in _SCREENS[state]:
        draw.text(pos, text, fill="black", font=font)

    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    img.save(out_path)
    return out_path


if __name__ == "__main__":
    DemoLoginApp().run()
