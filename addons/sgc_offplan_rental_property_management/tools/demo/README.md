# End-to-end demo recording pipeline

Self-contained pipeline that records a real browser session showing the
inbound XML feed ingestion flow (Bayut / Dubizzle XML → Odoo →
property.details records), produces a playable MP4, and emits
per-step screenshots.

## What you get

After `run_demo.sh` finishes you'll have:

```
tools/demo/
├── run_demo.sh                    # one-command orchestrator
├── record_demo.py                 # Playwright browser driver
├── feed_server.py                 # tiny HTTP server for the sample feed
├── videos/
│   ├── demo-<ts>.webm             # raw Playwright recording
│   └── demo-<ts>.mp4              # final MP4 (libx264, 1366x768)
├── frames/<ts>-<step>.png         # 13 per-step screenshots
└── audio/                         # narration, if espeak-ng is installed
```

The latest demo run produces:
- `videos/demo-1787057337.mp4` (1.9 MB, 102 s, 1366x768, H.264)
- 13 PNG screenshots covering every step

## How it works

1. `feed_server.py` (optional) serves the sample XML feed over HTTP
   for an `http://` feed URL. Skipped when the feed URL is `file://`.
2. `record_demo.py` launches headless Chromium, drives it through the
   Odoo UI, and records the browser viewport via Playwright's
   `recordVideo` API. Each step writes a frame to `frames/`.
3. `ffmpeg` re-encodes the raw `.webm` into a final `.mp4` with
   `libx264 -preset medium -crf 23 -movflags +faststart`.
4. (Optional) `espeak-ng` generates a narration WAV and ffmpeg muxes it
   with the MP4.

## Recorded flow (13 steps)

1. Open `/web/login`
2. Login as admin
3. Open Portal Connectors list
4. Click into the Bayut record
5. Click Edit
6. Set `inbound_feed_url` to the configured feed URL
7. Save
8. Open Scheduled Actions
9. Filter to "inbound feed", open the cron, click Run Manually
10. Open Properties list
11. Filter to `is_feed_sourced = True`, open the first property
12. Open Sync Logs
13. Final overview

## Run it

```bash
cd sgc_offplan_rental_property_management/tools/demo

# Defaults: Odoo at localhost:18030, feed URL is file:// inside the
# demo_presentation container.
./run_demo.sh

# Override Odoo base URL
ODOO_BASE=http://demo.sgctech.ai ./run_demo.sh

# Run against a remote HTTP feed
FEED_URL=http://localhost:18099/sample_bayut_feed.xml ./run_demo.sh
```

## Prerequisites

```bash
# Ubuntu / Debian
sudo apt-get install -y --no-install-recommends ffmpeg espeak-ng
pip3 install --break-system-packages playwright
python3 -m playwright install chromium
```

## Tweaking the demo

| What to change | How |
|---|---|
| Window size | `record_demo.py --viewport 1920,1080` |
| Login credentials | `record_demo.py --user X --password Y` |
| Different Odoo URL | `record_demo.py --base http://other.host:port` |
| Different feed | `--feed-url http://your.feed.example.com/feed.xml` |
| Browser | Edit the `chromium.launch(...)` call in `record_demo.py` |
| Speed of recording | Increase `wait_for_timeout(...)` between steps |
| Add a step | Wrap a new `step(page, "N-name", lambda: ...)` in the try block |
| Narration text | Edit `/tmp/narration.txt` in `run_demo.sh` (or just supply your own WAV to ffmpeg) |

## Known quirks

- The cron URL `/odoo/action-16` is the Odoo 19 `base.ir_cron_act`
  action. If the action ID ever changes, re-derive with:
  `ir.model.data` search for `(module='base', name='ir_cron_act')`.
- The Save button in Odoo 19's form view is sometimes rendered off-screen
  in narrow viewports. The demo uses `button.o_form_button_save` with
  `force=True` and falls back to `Ctrl+S`.
- The demo assumes the `sgc_offplan_rental_property_management` module
  is installed and the `portal.connector` model has at least one
  Bayut-coded record. The cleanup step in `run_demo.sh` does NOT wipe
  pre-existing data — wipe manually if you need a clean slate:

  ```python
  # via xmlrpc
  models.execute_kw(db, uid, pw,
      "property.portal.line", "unlink",
      [models.execute_kw(db, uid, pw,
          "property.portal.line", "search", [[]])])
  models.execute_kw(db, uid, pw,
      "property.details", "unlink",
      [models.execute_kw(db, uid, pw,
          "property.details", "search",
          [[["is_feed_sourced", "=", True]]])])
  models.execute_kw(db, uid, pw,
      "portal.connector", "write",
      [[bayut_id], {"inbound_feed_url": False}])
  ```

- Playwright's headless Chromium has been stable on this stack. If you
  need a real mouse cursor visible on the recording, run with
  `headless=False` (requires an X server or Xvfb).

## Why a real browser session?

Postman-style API tests can prove the controller endpoint returns 200
on a feed URL, but they don't show the user-facing surface:

- the Portal Connector form (the place an admin configures feeds),
- the cron admin page (where the hourly job shows up),
- the Properties list (filtered by `is_feed_sourced = True`),
- the "From Feed" ribbon that appears on imported property records,
- the Sync Logs page that shows the success entry.

All of that is captured in the recording.
