#!/usr/bin/env python3
"""Complete narrated end-to-end recording of portal syndication:

  1. RapidAPI connectivity — Bayut, Property Finder, Dubizzle
  2. Publish a real listing + public search + gated lead capture
  3. The Website Inquiries smart-button fix, proven live
  4. Sample partner XML feed ingestion — how it works, how to run it

Each named segment corresponds 1:1 to a line in narration_lines_v2.json
(generated via Deepgram Aura-2). Segment N's on-screen dwell time is held
to at least segment N's narration length, and the ACTUAL wall-clock
duration of every segment is recorded to segment_timings_<session>.json
for build_narrated_video.py to pad/mux against afterward.
"""
import argparse
import json
import re
import time
from pathlib import Path

from playwright.sync_api import sync_playwright

HERE = Path(__file__).resolve().parent
FRAMES_DIR = HERE / "frames"
VIDEOS_DIR = HERE / "videos"
AUDIO_DIR = HERE / "narration_audio_v2"
FRAMES_DIR.mkdir(exist_ok=True)
VIDEOS_DIR.mkdir(exist_ok=True)

PROPERTY_ID = 9
SEARCH_TERM = "Unit 507"

LEAD = {
    "name": "Ahmed Al Farsi",
    "email": "ahmed.alfarsi@example.ae",
    "phone": "+971 50 123 4567",
    "message": "Interested in this unit — please send the full floor plan and payment schedule.",
}

SEGMENT_TIMINGS = []


def load_narration_durations():
    manifest_path = AUDIO_DIR / "manifest.json"
    if not manifest_path.exists():
        print(f"WARNING: no narration manifest at {manifest_path}, using 0s floors")
        return {}
    manifest = json.loads(manifest_path.read_text())
    return {m["id"]: m["duration_s"] for m in manifest}


def screenshot(page, label):
    safe = re.sub(r"[^a-z0-9]+", "-", label.lower()).strip("-")
    ts = int(time.time() * 1000)
    path = FRAMES_DIR / f"{ts:013d}-{safe}.png"
    try:
        page.screenshot(path=str(path), full_page=False)
    except Exception as e:
        print(f"  [screenshot skipped: {e}]")


def segment(page, seg_id, narration_floor, action_fn, extra_wait=0.6):
    print(f"  [{seg_id}] ", end="", flush=True)
    t0 = time.time()
    try:
        action_fn()
    except Exception as e:
        print(f"FAIL: {e}")
        raise
    elapsed = time.time() - t0
    min_dur = narration_floor + extra_wait
    if elapsed < min_dur:
        page.wait_for_timeout(int((min_dur - elapsed) * 1000))
    screenshot(page, seg_id)
    total = time.time() - t0
    SEGMENT_TIMINGS.append({"id": seg_id, "duration_s": round(total, 2)})
    print(f"OK ({total:.1f}s, narration floor {narration_floor:.1f}s)")


def login(page, base, user, password):
    page.goto(f"{base}/web/login", wait_until="domcontentloaded")
    page.wait_for_timeout(1200)
    page.fill('input#login', user)
    page.fill('input#password', password)
    page.click('button.btn.btn-primary:has-text("Log in")')
    page.wait_for_function(
        "!window.location.pathname.startsWith('/web/login')", timeout=20000,
    )


