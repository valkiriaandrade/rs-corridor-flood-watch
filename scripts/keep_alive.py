"""Keep the Streamlit Community Cloud app awake.

Opens the app in a headless browser; if the "gone to sleep" page is shown,
clicks the wake-up button and waits for the app to start.

Usage: python scripts/keep_alive.py https://<app>.streamlit.app
"""

import sys

from playwright.sync_api import TimeoutError as PlaywrightTimeout
from playwright.sync_api import sync_playwright

WAKE_BUTTON = "button:has-text('get this app back up')"


def main(url: str) -> int:
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page()
        page.goto(url, wait_until="domcontentloaded", timeout=60_000)
        page.wait_for_timeout(10_000)

        button = page.locator(WAKE_BUTTON)
        if button.count() > 0:
            print("App asleep - clicking wake-up button.")
            button.first.click()
            try:
                button.first.wait_for(state="detached", timeout=180_000)
            except PlaywrightTimeout:
                print("Wake-up button still visible after 3 minutes.")
                browser.close()
                return 1
            page.wait_for_timeout(30_000)
            print("App woken up.")
        else:
            print("App already awake.")

        browser.close()
    return 0


if __name__ == "__main__":
    if len(sys.argv) != 2 or not sys.argv[1].startswith("http"):
        sys.exit("Usage: python scripts/keep_alive.py <app-url>")
    sys.exit(main(sys.argv[1]))
