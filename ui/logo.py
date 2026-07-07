"""
ui/logo.py
~~~~~~~~~~
AURA ASCII-art banner.

Usage
-----
    from ui.logo import print_banner
    print_banner()           # prints with colour via rich
    print_banner(plain=True) # plain text, no ANSI codes

Or run directly:
    python ui/logo.py
"""
from __future__ import annotations

# ── ASCII art ─────────────────────────────────────────────────────────────────
# Each tuple is (line_text, rich_style).
# The art is the original wide AURA banner; each line is printed individually
# so Rich never wraps it inside a Panel.
_ART_LINES: list[tuple[str, str]] = [
    (r"   ___      __    __  .______          ___           ______           ___      ", "bold bright_cyan"),
    (r"  /   \    |  |  |  | |   _  \        /   \         /  __  \         /   \    ", "bold cyan"),
    (r" /  ^  \   |  |  |  | |  |_)  |      /  ^  \       |  |  |  |       /  ^  \  ", "bold blue"),
    (r"/  /_\  \  |  |  |  | |      /      /  /_\  \      |  |  |  |      /  /_\  \ ", "bold bright_blue"),
    (r"\  _____/  |  `--'  | |  |\  \----./ _____   \     |  `--'  '--   /  _____  \\", "bold blue"),
    (r" \__/       \______/  |_|  `._____/__/     \__\     \_____\_____\ /__/     \__\\", "bold cyan"),
]

SUBTITLE = "Autonomous Unified RPA Agent  -  offline | vision-first | self-healing"
VERSION  = "v0.1.0"


def print_banner(*, plain: bool = False) -> None:
    """Print the AURA ASCII banner.

    Parameters
    ----------
    plain:
        When *True* output plain text with no ANSI codes (useful for log
        files or terminals that don't support colour).
    """
    if plain:
        for line, _ in _ART_LINES:
            print(line)
        print()
        print(f"  {SUBTITLE}")
        print(f"  {VERSION}")
        print()
        return

    try:
        import sys
        from rich.console import Console

        # On Windows the default cp1252 encoding can't render some characters.
        # reconfigure() switches encoding in-place WITHOUT closing the underlying
        # buffer (unlike wrapping stdout.buffer in a new TextIOWrapper, which
        # closes the buffer when the wrapper is GC'd and breaks all later prints).
        if sys.platform == "win32":
            try:
                sys.stdout.reconfigure(encoding="utf-8", errors="replace")
            except AttributeError:
                pass  # reconfigure not available; carry on with the current encoding

        console = Console(width=120, highlight=False)

        console.print()
        console.print("=" * 100, style="bright_cyan")
        for line, style in _ART_LINES:
            console.print(line, style=style, no_wrap=True, overflow="ignore")

        console.print()
        console.print(
            f"  {SUBTITLE}",
            style="dim white",
            no_wrap=True,
        )
        console.print(
            f"  {VERSION}",
            style="bold bright_magenta",
        )
        console.print("=" * 100, style="bright_cyan")
        console.print()

    except ImportError:
        # Rich not installed -- fall back to plain output
        print_banner(plain=True)


# ── Standalone usage ──────────────────────────────────────────────────────────
if __name__ == "__main__":
    print_banner()