#!/usr/bin/env python3
"""End-to-end Playwright recording of the Odoo inbound feed ingestion flow."""
import argparse
import re
import sys
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
        action()
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
    return path


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


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--base", default="http://localhost:18030")
    p.add_argument("--feed-url", default=(
        "file:///mnt/extra-addons/sgc_offplan_rental_property_management"
        "/tests/fixtures/sample_bayut_feed.xml"
    ))
    p.add_argument("--user", default="admin")
    p.add_argument("--password", default="admin")
    p.add_argument("--viewport", default="1366,768")
    args = p.parse_args()

    base = args.base.rstrip("/")
    feed_url = args.feed_url
    viewport_w, viewport_h = [int(x) for x in args.viewport.split(",")]

    print(f"Recording demo against {base}")
    print(f"Feed URL that will be set on portal.connector: {feed_url}")

    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=True,
            args=["--no-sandbox", "--disable-dev-shm-usage", "--disable-gpu"],
        )
        session_id = str(int(time.time()))
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

            step(page, "2-login",
                 lambda: login(page, base, args.user, args.password))

            step(page, "3-portal-connectors-list", lambda: (
                page.goto(f"{base}/odoo/action-784",
                          wait_until="domcontentloaded"),
                page.wait_for_timeout(3500),
            ))

            step(page, "4-open-bayut-record", lambda: (
                page.locator('tr:has-text("Bayut")').first.click(),
                page.wait_for_timeout(3000),
            ))

            step(page, "5-click-edit", lambda: (
                page.locator('button.o_form_button_edit').first.click()
                if page.locator('button.o_form_button_edit').count() > 0
                else page.wait_for_timeout(500),
                page.wait_for_timeout(2000),
            ))

            def fill_feed_url():
                inputs = page.locator('input[name="inbound_feed_url"]')
                if inputs.count() == 0:
                    inputs = page.locator(
                        'div.o_field_widget[name="inbound_feed_url"] input'
                    )
                if inputs.count() == 0:
                    inputs = page.locator(
                        'div[name="inbound_feed_url"] input'
                    )
                inputs.first.click()
                inputs.first.fill("")
                inputs.first.type(feed_url, delay=15)
                page.wait_for_timeout(1500)
            step(page, "6-set-inbound-feed-url", fill_feed_url)

            step(page, "7-save", lambda: (
                page.locator('button.o_form_button_save').first.click(
                    force=True
                ) if page.locator(
                    'button.o_form_button_save'
                ).count() > 0 else page.keyboard.press("Control+s"),
                page.wait_for_timeout(2500),
            ))

            step(page, "8-cron-list", lambda: (
                page.goto(f"{base}/odoo/action-16",
                          wait_until="domcontentloaded"),
                page.wait_for_timeout(3500),
            ))

            def run_cron():
                page.fill('input.o_searchview_input', "inbound feed")
                page.keyboard.press("Enter")
                page.wait_for_timeout(3000)
                row = page.locator(
                    'tr:has-text("Process All Inbound Feeds")'
                ).first
                if row.count() == 0:
                    page.fill('input.o_searchview_input', "")
                    page.keyboard.press("Enter")
                    page.wait_for_timeout(2000)
                    row = page.locator(
                        'tr:has-text("Process All Inbound Feeds")'
                    ).first
                row.click()
                page.wait_for_timeout(3000)
                for label in ("Run Manually", "Run Now", "Run"):
                    btn = page.locator(f'button:has-text("{label}")').first
                    if btn.count() > 0:
                        btn.click()
                        page.wait_for_timeout(4000)
                        break
            step(page, "9-run-cron", run_cron)

            step(page, "10-properties-list", lambda: (
                page.goto(f"{base}/odoo/action-641",
                          wait_until="domcontentloaded"),
                page.wait_for_timeout(3500),
            ))

            def open_first_property():
                page.fill('input.o_searchview_input', "is_feed_sourced = True")
                page.keyboard.press("Enter")
                page.wait_for_timeout(3000)
                row = page.locator('tr.o_data_row').first
                if row.count() == 0:
                    return False
                row.click()
                page.wait_for_timeout(3000)
                return True
            step(page, "11-open-feed-property", open_first_property)

            step(page, "12-sync-logs", lambda: (
                page.goto(f"{base}/odoo/action-786",
                          wait_until="domcontentloaded"),
                page.wait_for_timeout(3500),
            ))

            step(page, "13-final-overview",
                 lambda: page.wait_for_timeout(1500))

            print("\nDemo flow completed successfully.")
        finally:
            context.close()
            browser.close()

    for f in VIDEOS_DIR.glob("*.webm"):
        target = VIDEOS_DIR / f"demo-{session_id}.webm"
        if f != target:
            f.rename(target)
            print(f"Video: {target}")


if __name__ == "__main__":
    main()