def rapidapi_test(page, base, row_text):
    """Open a connector, click Test RapidAPI Connection, wait for the toast."""
    page.goto(f"{base}/odoo/action-784", wait_until="domcontentloaded")
    page.wait_for_timeout(1500)
    page.locator(f'tr:has-text("{row_text}")').first.click()
    page.wait_for_timeout(1500)
    btn = page.locator('button:has-text("Test RapidAPI Connection")').first
    btn.click()
    page.wait_for_selector('.o_notification, .o_notification_body', timeout=15000)
    page.wait_for_timeout(400)


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--base", default="http://localhost:18030")
    p.add_argument("--user", default="admin")
    p.add_argument("--password", default="admin")
    p.add_argument("--viewport", default="1366,768")
    args = p.parse_args()

    base = args.base.rstrip("/")
    viewport_w, viewport_h = [int(x) for x in args.viewport.split(",")]
    dur = load_narration_durations()

    print(f"Recording complete narrated demo against {base}")

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
            # ---- 1. Intro ----
            segment(page, "01-intro", dur.get("01-intro", 0), lambda: (
                page.goto(f"{base}/web/login", wait_until="domcontentloaded"),
                login(page, base, args.user, args.password),
                page.goto(f"{base}/odoo/action-784", wait_until="domcontentloaded"),
                page.wait_for_timeout(1500),
            ))

            # ---- 2. RapidAPI connectivity: Bayut, Property Finder, Dubizzle ----
            segment(page, "02-rapidapi-intro", dur.get("02-rapidapi-intro", 0), lambda: None)
            segment(page, "03-rapidapi-bayut", dur.get("03-rapidapi-bayut", 0),
                    lambda: rapidapi_test(page, base, "Bayut-1"))
            segment(page, "04-rapidapi-pf", dur.get("04-rapidapi-pf", 0),
                    lambda: rapidapi_test(page, base, "Property Finder"))
            segment(page, "05-rapidapi-dubizzle", dur.get("05-rapidapi-dubizzle", 0),
                    lambda: rapidapi_test(page, base, "Dubizzle"))
            segment(page, "06-rapidapi-note", dur.get("06-rapidapi-note", 0), lambda: None)

            # ---- 3. Publish + public search + lead capture ----
            segment(page, "07-publish-unpublished", dur.get("07-publish-unpublished", 0), lambda: (
                page.goto(f"{base}/odoo/action-641/{PROPERTY_ID}", wait_until="domcontentloaded"),
                page.wait_for_timeout(1500),
            ))

            def click_publish():
                btn = page.locator('button:has-text("Publish")').first
                if btn.count() > 0:
                    btn.click()
                    page.wait_for_timeout(1500)
                else:
                    print("[already published] ", end="")
            segment(page, "08-publish-click", dur.get("08-publish-click", 0), click_publish)

            segment(page, "09-publish-confirm", dur.get("09-publish-confirm", 0), lambda: None)

            def search_listing():
                page.goto(f"{base}/properties", wait_until="domcontentloaded")
                page.wait_for_timeout(1200)
                box = page.locator('form.search-box input[name="search"]').first
                box.click()
                box.fill(SEARCH_TERM)
                page.locator('form.search-box button[type="submit"]').first.click()
                page.wait_for_timeout(1200)
            segment(page, "10-public-search", dur.get("10-public-search", 0), search_listing)

            def open_detail():
                page.locator(f'a[href="/offplan/property/{PROPERTY_ID}"]').first.click()
                page.wait_for_timeout(1200)
            segment(page, "11-public-detail", dur.get("11-public-detail", 0), open_detail)

            def reveal_inquiry_form():
                # The logged-in-admin website-editor toolbar can overlay the
                # page and intercept pointer events during its own load;
                # force=True bypasses that actionability check since the
                # button itself is genuinely visible and enabled underneath.
                page.locator('button:has-text("Inquire Now")').first.click(force=True)
                page.wait_for_timeout(500)
            segment(page, "12-inquiry-open", dur.get("12-inquiry-open", 0), reveal_inquiry_form)

            def fill_lead_form():
                page.fill('#inquiry-form input[name="name"]', LEAD["name"])
                page.fill('#inquiry-form input[name="email"]', LEAD["email"])
                page.fill('#inquiry-form input[name="phone"]', LEAD["phone"])
                page.fill('#inquiry-form textarea[name="message"]', LEAD["message"])
            segment(page, "13-inquiry-fill", dur.get("13-inquiry-fill", 0), fill_lead_form)

            def submit_lead_form():
                page.locator('#inquiry-form button[type="submit"]').first.click(force=True)
                page.wait_for_selector('#inquiry-result:not(:empty)', timeout=15000)
            segment(page, "14-inquiry-submit", dur.get("14-inquiry-submit", 0), submit_lead_form)

            # ---- 4. The Website Inquiries smart-button fix ----
            segment(page, "15-gap-fix-intro", dur.get("15-gap-fix-intro", 0), lambda: (
                page.goto(f"{base}/odoo/action-641/{PROPERTY_ID}", wait_until="domcontentloaded"),
                page.wait_for_timeout(1500),
            ))

            def click_smart_button():
                page.locator('button:has-text("Website Inquiries")').first.click()
                page.wait_for_timeout(1500)
            segment(page, "16-smart-button-click", dur.get("16-smart-button-click", 0), click_smart_button)

            def open_captured_lead():
                row = page.locator(f'tr:has-text("{LEAD["email"]}")').first
                if row.count() > 0:
                    row.click()
                    page.wait_for_timeout(1200)
            segment(page, "17-smart-button-proof", dur.get("17-smart-button-proof", 0), open_captured_lead)

            # ---- 5. Sample partner feed ingestion ----
            segment(page, "18-feed-intro", dur.get("18-feed-intro", 0), lambda: (
                page.goto(f"{base}/odoo/action-784", wait_until="domcontentloaded"),
                page.wait_for_timeout(1200),
                page.locator('tr:has-text("Bayut-1")').first.click(),
                page.wait_for_timeout(1500),
            ))

            segment(page, "19-feed-config", dur.get("19-feed-config", 0), lambda: None)

            def run_feed_cron():
                page.goto(f"{base}/odoo/action-16", wait_until="domcontentloaded")
                page.wait_for_timeout(1500)
                search = page.locator('input.o_searchview_input').first
                search.fill("inbound feed")
                page.keyboard.press("Enter")
                page.wait_for_timeout(1500)
                row = page.locator('tr:has-text("Process All Inbound Feeds")').first
                if row.count() == 0:
                    search.fill("")
                    page.keyboard.press("Enter")
                    page.wait_for_timeout(1200)
                    row = page.locator('tr:has-text("Process All Inbound Feeds")').first
                row.click()
                page.wait_for_timeout(1500)
                for label in ("Run Manually", "Run Now", "Run"):
                    btn = page.locator(f'button:has-text("{label}")').first
                    if btn.count() > 0:
                        btn.click()
                        page.wait_for_timeout(2500)
                        break
            segment(page, "20-feed-run", dur.get("20-feed-run", 0), run_feed_cron)

            def show_feed_result():
                page.goto(f"{base}/odoo/action-641", wait_until="domcontentloaded")
                page.wait_for_timeout(1200)
                search = page.locator('input.o_searchview_input').first
                search.fill("is_feed_sourced = True")
                page.keyboard.press("Enter")
                page.wait_for_timeout(1500)
            segment(page, "21-feed-result", dur.get("21-feed-result", 0), show_feed_result)

            # ---- 6. Closing ----
            segment(page, "22-closing", dur.get("22-closing", 0), lambda: page.wait_for_timeout(500))

            print("\nDemo flow completed successfully.")
        finally:
            context.close()
            browser.close()

    new_files = [f for f in VIDEOS_DIR.glob("*.webm") if f not in pre_existing]
    video_path = None
    for f in new_files:
        target = VIDEOS_DIR / f"complete-demo-{session_id}.webm"
        f.rename(target)
        video_path = target
        print(f"Video: {target}")

    timings_path = HERE / f"segment_timings_{session_id}.json"
    timings_path.write_text(json.dumps(SEGMENT_TIMINGS, indent=2))
    print(f"Segment timings: {timings_path}")
    if video_path:
        print(f"SESSION_ID={session_id}")


if __name__ == "__main__":
    main()
