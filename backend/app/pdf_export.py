"""Render the brief's HTML export to PDF using headless Chromium.

The PDF is generated directly from the same HTML template used by the
HTML export (`brief_to_html`), so the two stay visually consistent by
construction — there is no separate PDF layout to drift out of sync.
"""

import os

from playwright.sync_api import sync_playwright

# Point at a specific Chromium binary if `playwright install chromium` hasn't
# been run for this interpreter (e.g. a pre-provisioned browser elsewhere on
# disk). Set ADVISORLENS_CHROMIUM_PATH to "" to force Playwright's own default
# resolution instead.
_DEFAULT_CHROMIUM_PATH = "/opt/pw-browsers/chromium" if os.path.exists(
    "/opt/pw-browsers/chromium"
) else None
CHROMIUM_PATH = os.environ.get("ADVISORLENS_CHROMIUM_PATH", _DEFAULT_CHROMIUM_PATH)

PDF_MARGIN = {"top": "0.6in", "bottom": "0.6in", "left": "0.6in", "right": "0.6in"}


class PdfRenderError(RuntimeError):
    """Raised when the headless browser could not render the report to PDF."""


def html_to_pdf_bytes(html: str) -> bytes:
    """Render an HTML string to PDF bytes via a short-lived headless browser."""
    launch_kwargs = {"executable_path": CHROMIUM_PATH} if CHROMIUM_PATH else {}
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(**launch_kwargs)
            try:
                page = browser.new_page()
                page.set_content(html, wait_until="load")
                pdf_bytes = page.pdf(
                    format="Letter",
                    print_background=True,
                    margin=PDF_MARGIN,
                )
            finally:
                browser.close()
    except Exception as exc:  # noqa: BLE001 - surface any renderer failure uniformly
        raise PdfRenderError(f"Failed to render brief to PDF: {exc}") from exc
    return pdf_bytes
