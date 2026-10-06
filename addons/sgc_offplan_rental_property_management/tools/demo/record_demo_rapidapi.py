#!/usr/bin/env python3
"""End-to-end Playwright recording of the RapidAPI connectivity test flow.

Companion to record_demo.py (which records the XML feed ingestion flow).
This one records the *other* integration on the same screen: the
"Test RapidAPI Connection" button on portal.connector, added in
19.0.2.29/30, that checks Bayut/Property Finder/Dubizzle market-data
reachability via RapidAPI.
"""
import argparse
import re
import time
from pathlib import Path

from playwright.sync_api import sync_playwright

HERE = Path(__file__).resolve().parent
FRAMES_DIR = HERE / "frames"
VIDEOS_DIR = HERE / "videos"
FRAMES_DIR.mkdir(exist_ok=True)
VIDEOS_DIR.mkdir(exist_ok=True)


def step(page, label, action):
    print(f"  [{label}] ", end="", flush=True)
    t0 = time.time()
    try:
        result = action()
    except Exception as e:
        print(f"FAIL: {e}")
        raise
    dt = time.time() - t0
    safe = re.sub(r"[^a-z0-9]+", "-", label.lower()).strip("-")
    ts = int(time.time() * 1000)
    path = FRAMES_DIR / f"{ts:013d}-{safe}.png"
    try:
        page.screenshot(path=str(path), full_page=False)
        print(f"OK ({dt:.1f}s) -> {path.name}")
    except Exception as e:
        print(f"OK ({dt:.1f}s) [screenshot skipped: {e}]")
    return result


def login(page, base, user, password):
    page.goto(f"{base}/web/login", wait_until="domcontentloaded")
    page.wait_for_timeout(1500)
    page.fill('input#login', user)
    page.fill('input#password', password)
    page.click('button.btn.btn-primary:has-text("Log in")')
    page.wait_for_function(
        "!window.location.pathname.startsWith('/web/login')",
        timeout=20000,
    )
    page.wait_for_timeout(2000)


def test_connector(page, base, row_text, label_prefix):
    """Open one connector record, click Test RapidAPI Connection, watch the
    toast, then open the Logs tab to show history."""

    step(page, f"{label_prefix}-open-record", lambda: (
        page.goto(f"{base}/odoo/action-784", wait_until="domcontentloaded"),
        page.wait_for_timeout(2500),
        page.locator(f'tr:has-text("{row_text}")').first.click(),
        page.wait_for_timeout(2000),
    ))

    step(page, f"{label_prefix}-show-form", lambda: page.wait_for_timeout(1000))

    def click_test_button():
        btn = page.locator('button:has-text("Test RapidAPI Connection")').first
        btn.click()
        # Poll for the toast rather than a fixed sleep, so the recording
        # captures it near-peak-opacity instead of mid-fade.
        page.wait_for_selector(
            '.o_notification, .o_notification_body',
            timeout=15000,
        )
        page.wait_for_timeout(400)
    step(page, f"{label_prefix}-click-test-button", click_test_button)

    step(page, f"{label_prefix}-toast-result", lambda: page.wait_for_timeout(2000))

    def open_logs_tab():
        tab = page.locator('a:has-text("Logs")').first
        if tab.count() > 0:
            tab.click()
            page.wait_for_timeout(1500)
    step(page, f"{label_prefix}-logs-tab", open_logs_tab)


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--base", default="http://localhost:18030")
    p.add_argument("--user", default="admin")
    p.add_argument("--password", default="admin")
    p.add_argument("--viewport", default="1366,768")
    args = p.parse_args()

    base = args.base.rstrip("/")
    viewport_w, viewport_h = [int(x) for x in args.viewport.split(",")]

    print(f"Recording RapidAPI connectivity demo against {base}")

    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=True,
            args=["--no-sandbox", "--disable-dev-shm-usage", "--disable-gpu"],
        )
        session_id = str(int(time.time()))
        pre_existing = set(VIDEOS_DIR.glob("*.webm"))
        context = browser.new_context(
            viewport={"width": viewport_w, "height": viewport_h},
            record_video_dir=str(VIDEOS_DIR),
            record_video_size={"width": viewport_w, "height": viewport_h},
            ignore_https_errors=True,
        )
        page = context.new_page()

        try:
            step(page, "1-open-login", lambda: page.goto(
                f"{base}/web/login", wait_until="domcontentloaded",
            ))

            step(page, "2-login", lambda: login(page, base, args.user, args.password))

            step(page, "3-portal-connectors-list", lambda: (
                page.goto(f"{base}/odoo/action-784", wait_until="domcontentloaded"),
                page.wait_for_timeout(3000),
            ))

            test_connector(page, base, "Property Finder", "4")
            test_connector(page, base, "Bayut", "5")

            step(page, "6-back-to-list", lambda: (
                page.goto(f"{base}/odoo/action-784", wait_until="domcontentloaded"),
                page.wait_for_timeout(2500),
            ))

            step(page, "7-final-overview", lambda: page.wait_for_timeout(1500))

            print("\nDemo flow completed successfully.")
        finally:
            context.close()
            browser.close()

    new_files = [f for f in VIDEOS_DIR.glob("*.webm") if f not in pre_existing]
    for f in new_files:
        target = VIDEOS_DIR / f"rapidapi-demo-{session_id}.webm"
        f.rename(target)
        print(f"Video: {target}")


if __name__ == "__main__":
    main()
