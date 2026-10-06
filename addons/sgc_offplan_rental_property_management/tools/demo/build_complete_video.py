#!/usr/bin/env python3
"""Mux narration onto the complete demo recording, segment by segment.

Same approach as build_narrated_video.py, with two fixes found while
diagnosing the previous "broken" video:

1. The final mux step was missing `-movflags +faststart`, so the moov
   atom landed at the END of the file instead of the beginning. That's
   valid MP4, but many players (including inline web previews) refuse to
   start playback, or show a black/broken screen, until they've read the
   whole file. Faststart is now applied on every write, not just the
   intermediate video-only pass.
2. Narration clips are MP3 (Deepgram), not WAV (Kokoro/KittenTTS) — the
   padding/concat commands are format-agnostic either way, but paths are
   updated accordingly.
"""
import argparse
import json
import subprocess
from pathlib import Path

HERE = Path(__file__).resolve().parent
VIDEOS_DIR = HERE / "videos"
AUDIO_DIR = HERE / "narration_audio_v2"
PADDED_DIR = AUDIO_DIR / "padded"


def run(cmd):
    subprocess.run(cmd, check=True, capture_output=True, text=True)


def main():
    p = argparse.ArgumentParser()
    p.add_argument("session_id")
    args = p.parse_args()

    webm_path = VIDEOS_DIR / f"complete-demo-{args.session_id}.webm"
    timings_path = HERE / f"segment_timings_{args.session_id}.json"
    if not webm_path.exists():
        raise SystemExit(f"missing video: {webm_path}")
    if not timings_path.exists():
        raise SystemExit(f"missing timings: {timings_path}")

    timings = {t["id"]: t["duration_s"] for t in json.loads(timings_path.read_text())}
    PADDED_DIR.mkdir(parents=True, exist_ok=True)

    concat_list = PADDED_DIR / "concat.txt"
    lines = []
    for seg_id, target_dur in timings.items():
        src = AUDIO_DIR / f"{seg_id}.mp3"
        out = PADDED_DIR / f"{seg_id}.wav"
        if not src.exists():
            print(f"WARNING: no narration for {seg_id}, using silence")
            run(["ffmpeg", "-y", "-f", "lavfi", "-i", "anullsrc=r=24000:cl=mono",
                 "-t", str(target_dur), str(out)])
        else:
            run(["ffmpeg", "-y", "-i", str(src), "-af", "apad",
                 "-t", str(target_dur), "-ar", "24000", "-ac", "1", str(out)])
        print(f"  {seg_id}: padded to {target_dur:.1f}s -> {out.name}")
        lines.append(f"file '{out.resolve()}'")

    concat_list.write_text("\n".join(lines) + "\n")

    final_audio = AUDIO_DIR / f"final-narration-{args.session_id}.wav"
    run(["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", str(concat_list),
         "-c", "copy", str(final_audio)])
    print(f"Concatenated narration: {final_audio}")

    video_mp4 = VIDEOS_DIR / f"complete-demo-{args.session_id}.mp4"
    run(["ffmpeg", "-y", "-i", str(webm_path),
         "-c:v", "libx264", "-preset", "medium", "-crf", "23",
         "-movflags", "+faststart", "-an", str(video_mp4)])
    print(f"Video (no audio): {video_mp4}")

    final_mp4 = VIDEOS_DIR / f"complete-demo-{args.session_id}-final.mp4"
    run(["ffmpeg", "-y", "-i", str(video_mp4), "-i", str(final_audio),
         "-c:v", "copy", "-c:a", "aac", "-b:a", "160k",
         "-movflags", "+faststart",
         "-shortest", str(final_mp4)])
    print(f"FINAL: {final_mp4}")


if __name__ == "__main__":
    main()
