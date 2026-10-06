#!/usr/bin/env python3
"""Narrated end-to-end recording: publish -> public listing -> lead capture
-> the new Website Inquiries smart-button fix -> proof.

Each named segment below corresponds 1:1 to a line in narration_lines.json
(generated separately via the hf-speech/Kokoro TTS service). This script
loads narration_audio/manifest.json for each line's real spoken duration
and holds each on-screen segment open at least that long, so the final
narration track can be laid over the recording without post-hoc timeline
editing — segment N's audio always fits inside segment N's video.

After the run, segment_timings.json records the ACTUAL wall-clock length
of every segment (always >= its narration length), which the audio-mux
step uses to pad each clip to match exactly.
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
AUDIO_DIR = HERE / "narration_audio"
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

    print(f"Recording narrated demo against {base}")
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
            segment(page, "01-intro", dur.get("01-intro", 0), lambda: (
                page.goto(f"{base}/web/login", wait_until="domcontentloaded"),
                login(page, base, args.user, args.password),
                page.goto(f"{base}/odoo/action-641", wait_until="domcontentloaded"),
                page.wait_for_timeout(1500),
            ))

            segment(page, "02-unpublished", dur.get("02-unpublished", 0), lambda: (
                page.goto(f"{base}/odoo/action-641/{PROPERTY_ID}",
                          wait_until="domcontentloaded"),
                page.wait_for_timeout(1500),
            ))

            def click_publish():
                btn = page.locator('button:has-text("Publish")').first
                if btn.count() > 0:
                    btn.click()
                    page.wait_for_timeout(1500)
                else:
                    print("[already published] ", end="")
            segment(page, "03-publish-click", dur.get("03-publish-click", 0), click_publish)

            segment(page, "04-published", dur.get("04-published", 0), lambda: None)

            def search_listing():
                page.goto(f"{base}/properties", wait_until="domcontentloaded")
                page.wait_for_timeout(1200)
                box = page.locator('form.search-box input[name="search"]').first
                box.click()
                box.fill(SEARCH_TERM)
                page.locator('form.search-box button[type="submit"]').first.click()
                page.wait_for_timeout(1200)
            segment(page, "05-public-search", dur.get("05-public-search", 0), search_listing)

            def open_detail():
                page.locator(f'a[href="/offplan/property/{PROPERTY_ID}"]').first.click()
                page.wait_for_timeout(1200)
            segment(page, "06-detail-page", dur.get("06-detail-page", 0), open_detail)

            def reveal_inquiry_form():
                page.locator('button:has-text("Inquire Now")').first.click()
                page.wait_for_timeout(500)
            segment(page, "07-inquiry-open", dur.get("07-inquiry-open", 0), reveal_inquiry_form)

            def fill_lead_form():
                page.fill('#inquiry-form input[name="name"]', LEAD["name"])
                page.fill('#inquiry-form input[name="email"]', LEAD["email"])
                page.fill('#inquiry-form input[name="phone"]', LEAD["phone"])
                page.fill('#inquiry-form textarea[name="message"]', LEAD["message"])
            segment(page, "08-inquiry-fill", dur.get("08-inquiry-fill", 0), fill_lead_form)

            def submit_lead_form():
                page.locator('#inquiry-form button[type="submit"]').first.click()
                page.wait_for_selector('#inquiry-result:not(:empty)', timeout=15000)
            segment(page, "09-inquiry-submit", dur.get("09-inquiry-submit", 0), submit_lead_form)

            segment(page, "10-gap-fix", dur.get("10-gap-fix", 0), lambda: (
                page.goto(f"{base}/odoo/action-641/{PROPERTY_ID}",
                          wait_until="domcontentloaded"),
                page.wait_for_timeout(1500),
            ))

            def click_smart_button():
                page.locator('button:has-text("Website Inquiries")').first.click()
                page.wait_for_timeout(1500)
            segment(page, "11-smart-button", dur.get("11-smart-button", 0), click_smart_button)

            def open_captured_lead():
                row = page.locator(f'tr:has-text("{LEAD["email"]}")').first
                if row.count() > 0:
                    row.click()
                    page.wait_for_timeout(1200)
            segment(page, "12-proof", dur.get("12-proof", 0), open_captured_lead)

            segment(page, "13-closing", dur.get("13-closing", 0), lambda: (
                page.goto(f"{base}/odoo/action-641/{PROPERTY_ID}",
                          wait_until="domcontentloaded"),
                page.wait_for_timeout(1000),
            ))

            print("\nDemo flow completed successfully.")
        finally:
            context.close()
            browser.close()

    new_files = [f for f in VIDEOS_DIR.glob("*.webm") if f not in pre_existing]
    video_path = None
    for f in new_files:
        target = VIDEOS_DIR / f"narrated-demo-{session_id}.webm"
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
