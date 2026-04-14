"""Screenshot the dashboard with the myapp detail panel expanded.

Run: python scripts/gen_detail_screenshot.py
Output: assets/dashboard-detail.png
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))


def main() -> None:
    from playwright.sync_api import sync_playwright
    from PIL import Image

    html_path = Path(__file__).parent.parent / "assets" / "dashboard-demo.html"
    png_path = Path(__file__).parent.parent / "assets" / "dashboard-detail.png"
    tmp_path = Path(__file__).parent.parent / "assets" / "_detail_full.png"

    if not html_path.exists():
        print(f"ERROR: {html_path} not found — run gen_demo_dashboard.py first")
        sys.exit(1)

    html_url = html_path.as_uri()
    chrome = r"C:\Program Files\Google\Chrome\Application\chrome.exe"

    with sync_playwright() as p:
        browser = p.chromium.launch(executable_path=chrome, headless=True)
        # Tall viewport so we can see everything without scroll
        page = browser.new_page(viewport={"width": 1440, "height": 1100})
        page.goto(html_url)
        page.wait_for_timeout(1200)

        # Click the myapp card (data-idx="2")
        myapp_card = page.locator('[data-idx="2"]')
        myapp_card.scroll_into_view_if_needed()
        myapp_card.click()
        page.wait_for_timeout(800)  # wait for detail panel animation

        # Take full-page screenshot so we capture everything
        page.screenshot(path=str(tmp_path), full_page=True)
        browser.close()

    print(f"Full screenshot: {tmp_path}")

    # Crop: keep header + project grid + detail panel; drop fleet summary
    # Strategy: find the first pixel row that's background-only *after* the
    # detail panel ends.  Simpler: just keep the top 1380 px which comfortably
    # contains header + grid + full detail panel for myapp.
    img = Image.open(tmp_path)
    width, height = img.size
    print(f"Full image size: {width}x{height}")

    # Crop to a sensible height that shows all the relevant content
    crop_height = min(height, 1350)
    cropped = img.crop((0, 0, width, crop_height))
    cropped.save(png_path, optimize=True)
    print(f"Cropped to {width}x{crop_height} -> {png_path}")

    # Clean up temp file
    tmp_path.unlink(missing_ok=True)


if __name__ == "__main__":
    main()
