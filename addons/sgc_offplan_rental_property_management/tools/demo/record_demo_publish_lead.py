#!/usr/bin/env python3
"""End-to-end Playwright recording of a real publish + lead-capture flow.

Companion to record_demo.py (XML feed) and record_demo_rapidapi.py
(RapidAPI connectivity). This one records the actual customer-facing
path: publish a real property from the backend, find it on the public
website, submit the gated inquiry form as a visitor, then go back to
the backend and show the captured lead record.

Uses a real, pre-existing unpublished property (id=9, "Palm Jumeirah
Residences - Unit 507") rather than fabricated data.
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

PROPERTY_ID = 9
PROPERTY_NAME = "Palm Jumeirah Residences - Unit 507"
SEARCH_TERM = "Unit 507"

LEAD = {
    "name": "Ahmed Al Farsi",
    "email": "ahmed.alfarsi@example.ae",
    "phone": "+971 50 123 4567",
    "message": "Interested in this unit — please send the full floor plan and payment schedule.",
}


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


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--base", default="http://localhost:18030")
    p.add_argument("--user", default="admin")
    p.add_argument("--password", default="admin")
    p.add_argument("--viewport", default="1366,768")
    args = p.parse_args()

    base = args.base.rstrip("/")
    viewport_w, viewport_h = [int(x) for x in args.viewport.split(",")]

    print(f"Recording publish + lead-capture demo against {base}")
    print(f"Target property: id={PROPERTY_ID} ({PROPERTY_NAME})")

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

            step(page, "3-properties-list", lambda: (
                page.goto(f"{base}/odoo/action-641", wait_until="domcontentloaded"),
                page.wait_for_timeout(3000),
            ))

            step(page, "4-open-target-property", lambda: (
                page.goto(f"{base}/odoo/action-641/{PROPERTY_ID}",
                          wait_until="domcontentloaded"),
                page.wait_for_timeout(2500),
            ))

            step(page, "5-unpublished-state", lambda: page.wait_for_timeout(800))

            def click_publish():
                btn = page.locator('button:has-text("Publish")').first
                if btn.count() > 0:
                    btn.click()
                    page.wait_for_timeout(2500)
                else:
                    print("[already published, skipping] ", end="")
            step(page, "6-click-publish", click_publish)

            step(page, "7-published-state", lambda: page.wait_for_timeout(1000))

            step(page, "8-public-listing-page", lambda: (
                page.goto(f"{base}/properties", wait_until="domcontentloaded"),
                page.wait_for_timeout(2500),
            ))

            def search_listing():
                box = page.locator('form.search-box input[name="search"]').first
                box.click()
                box.fill(SEARCH_TERM)
                page.locator('form.search-box button[type="submit"]').first.click()
                page.wait_for_timeout(2500)
            step(page, "9-search-listing", search_listing)

            def open_detail():
                card = page.locator(f'a[href="/offplan/property/{PROPERTY_ID}"]').first
                card.click()
                page.wait_for_timeout(2500)
            step(page, "10-open-listing-detail", open_detail)

            step(page, "11-public-detail-page", lambda: page.wait_for_timeout(1000))

            def reveal_inquiry_form():
                page.locator('button:has-text("Inquire Now")').first.click()
                page.wait_for_timeout(800)
            step(page, "12-click-inquire-now", reveal_inquiry_form)

            def fill_lead_form():
                page.fill('#inquiry-form input[name="name"]', LEAD["name"])
                page.fill('#inquiry-form input[name="email"]', LEAD["email"])
                page.fill('#inquiry-form input[name="phone"]', LEAD["phone"])
                page.fill('#inquiry-form textarea[name="message"]', LEAD["message"])
                page.wait_for_timeout(600)
            step(page, "13-fill-lead-form", fill_lead_form)

            def submit_lead_form():
                page.locator('#inquiry-form button[type="submit"]').first.click()
                page.wait_for_selector('#inquiry-result:not(:empty)', timeout=15000)
                page.wait_for_timeout(1000)
            step(page, "14-submit-lead-form", submit_lead_form)

            step(page, "15-lead-confirmation", lambda: page.wait_for_timeout(2000))

            step(page, "16-backend-inquiries-list", lambda: (
                page.goto(f"{base}/odoo/action-667", wait_until="domcontentloaded"),
                page.wait_for_timeout(3000),
            ))

            def open_captured_lead():
                row = page.locator(f'tr:has-text("{LEAD["email"]}")').first
                if row.count() > 0:
                    row.click()
                    page.wait_for_timeout(2000)
            step(page, "17-captured-lead-record", open_captured_lead)

            print("\nDemo flow completed successfully.")
        finally:
            context.close()
            browser.close()

    new_files = [f for f in VIDEOS_DIR.glob("*.webm") if f not in pre_existing]
    for f in new_files:
        target = VIDEOS_DIR / f"publish-lead-demo-{session_id}.webm"
        f.rename(target)
        print(f"Video: {target}")


if __name__ == "__main__":
    main()
