"""
Requirement document parser.

Ingests a requirement doc (Markdown, plain text, or PDF) and produces a
single normalized text blob for the spec generator to work from. No
network calls — PDF text extraction uses pypdf, which is a pure local
library.
"""
from __future__ import annotations

from pathlib import Path


def parse_requirement_file(path: str | Path) -> str:
    path = Path(path)
    suffix = path.suffix.lower()

    if suffix == ".pdf":
        return _parse_pdf(path)
    if suffix in (".md", ".markdown", ".txt"):
        return _normalize_text(path.read_text(encoding="utf-8"))

    raise ValueError(f"Unsupported requirement file type: {suffix}")


def _parse_pdf(path: Path) -> str:
    from pypdf import PdfReader

    reader = PdfReader(str(path))
    pages = [page.extract_text() or "" for page in reader.pages]
    return _normalize_text("\n".join(pages))


def _normalize_text(raw: str) -> str:
    # Collapse excessive blank lines, strip trailing whitespace per line.
    lines = [line.rstrip() for line in raw.splitlines()]
    normalized: list[str] = []
    blank_run = 0
    for line in lines:
        if line.strip() == "":
            blank_run += 1
            if blank_run > 1:
                continue
        else:
            blank_run = 0
        normalized.append(line)
    return "\n".join(normalized).strip()
