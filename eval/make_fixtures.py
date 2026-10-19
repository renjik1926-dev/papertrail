"""Render the synthetic letter templates to PDF with Playwright's Chromium.

Generate once and commit the PDFs: different Chromium versions produce slightly different
files, which would change the golden block dumps and the request hashes. CI never runs this.

    uv run --project backend --group fixtures python eval/make_fixtures.py

Outputs:
  eval/docs/<name>.pdf              one per eval/templates/*.html
  backend/tests/fixtures/*.pdf      parser fixtures (plain, two columns, rotated, cropped,
                                    scanned, encrypted, 51 pages, privacy marker)
"""

from __future__ import annotations

import base64
import io
import tempfile
from pathlib import Path

from playwright.sync_api import Page, sync_playwright
from pypdf import PdfReader, PdfWriter
from pypdf.generic import RectangleObject

ROOT = Path(__file__).resolve().parent.parent
TEMPLATES = ROOT / "eval" / "templates"
EVAL_DOCS = ROOT / "eval" / "docs"
FIXTURES = ROOT / "backend" / "tests" / "fixtures"

# Fixed metadata so regenerating doesn't change bytes for no reason.
METADATA = {"/Producer": "PaperTrail fixtures", "/Creator": "eval/make_fixtures.py"}


def render(page: Page, template: Path) -> bytes:
    page.goto(template.as_uri())
    page.emulate_media(media="print")
    return page.pdf(format="Letter", print_background=True, prefer_css_page_size=True)


def normalized(pdf_bytes: bytes) -> PdfWriter:
    """Copy into a fresh writer with fixed metadata (drops Chromium's creation date)."""
    writer = PdfWriter(clone_from=PdfReader(io.BytesIO(pdf_bytes)))
    writer.metadata = None
    writer.add_metadata(METADATA)
    return writer


def save(writer: PdfWriter, out: Path) -> None:
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("wb") as handle:
        writer.write(handle)
    print(f"wrote {out.relative_to(ROOT)}")


def scanned_pdf(page: Page, template: Path) -> bytes:
    """A 'scan': a screenshot of a rendered letter placed on a page as the only content."""
    page.set_viewport_size({"width": 816, "height": 1056})  # 8.5 x 11 in at 96 dpi
    page.goto(template.as_uri())
    png = page.screenshot(full_page=False)
    data_url = "data:image/png;base64," + base64.b64encode(png).decode("ascii")
    html = (
        "<!doctype html><html><head><style>@page{size:Letter;margin:0}"
        "body{margin:0}img{width:8.5in;height:11in;display:block}</style></head>"
        f'<body><img src="{data_url}" alt=""></body></html>'
    )
    with tempfile.TemporaryDirectory() as tmp:
        holder = Path(tmp) / "scan.html"
        holder.write_text(html, encoding="utf-8")
        return render(page, holder)


def main() -> None:
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        page = browser.new_page()

        for template in sorted(TEMPLATES.glob("*.html")):
            save(normalized(render(page, template)), EVAL_DOCS / f"{template.stem}.pdf")

        fixture_templates = TEMPLATES / "fixtures"
        for name in ("plain_letter", "two_columns", "privacy_marker", "fifty_one_pages"):
            save(
                normalized(render(page, fixture_templates / f"{name}.html")),
                FIXTURES / f"{name}.pdf",
            )

        plain = render(page, fixture_templates / "plain_letter.html")

        rotated = normalized(plain)
        rotated.pages[0].rotate(90)
        save(rotated, FIXTURES / "rotated.pdf")

        cropped = normalized(plain)
        box = cropped.pages[0].mediabox
        # Trim 36 pt from the left and 72 pt from the top of the visible area.
        cropped.pages[0].cropbox = RectangleObject(
            (float(box.left) + 36, float(box.bottom), float(box.right), float(box.top) - 72)
        )
        save(cropped, FIXTURES / "cropped.pdf")

        encrypted = normalized(plain)
        # Throwaway passwords for a test fixture, not secrets.
        encrypted.encrypt(user_password="fixture-user", owner_password="fixture-owner")  # noqa: S106
        save(encrypted, FIXTURES / "encrypted.pdf")

        save(
            normalized(scanned_pdf(page, TEMPLATES / "medical_bill_01.html")),
            FIXTURES / "scanned.pdf",
        )

        browser.close()


if __name__ == "__main__":
    main()
