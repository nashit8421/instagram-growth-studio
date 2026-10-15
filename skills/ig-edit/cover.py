#!/usr/bin/env python3
"""
cover.py - grab a cover frame from a finished Reel, and the check frames that
show where the interface will sit on top of it.

The cover is a full 1080x1920 JPEG. Instagram shows it at 9:16 in the Reels
tab and crops it to the middle 3:4 (1080x1440) on the profile grid, so keep
the words in the middle of the frame.

Check frames are PNGs with the parts of the screen the app covers shaded
red: the top 230px, everything below y=1440 and the right 230px. If a caption
or the hook card touches the red, it will be hidden on a phone.

Usage
  python3 cover.py reel.mp4 --at 1.2 --out cover.jpg
  python3 cover.py reel.mp4 --check 0.5 5 9 --out-dir ./check
  python3 cover.py reel.mp4 --at 1.2 --out cover.jpg --json

Nothing is uploaded.
"""

import argparse
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

W, H = 1080, 1920
SAFE_TOP, SAFE_BOTTOM, SAFE_RIGHT = 230, 1440, 230   # from /ig-reel
GRID_TOP = (H - 1440) // 2                           # 3:4 grid crop, centred

RULE = "=" * 70


class CoverError(Exception):
    pass


def tool(name):
    """ffmpeg or ffprobe: $FFMPEG / $FFPROBE, then PATH, then Homebrew."""
    env = os.environ.get(name.upper())
    if env and Path(env).exists():
        return env
    found = shutil.which(name)
    if found:
        return found
    for base in ("/opt/homebrew/bin", "/usr/local/bin"):
        p = Path(base) / name
        if p.exists():
            return str(p)
    raise CoverError(f"{name} not found. Install it with: brew install ffmpeg")


def duration(path):
    out = subprocess.run([tool("ffprobe"), "-v", "error", "-show_entries",
                          "format=duration", "-of", "default=nw=1:nk=1", str(path)],
                         capture_output=True, text=True)
    try:
        return float(out.stdout.strip())
    except ValueError:
        raise CoverError(f"could not read {path}. Is it a video?")


def grab(video, at, out, overlay=False):
    """One frame at `at` seconds. JPEG or PNG by the extension of `out`."""
    out = Path(out)
    out.parent.mkdir(parents=True, exist_ok=True)
    vf = "scale=1080:1920:force_original_aspect_ratio=decrease,pad=1080:1920:(ow-iw)/2:(oh-ih)/2"
    if overlay:
        red = "red@0.35"
        vf += (f",drawbox=x=0:y=0:w=iw:h={SAFE_TOP}:color={red}:t=fill"
               f",drawbox=x=0:y={SAFE_BOTTOM}:w=iw:h=ih-{SAFE_BOTTOM}:color={red}:t=fill"
               f",drawbox=x=iw-{SAFE_RIGHT}:y={SAFE_TOP}:w={SAFE_RIGHT}:"
               f"h={SAFE_BOTTOM - SAFE_TOP}:color={red}:t=fill"
               f",drawbox=x=0:y={SAFE_TOP}:w=iw-{SAFE_RIGHT}:h={SAFE_BOTTOM - SAFE_TOP}"
               f":color=red:t=4")
    cmd = [tool("ffmpeg"), "-hide_banner", "-nostdin", "-loglevel", "error", "-y",
           "-ss", f"{at:.3f}", "-i", str(video), "-frames:v", "1", "-vf", vf]
    if out.suffix.lower() in (".jpg", ".jpeg"):
        cmd += ["-q:v", "2"]
    cmd.append(str(out))
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0 or not out.exists():
        raise CoverError(f"ffmpeg could not grab a frame at {at}s: {r.stderr.strip()[-300:]}")
    return out


def check_frames(video, times, out_dir):
    """Safe-zone check frames. Returns the list of PNG paths written."""
    total = duration(video)
    paths = []
    for t in times:
        t = max(0.0, min(float(t), max(0.0, total - 0.05)))
        paths.append(grab(video, t, Path(out_dir) / f"check-{t:05.2f}s.png", overlay=True))
    return paths


def make_cover(video, at, out):
    total = duration(video)
    warnings = []
    if at >= total:
        warnings.append(f"--at {at}s is past the end ({total:.2f}s). Used the last frame.")
        at = max(0.0, total - 0.05)
    path = grab(video, at, out)
    if at < 2.5:
        warnings.append("this frame is inside the hook card window, so the card is on the cover. "
                        "That is usually what you want.")
    return {"video": str(video), "at": round(at, 2), "cover": str(path),
            "size": f"{W}x{H}", "warnings": warnings}


def main(argv=None):
    ap = argparse.ArgumentParser(description="Grab a cover frame or safe-zone check frames from a Reel.")
    ap.add_argument("video")
    ap.add_argument("--at", type=float, default=None, help="seconds into the reel for the cover")
    ap.add_argument("--out", default=None, help="cover file, .jpg (default: <video>-cover.jpg)")
    ap.add_argument("--check", type=float, nargs="+", default=None,
                    help="times in seconds for safe-zone check frames")
    ap.add_argument("--out-dir", default=None, help="folder for check frames")
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args(argv)

    video = Path(a.video)
    if not video.exists():
        print(f"error: {video} not found", file=sys.stderr)
        return 2
    try:
        res = {"video": str(video), "warnings": []}
        if a.check:
            out_dir = Path(a.out_dir or video.with_name(video.stem + "-check"))
            res["check_frames"] = [str(p) for p in check_frames(video, a.check, out_dir)]
        if a.at is not None or not a.check:
            at = 1.0 if a.at is None else a.at
            out = a.out or str(video.with_name(video.stem + "-cover.jpg"))
            res.update(make_cover(video, at, out))
    except CoverError as e:
        print(f"error: {e}", file=sys.stderr)
        return 1

    if a.json:
        print(json.dumps(res, indent=2))
        return 0
    print(f"\nCOVER  ·  {video.name}")
    print(RULE)
    if "cover" in res:
        print(f"  cover      {res['cover']}  ({res['size']}, frame at {res['at']}s)")
        print("  grid       the profile grid shows the middle 1080x1440. Keep words there.")
    for p in res.get("check_frames", []):
        print(f"  check      {p}")
    if res.get("check_frames"):
        print("  red = covered by the app. Nothing that matters should touch it.")
    for w in res["warnings"]:
        print(f"  ! {w}")
    print("\n  Set the cover in the app: Edit cover > Add from camera roll.")
    print("  Nothing was uploaded.\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
