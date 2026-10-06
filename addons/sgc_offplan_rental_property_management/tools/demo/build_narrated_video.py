#!/usr/bin/env python3
"""Mux narration audio onto the recorded webm, segment by segment.

For each segment id, pads/trims its narration WAV to exactly match that
segment's ACTUAL on-screen duration (from segment_timings_<session>.json,
produced by record_demo_narrated.py), then concatenates all padded clips
in order and muxes the result onto the video. Segment N's video length is
always >= segment N's raw narration length (record_demo_narrated.py
enforces this while recording), so padding only ever adds trailing
silence — it never has to speed up or truncate speech.
"""
import argparse
import json
import subprocess
from pathlib import Path

HERE = Path(__file__).resolve().parent
VIDEOS_DIR = HERE / "videos"
AUDIO_DIR = HERE / "narration_audio"
PADDED_DIR = AUDIO_DIR / "padded"


def run(cmd):
    subprocess.run(cmd, check=True, capture_output=True, text=True)


def main():
    p = argparse.ArgumentParser()
    p.add_argument("session_id")
    args = p.parse_args()

    webm_path = VIDEOS_DIR / f"narrated-demo-{args.session_id}.webm"
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
        src = AUDIO_DIR / f"{seg_id}.wav"
        if not src.exists():
            print(f"WARNING: no narration for {seg_id}, using silence")
            out = PADDED_DIR / f"{seg_id}.wav"
            run(["ffmpeg", "-y", "-f", "lavfi", "-i", "anullsrc=r=24000:cl=mono",
                 "-t", str(target_dur), str(out)])
        else:
            out = PADDED_DIR / f"{seg_id}.wav"
            run(["ffmpeg", "-y", "-i", str(src), "-af", "apad",
                 "-t", str(target_dur), str(out)])
        print(f"  {seg_id}: padded to {target_dur:.1f}s -> {out.name}")
        lines.append(f"file '{out.resolve()}'")

    concat_list.write_text("\n".join(lines) + "\n")

    final_audio = AUDIO_DIR / f"final-narration-{args.session_id}.wav"
    run(["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", str(concat_list),
         "-c", "copy", str(final_audio)])
    print(f"Concatenated narration: {final_audio}")

    video_mp4 = VIDEOS_DIR / f"narrated-demo-{args.session_id}.mp4"
    run(["ffmpeg", "-y", "-i", str(webm_path),
         "-c:v", "libx264", "-preset", "medium", "-crf", "23",
         "-movflags", "+faststart", "-an", str(video_mp4)])
    print(f"Video (no audio): {video_mp4}")

    final_mp4 = VIDEOS_DIR / f"narrated-demo-{args.session_id}-final.mp4"
    run(["ffmpeg", "-y", "-i", str(video_mp4), "-i", str(final_audio),
         "-c:v", "copy", "-c:a", "aac", "-b:a", "128k",
         "-shortest", str(final_mp4)])
    print(f"FINAL: {final_mp4}")


if __name__ == "__main__":
    main()
