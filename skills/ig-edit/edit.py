#!/usr/bin/env python3
"""
edit.py - turn a raw recording into a Reel, locally, with ffmpeg.

Cuts the silences, crops to 9:16, burns in captions inside the Reel safe
zone, puts the hook card up from frame 1 and writes an Instagram-safe MP4:
1080x1920, H.264 high profile, yuv420p, 30 fps, AAC, faststart.

Cut on the sentence, not on the breath. A pause is only cut when it is
quieter than --silence-db for at least --min-silence seconds, so a breath
between two words stays in. Each kept stretch keeps --pad seconds either side
so the first and last syllables are not clipped.

Captions come from, in this order:
  1. --srt FILE           your own subtitles, timed against the input file
  2. a local Whisper      whisper.cpp (whisper-cli), mlx_whisper, faster_whisper
                          or the openai-whisper CLI, if one is installed
  3. --script FILE        the script lines spread over the speech. Approximate.
Nothing is installed or downloaded by this script. The only network use is
whatever your own Whisper install does when it loads a model.

Usage
  python3 edit.py raw.mov --out reel.mp4 --cut-silence --script script.txt \\
      --hook-text "5 HOURS -> 20 MIN"
  python3 edit.py long.mp4 --out clip.mp4 --start 00:14:20 --end 00:14:58 --cut-silence
  python3 edit.py raw.mov --out reel.mp4 --dry-run
  python3 edit.py raw.mov --out reel.mp4 --cover-at 1.2 --json

Writes next to --out: reel.mp4, reel.srt, reel.ass, edit-report.json and a
check/ folder of safe-zone frames. Nothing is uploaded. Nothing is posted.
"""

import argparse
import importlib.util
import json
import math
import os
import re
import shlex
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import cover  # noqa: E402

W, H, FPS = 1080, 1920, 30
SAFE_TOP, SAFE_BOTTOM, SAFE_RIGHT = 230, 1440, 230   # /ig-reel safe zone
SIDE = 60                                            # left gutter for text
HOOK_SECONDS = 2.5
MAX_CARD_WORDS = 6
DEAD_AIR = 0.5           # first word later than this and the hook is late
MIN_REEL = 7.0           # under this the loop counts inflate and nothing else
LONG_REEL = 90.0
MIN_SPEECH = 0.08        # a "speech" run shorter than this is a click
MERGE_GAP = 0.20         # cutting less than this is a jump cut for nothing
VIDEO_BITRATE, VIDEO_MAX, VIDEO_BUF = "9M", "10M", "18M"
AUDIO_BITRATE = "160k"
WIDE = 2.0               # --crop auto fits anything wider than 2:1 on blur

RULE = "=" * 70
THIN = "-" * 70

WHISPER_HINT = ("no local Whisper found. For word-timed captions: brew install whisper-cpp, "
                "then put a model in {models}, e.g. curl -L -o {models}/ggml-base.en.bin "
                "https://huggingface.co/ggerganov/whisper.cpp/resolve/main/ggml-base.en.bin")


class EditError(Exception):
    pass


# ---------------------------------------------------------------- data dir

def data_dir():
    """$IG_DATA_DIR, else the active account's folder, else $IG_HOME."""
    if os.environ.get("IG_DATA_DIR"):
        return Path(os.environ["IG_DATA_DIR"]).expanduser()
    home = Path(os.environ.get("IG_HOME") or "~/IGStudio").expanduser()
    marker = home / "active-account"
    try:
        handle = marker.read_text().strip().lstrip("@")
    except OSError:
        handle = ""
    if handle and "/" not in handle and (home / "accounts" / handle).is_dir():
        return home / "accounts" / handle
    return home


# ---------------------------------------------------------------- time

def parse_time(value):
    """'HH:MM:SS.ms', 'MM:SS' or plain seconds -> float seconds."""
    if value is None:
        return None
    s = str(value).strip()
    try:
        parts = [float(p) for p in s.split(":")]
    except ValueError:
        raise EditError(f"cannot read time {value!r}. Use HH:MM:SS, MM:SS or seconds.")
    if len(parts) > 3 or any(p < 0 for p in parts):
        raise EditError(f"cannot read time {value!r}. Use HH:MM:SS, MM:SS or seconds.")
    total = 0.0
    for p in parts:
        total = total * 60 + p
    return total


def tc(seconds):
    m, s = divmod(max(0.0, seconds), 60)
    return f"{int(m)}:{s:04.1f}"


def srt_time(t):
    ms = int(round(max(0.0, t) * 1000))
    h, ms = divmod(ms, 3600000)
    m, ms = divmod(ms, 60000)
    s, ms = divmod(ms, 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def ass_time(t):
    cs = int(round(max(0.0, t) * 100))
    h, cs = divmod(cs, 360000)
    m, cs = divmod(cs, 6000)
    s, cs = divmod(cs, 100)
    return f"{h}:{m:02d}:{s:02d}.{cs:02d}"


# ---------------------------------------------------------------- probe

def run(cmd, **kw):
    return subprocess.run(cmd, capture_output=True, text=True, **kw)


def rate(value):
    try:
        num, den = str(value).split("/")
        return float(num) / float(den) if float(den) else 0.0
    except (ValueError, ZeroDivisionError):
        try:
            return float(value)
        except (TypeError, ValueError):
            return 0.0


def parse_probe(info):
    """ffprobe JSON -> the few facts the edit needs. Width and height are as
    displayed, so a phone clip with 90 degree rotation metadata is portrait."""
    streams = info.get("streams", [])
    video = next((s for s in streams if s.get("codec_type") == "video"
                  and not s.get("disposition", {}).get("attached_pic")), None)
    if video is None:
        raise EditError("no video stream in this file")
    rotation = 0
    for sd in video.get("side_data_list", []) or []:
        if "rotation" in sd:
            rotation = int(round(float(sd["rotation"])))
    if not rotation and video.get("tags", {}).get("rotate"):
        rotation = int(video["tags"]["rotate"])
    w, h = int(video.get("width", 0)), int(video.get("height", 0))
    if abs(rotation) % 180 == 90:
        w, h = h, w
    dur = info.get("format", {}).get("duration") or video.get("duration") or 0
    fps = rate(video.get("avg_frame_rate")) or rate(video.get("r_frame_rate"))
    return {
        "duration": round(float(dur), 3),
        "width": w,
        "height": h,
        "rotation": rotation,
        "fps": round(fps, 3),
        "has_audio": any(s.get("codec_type") == "audio" for s in streams),
        "video_codec": video.get("codec_name"),
    }


def probe(path):
    r = run([cover.tool("ffprobe"), "-v", "error", "-print_format", "json",
             "-show_streams", "-show_format", str(path)])
    if r.returncode != 0:
        raise EditError(f"ffprobe could not read {path}: {r.stderr.strip()[-300:]}")
    return parse_probe(json.loads(r.stdout or "{}"))


def orientation(w, h):
    if w > h * 1.05:
        return "landscape"
    if h > w * 1.05:
        return "portrait"
    return "square"


# ---------------------------------------------------------------- silence

SIL_START = re.compile(r"silence_start:\s*(-?[\d.]+)")
SIL_END = re.compile(r"silence_end:\s*(-?[\d.]+)")


def window_args(start, length, full):
    args = []
    if start > 0:
        args += ["-ss", f"{start:.3f}"]
    if not full:
        args += ["-t", f"{length:.3f}"]
    return args


def parse_silences(stderr, dur):
    out, open_at = [], None
    for line in stderr.splitlines():
        m = SIL_START.search(line)
        if m:
            open_at = max(0.0, float(m.group(1)))
        m = SIL_END.search(line)
        if m and open_at is not None:
            out.append((open_at, min(dur, float(m.group(1)))))
            open_at = None
    if open_at is not None:
        out.append((open_at, dur))
    return out


def detect_silences(path, start, length, full, db, min_silence):
    cmd = [cover.tool("ffmpeg"), "-hide_banner", "-nostdin", *window_args(start, length, full),
           "-i", str(path), "-vn", "-af", f"silencedetect=noise={db}dB:d={min_silence}",
           "-f", "null", "-"]
    r = run(cmd)
    if r.returncode != 0:
        raise EditError(f"silence detection failed: {r.stderr.strip()[-300:]}")
    return parse_silences(r.stderr, length), cmd


def speech_runs(silences, dur):
    runs, t = [], 0.0
    for a, b in sorted(silences):
        if a > t:
            runs.append((t, a))
        t = max(t, b)
    if t < dur:
        runs.append((t, dur))
    return [(round(a, 3), round(b, 3)) for a, b in runs if b - a >= MIN_SPEECH]


def keep_segments(runs, dur, pad, merge_gap=MERGE_GAP):
    """Pad each speech run and merge the ones that nearly touch."""
    merged = []
    for a, b in runs:
        a, b = max(0.0, a - pad), min(dur, b + pad)
        if merged and a - merged[-1][1] < merge_gap:
            merged[-1] = (merged[-1][0], max(b, merged[-1][1]))
        else:
            merged.append((a, b))
    return [(round(a, 3), round(b, 3)) for a, b in merged]


def snap(segs, fps):
    """Put cut points on the source frame grid so sound and picture cut on
    the same frame and do not drift apart across many cuts."""
    if not fps:
        return segs
    out = []
    for a, b in segs:
        a2, b2 = math.floor(a * fps) / fps, math.ceil(b * fps) / fps
        out.append((round(a2, 4), round(b2, 4)))
    return out


def cap_segments(segs, max_len, runs, pad):
    """Fit under max_len, cutting at the end of a sentence where there is one."""
    out, total = [], 0.0
    for a, b in segs:
        if total + (b - a) <= max_len + 1e-6:
            out.append((a, b))
            total += b - a
            continue
        room = max_len - total
        if out and total >= 0.6 * max_len:
            return out, "dropped the tail at a pause to stay under the limit"
        ends = [e + pad for s, e in runs if a < e + pad <= a + room and e > a]
        if ends:
            out.append((a, round(max(ends), 3)))
            return out, "cut at the last pause before the limit"
        out.append((a, round(a + room, 3)))
        return out, "hard cut at the limit, probably mid-sentence"
    return out, None


class Timeline:
    """Maps a time in the (windowed) input to a time in the output."""

    def __init__(self, segs):
        self.segs = segs
        self.offsets, t = [], 0.0
        for a, b in segs:
            self.offsets.append(t)
            t += b - a
        self.duration = round(t, 3)

    def map(self, t, side="start"):
        for (a, b), off in zip(self.segs, self.offsets):
            if a <= t <= b:
                return off + t - a
            if t < a:   # inside a cut: a start moves forward, an end moves back
                return off if side == "start" else max(0.0, off)
        return self.duration

    def interval(self, s, e, min_len=0.05):
        a, b = self.map(s, "start"), self.map(e, "end")
        return (round(a, 3), round(b, 3)) if b - a >= min_len else None


# ---------------------------------------------------------------- captions

def split_words(text, n=MAX_CARD_WORDS):
    """Cards of n words or fewer, about even, breaking after a comma or a
    full stop when there is one close to the even split."""
    words = text.split()
    cards = []
    while len(words) > n:
        size = math.ceil(len(words) / math.ceil(len(words) / n))
        cut = size
        for j in range(min(n, size + 1), max(1, size - 2), -1):
            if re.search(r"[,;:.!?\u0964\u06d4\u061f]$", words[j - 1]) and len(words) - j >= 2:
                cut = j
                break
        cards.append(" ".join(words[:cut]))
        words = words[cut:]
    if words:
        cards.append(" ".join(words))
    return cards


def spread(text, start, end):
    """One cue of any length -> cards of six words or fewer over its span."""
    chunks = split_words(text)
    total = sum(len(c.split()) for c in chunks) or 1
    cards, t = [], start
    for c in chunks:
        d = (end - start) * len(c.split()) / total
        cards.append({"start": round(t, 3), "end": round(t + d, 3), "text": c})
        t += d
    return cards


def tidy(cards, out_dur):
    cards = sorted([c for c in cards if c["text"].strip()], key=lambda c: c["start"])
    for i, c in enumerate(cards):
        c["end"] = min(c["end"], out_dur)
        if i + 1 < len(cards):
            c["end"] = min(c["end"], cards[i + 1]["start"])
    return [c for c in cards if c["end"] - c["start"] >= 0.1]


def parse_srt(text):
    cues = []
    for block in re.split(r"\n\s*\n", text.replace("\r", "").strip()):
        lines = block.strip().split("\n")
        for i, line in enumerate(lines):
            m = re.match(r"\s*(\d+):(\d+):(\d+)[,.](\d+)\s*-->\s*(\d+):(\d+):(\d+)[,.](\d+)", line)
            if m:
                g = [int(x) for x in m.groups()]
                s = g[0] * 3600 + g[1] * 60 + g[2] + g[3] / 10 ** len(m.group(4))
                e = g[4] * 3600 + g[5] * 60 + g[6] + g[7] / 10 ** len(m.group(8))
                body = " ".join(re.sub(r"<[^>]+>|\{[^}]*\}", "", l).strip() for l in lines[i + 1:])
                if body.strip():
                    cues.append({"start": s, "end": e, "text": body.strip()})
                break
    return cues


def cards_from_cues(cues, tl, offset=0.0):
    """Cues timed on the input file -> cards on the output timeline."""
    cards = []
    for c in cues:
        span = tl.interval(c["start"] - offset, c["end"] - offset)
        if span:
            cards += spread(c["text"], *span)
    return tidy(cards, tl.duration)


def cards_from_words(words, tl):
    """Word timings from Whisper -> cards of six words or fewer. A card also
    breaks at the end of a sentence and wherever the cut removed a pause."""
    mapped = []
    for w in words:
        span = tl.interval(w["start"], w["end"], min_len=0.0)
        if span and w["word"].strip():
            mapped.append({"start": span[0], "end": span[1], "word": w["word"].strip()})
    cards, cur = [], []
    for w in mapped:
        if cur and (len(cur) >= MAX_CARD_WORDS or w["start"] - cur[-1]["end"] > 0.6
                    or re.search(r"[.!?।۔؟]$", cur[-1]["word"])):
            cards.append(cur)
            cur = []
        cur.append(w)
    if cur:
        cards.append(cur)
    out = [{"start": c[0]["start"], "end": c[-1]["end"] + 0.15,
            "text": " ".join(w["word"] for w in c)} for c in cards]
    return tidy(out, tl.duration)


def cards_from_script(lines, speech, out_dur):
    """Script lines spread over the speech in the output. If the number of
    lines matches the number of speech runs, line N goes on run N. Otherwise
    the words are spread over the speech time in proportion. Either way it is
    an estimate, and the report says so."""
    lines = [l.strip() for l in lines if l.strip()]
    if not lines:
        return [], "empty script"
    speech = [s for s in speech if s[1] - s[0] > 0.05] or [(0.0, out_dur)]
    if len(lines) == len(speech):
        cards = []
        for line, (a, b) in zip(lines, speech):
            cards += spread(line, a, b)
        return tidy(cards, out_dur), f"{len(lines)} lines matched to {len(speech)} speech runs"
    total_words = sum(len(l.split()) for l in lines)
    talk = sum(b - a for a, b in speech)

    def clock_to_out(x):
        for a, b in speech:
            if x <= b - a + 1e-9:
                return a + x
            x -= b - a
        return speech[-1][1]

    cards, pos = [], 0.0
    for line in lines:
        d = talk * len(line.split()) / total_words
        a, b = clock_to_out(pos), clock_to_out(pos + d - 1e-6)
        cards += spread(line, a, max(b, a + 0.3))
        pos += d
    return (tidy(cards, out_dur),
            f"{len(lines)} lines spread over {len(speech)} speech runs by word count")


def write_srt(cards, path):
    blocks = [f"{i}\n{srt_time(c['start'])} --> {srt_time(c['end'])}\n{c['text']}\n"
              for i, c in enumerate(cards, 1)]
    Path(path).write_text("\n".join(blocks), encoding="utf-8")


def ass_text(text):
    text = text.replace("->", "→").replace("\\", "/").replace("{", "(").replace("}", ")")
    return text.replace("\n", "\\N")


def ass_document(cards, hook, hook_end, font="Helvetica Neue"):
    margin_r = SAFE_RIGHT + SIDE
    cap_v = H - SAFE_BOTTOM + 60            # bottom of caption text at y=1380
    hook_v = 420                            # top of the hook card
    head = f"""[Script Info]
ScriptType: v4.00+
PlayResX: {W}
PlayResY: {H}
WrapStyle: 0
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Caption,{font},74,&H00FFFFFF,&H00FFFFFF,&H00101010,&H80000000,-1,0,0,0,100,100,2,0,1,5,2,2,{SIDE},{margin_r},{cap_v},1
Style: Hook,{font},92,&H00FFFFFF,&H00FFFFFF,&H00101010,&H90000000,-1,0,0,0,100,100,0,0,3,22,0,8,{SIDE},{margin_r},{hook_v},1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
    ev = []
    if hook:
        ev.append(f"Dialogue: 1,{ass_time(0)},{ass_time(hook_end)},Hook,,0,0,0,,{ass_text(hook)}")
    for c in cards:
        ev.append(f"Dialogue: 0,{ass_time(c['start'])},{ass_time(c['end'])},Caption,,0,0,0,,"
                  f"{ass_text(c['text'])}")
    return head + "\n".join(ev) + "\n"


# ---------------------------------------------------------------- whisper

MODEL_GLOBS = ("ggml-*.bin",)


def model_dirs():
    dirs = []
    if os.environ.get("WHISPER_MODEL_DIR"):
        dirs.append(Path(os.environ["WHISPER_MODEL_DIR"]).expanduser())
    dirs += [data_dir() / "models", Path.home() / ".cache" / "whisper.cpp",
             Path.home() / ".cache" / "whisper", Path.home() / "models",
             Path("/opt/homebrew/share/whisper-cpp/models"),
             Path("/opt/homebrew/share/whisper-cpp"), Path("/usr/local/share/whisper-cpp")]
    return dirs


def find_ggml_model():
    env = os.environ.get("WHISPER_MODEL")
    if env and Path(env).expanduser().is_file():
        return str(Path(env).expanduser())
    prefer = ("small", "base", "medium", "large", "tiny")
    found = []
    for d in model_dirs():
        if d.is_dir():
            for g in MODEL_GLOBS:
                found += sorted(d.glob(g))
    for p in prefer:
        for f in found:
            if p in f.name and f.stat().st_size > 1_000_000:
                return str(f)
    return str(found[0]) if found else None


def find_transcriber():
    """The first usable local Whisper, or None. Never installs anything."""
    for name in ("whisper-cli", "whisper-cpp"):
        exe = shutil.which(name)
        if exe:
            model = find_ggml_model()
            if model:
                return {"kind": "whisper.cpp", "exe": exe, "model": model}
    if importlib.util.find_spec("mlx_whisper"):
        return {"kind": "mlx_whisper"}
    if importlib.util.find_spec("faster_whisper"):
        return {"kind": "faster_whisper"}
    exe = shutil.which("whisper")
    if exe:
        return {"kind": "openai-whisper", "exe": exe}
    return None


def whisper_cpp_without_model():
    return bool(shutil.which("whisper-cli") or shutil.which("whisper-cpp")) and not find_ggml_model()


PY_WORDS = {
    "mlx_whisper": """
import json, sys, mlx_whisper
kw = {"word_timestamps": True}
if sys.argv[2] != "auto": kw["language"] = sys.argv[2]
r = mlx_whisper.transcribe(sys.argv[1], **kw)
print(json.dumps([{"word": w["word"], "start": w["start"], "end": w["end"]}
                  for s in r["segments"] for w in s.get("words", [])]))
""",
    "faster_whisper": """
import json, sys
from faster_whisper import WhisperModel
m = WhisperModel("base", device="auto", compute_type="int8")
segs, _ = m.transcribe(sys.argv[1], word_timestamps=True,
                       language=None if sys.argv[2] == "auto" else sys.argv[2])
print(json.dumps([{"word": w.word, "start": w.start, "end": w.end}
                  for s in segs for w in (s.words or [])]))
""",
}


def transcribe(t, wav, lang, workdir):
    """Word timings [{word, start, end}] relative to the start of `wav`."""
    if t["kind"] == "whisper.cpp":
        base = Path(workdir) / "whisper"
        language = "en" if ".en." in Path(t["model"]).name else lang
        r = run([t["exe"], "-m", t["model"], "-f", str(wav), "-l", language,
                 "-ml", "1", "-sow", "-osrt", "-of", str(base), "-np"])
        srt = base.with_suffix(".srt")
        if r.returncode != 0 or not srt.exists():
            raise EditError(f"whisper.cpp failed: {r.stderr.strip()[-300:]}")
        return [{"word": c["text"], "start": c["start"], "end": c["end"]}
                for c in parse_srt(srt.read_text(encoding="utf-8", errors="replace"))]
    if t["kind"] in PY_WORDS:
        r = run([sys.executable, "-c", PY_WORDS[t["kind"]], str(wav), lang])
        if r.returncode != 0:
            raise EditError(f"{t['kind']} failed: {r.stderr.strip()[-300:]}")
        return json.loads(r.stdout.strip().splitlines()[-1])
    if t["kind"] == "openai-whisper":
        cmd = [t["exe"], str(wav), "--model", "base", "--word_timestamps", "True",
               "--output_format", "json", "--output_dir", str(workdir), "--fp16", "False"]
        if lang != "auto":
            cmd += ["--language", lang]
        r = run(cmd)
        js = Path(workdir) / (Path(wav).stem + ".json")
        if r.returncode != 0 or not js.exists():
            raise EditError(f"whisper failed: {r.stderr.strip()[-300:]}")
        data = json.loads(js.read_text())
        return [{"word": w["word"], "start": w["start"], "end": w["end"]}
                for s in data.get("segments", []) for w in s.get("words", [])]
    raise EditError(f"unknown transcriber {t['kind']}")


# ---------------------------------------------------------------- ffmpeg plan

def framing(mode, w, h):
    """The video filter that turns the cut into 1080x1920, and its name."""
    fill = f"scale={W}:{H}:force_original_aspect_ratio=increase:flags=lanczos,crop={W}:{H}"
    if mode == "auto":
        mode = "none" if w > h * WIDE else "center"
    if mode == "center":
        return fill + ",setsar=1", "centre crop"
    bg = (f"split=2[bg][fg];[bg]scale=270:480:force_original_aspect_ratio=increase,crop=270:480,"
          f"boxblur=12:3,scale={W}:{H},eq=brightness=-0.10[bgb];"
          f"[fg]scale={W}:{H}:force_original_aspect_ratio=decrease:flags=lanczos[fgs];"
          f"[bgb][fgs]overlay=(W-w)/2:(H-h)/2,setsar=1")
    return bg, "fit on blurred background"


def build_command(src, out, start, length, full, segs, has_audio, frame_filter,
                  ass_name, preset):
    parts, labels = [], []
    for i, (a, b) in enumerate(segs):
        parts.append(f"[0:v]trim=start={a:.4f}:end={b:.4f},setpts=PTS-STARTPTS[v{i}]")
        if has_audio:
            parts.append(f"[0:a]atrim=start={a:.4f}:end={b:.4f},asetpts=PTS-STARTPTS[a{i}]")
            labels.append(f"[v{i}][a{i}]")
        else:
            labels.append(f"[v{i}]")
    n = len(segs)
    if has_audio:
        parts.append(f"{''.join(labels)}concat=n={n}:v=1:a=1[vc][ac]")
        parts.append("[ac]aresample=48000,aformat=sample_rates=48000:channel_layouts=stereo[aout]")
    else:
        parts.append(f"{''.join(labels)}concat=n={n}:v=1:a=0[vc]")
        total = sum(b - a for a, b in segs)
        parts.append(f"anullsrc=r=48000:cl=stereo,atrim=duration={total:.4f}[aout]")
    chain = f"[vc]fps={FPS},{frame_filter}"
    if ass_name:
        chain += f",ass={ass_name}"
    parts.append(chain + ",format=yuv420p[vout]")
    return [cover.tool("ffmpeg"), "-hide_banner", "-nostdin", "-loglevel", "error", "-y",
            *window_args(start, length, full), "-i", str(src),
            "-filter_complex", ";".join(parts),
            "-map", "[vout]", "-map", "[aout]",
            "-c:v", "libx264", "-preset", preset, "-profile:v", "high", "-level:v", "4.1",
            "-pix_fmt", "yuv420p", "-r", str(FPS), "-g", str(FPS * 2),
            "-b:v", VIDEO_BITRATE, "-maxrate", VIDEO_MAX, "-bufsize", VIDEO_BUF,
            "-c:a", "aac", "-b:a", AUDIO_BITRATE, "-ar", "48000", "-ac", "2",
            "-movflags", "+faststart", str(out)]


# ---------------------------------------------------------------- the edit

def edit(a):
    src = Path(a.input).expanduser()
    if not src.exists():
        raise EditError(f"{src} not found")
    out = Path(a.out).expanduser().resolve()
    if out.suffix.lower() != ".mp4":
        raise EditError("--out must end in .mp4")
    info = probe(src)
    warnings, notes = [], []

    # Window: the whole file, or --start/--end for a clip out of a long video.
    start = parse_time(a.start) or 0.0
    end = parse_time(a.end)
    if start >= info["duration"]:
        raise EditError(f"--start {tc(start)} is past the end of the video ({tc(info['duration'])})")
    if end is None or end > info["duration"]:
        if end is not None:
            warnings.append(f"--end {tc(end)} is past the end of the video. Used {tc(info['duration'])}.")
        end = info["duration"]
    if end <= start:
        raise EditError("--end must be after --start")
    length = round(end - start, 3)
    full = start == 0 and end >= info["duration"]

    # Silence and speech.
    silences, runs, sil_cmd = [], [(0.0, length)], None
    if info["has_audio"]:
        silences, sil_cmd = detect_silences(src, start, length, full, a.silence_db, a.min_silence)
        runs = speech_runs(silences, length)
    elif a.cut_silence:
        warnings.append("no audio track, so there is nothing to cut on. Nothing was cut.")
    no_speech = info["has_audio"] and not runs
    if no_speech:
        warnings.append(f"no sound above {a.silence_db} dB anywhere. Check the mic, "
                        "or lower --silence-db.")
        runs = [(0.0, length)]

    if a.cut_silence and info["has_audio"] and not no_speech:
        segs = keep_segments(runs, length, a.pad)
    else:
        segs = [(0.0, length)]
    segs = snap(segs, info["fps"])
    segs = [(max(0.0, x), min(length, y)) for x, y in segs]
    segs, capped = cap_segments(segs, a.max_length, runs, a.pad)
    if capped:
        warnings.append(f"longer than --max-length {a.max_length:g}s: {capped}.")
    tl = Timeline(segs)
    out_dur = tl.duration
    cut_seconds = round(length - out_dur, 2)
    gaps = sum(1 for (x0, y0), (x1, y1) in zip(segs, segs[1:]) if x1 - y0 > 0.01)
    cuts = gaps + (1 if segs[0][0] > 0.01 else 0) + (1 if length - segs[-1][1] > 0.01 else 0)

    speech_out = [s for s in (tl.interval(x, y) for x, y in runs) if s]
    first_word = speech_out[0][0] if speech_out and info["has_audio"] and not no_speech else None

    # Captions.
    cards, cap_source, cap_detail = [], "none", ""
    transcriber = None if a.no_transcribe else find_transcriber()
    workdir = Path(tempfile.mkdtemp(prefix="ig-edit-"))
    try:
        if a.captions != "none":
            if a.srt:
                cues = parse_srt(Path(a.srt).expanduser().read_text(encoding="utf-8", errors="replace"))
                cards = cards_from_cues(cues, tl, offset=start)
                cap_source, cap_detail = "srt", f"{Path(a.srt).name}, {len(cues)} cues"
                if not cards:
                    warnings.append("the SRT has no cues inside the kept footage. Times are read "
                                    "against the input file, not the output.")
            elif transcriber and info["has_audio"] and not no_speech:
                cap_source = transcriber["kind"]
                if a.dry_run:
                    cap_detail = "would transcribe locally with word timing"
                else:
                    wav = workdir / "speech.wav"
                    r = run([cover.tool("ffmpeg"), "-hide_banner", "-nostdin", "-loglevel", "error",
                             "-y", *window_args(start, length, full), "-i", str(src), "-vn",
                             "-ac", "1", "-ar", "16000", "-c:a", "pcm_s16le", str(wav)])
                    if r.returncode != 0:
                        raise EditError(f"could not extract audio: {r.stderr.strip()[-300:]}")
                    words = transcribe(transcriber, wav, a.lang, workdir)
                    cards = cards_from_words(words, tl)
                    cap_detail = f"transcribed locally, {len(words)} words"
                    if not words:
                        warnings.append("Whisper heard no words. No captions.")
            elif a.script:
                lines = Path(a.script).expanduser().read_text(encoding="utf-8").splitlines()
                cards, how = cards_from_script(lines, speech_out, out_dur)
                cap_source = "script"
                cap_detail = f"approximate: {how}"
                warnings.append("captions are timed from the script, not from what you said. "
                                "Watch them through. Fix with --srt, or install Whisper.")
            if not transcriber and not a.srt and not a.no_transcribe:
                models = data_dir() / "models"
                hint = (f"whisper.cpp is installed but has no model. Put one in {models}"
                        if whisper_cpp_without_model() else WHISPER_HINT.format(models=models))
                notes.append(hint)
            if cap_source == "none":
                warnings.append("no captions. Most people watch muted first. Pass --script or --srt.")

        hook = (a.hook_text or "").strip()
        hook_end = min(HOOK_SECONDS, out_dur)
        if hook and len(hook.replace("->", " ").split()) > MAX_CARD_WORDS:
            warnings.append(f"hook card is {len(hook.split())} words. Six or fewer reads at a glance.")
        if any(len(c["text"].split()) > MAX_CARD_WORDS for c in cards):
            warnings.append("a caption card is over six words.")

        # Warnings that are about the Reel, not the tool.
        if out_dur > LONG_REEL:
            warnings.append(f"output is {out_dur:.1f}s, over 90s. 15 to 45s is the working range.")
        if out_dur < MIN_REEL:
            warnings.append(f"output is {out_dur:.1f}s, under 7s. The loop counts inflate and "
                            "nothing else does.")
        if first_word is not None and first_word > DEAD_AIR:
            warnings.append(f"dead air before hook: the first word starts at {first_word:.2f}s. "
                            "Use --cut-silence, or start the clip later.")
        frame_filter, crop_name = framing(a.crop, info["width"], info["height"])
        orient = orientation(info["width"], info["height"])
        if orient == "landscape" and crop_name == "centre crop":
            kept = (info["height"] * 9 / 16) / info["width"]
            notes.append(f"landscape source: the centre crop keeps the middle {kept:.0%} of the width. "
                         "If you were not in the middle, use --crop none.")
        scale_w = min(info["width"], info["height"] * 9 / 16) if crop_name == "centre crop" else info["width"]
        if scale_w < W * 0.66:
            warnings.append(f"source is {info['width']}x{info['height']}. After the crop it is being "
                            "blown up a lot and will look soft.")

        burn = a.captions == "burn" and bool(cards)
        ass_name = "captions.ass" if (burn or hook) else None
        cmd = build_command(src.resolve(), out, start, length, full, segs, info["has_audio"],
                            frame_filter, ass_name, a.preset)
        srt_path = out.with_suffix(".srt")
        ass_path = out.with_suffix(".ass")
        report_path = out.parent / "edit-report.json"
        files = [str(out)]

        report = {
            "input": str(src),
            "output": str(out),
            "probe": info,
            "window": {"start": round(start, 3), "end": round(end, 3), "length": length},
            "output_duration": out_dur,
            "seconds_cut": cut_seconds,
            "cuts": cuts,
            "segments": [[round(x + start, 3), round(y + start, 3)] for x, y in segs],
            "silence": {"enabled": bool(a.cut_silence), "db": a.silence_db,
                        "min_silence": a.min_silence, "pad": a.pad,
                        "silences_found": len(silences)},
            "first_word_at": None if first_word is None else round(first_word, 2),
            "crop": crop_name,
            "hook_card": {"text": hook, "start": 0.0, "end": round(hook_end, 2)} if hook else None,
            "captions": {"mode": a.captions, "source": cap_source, "detail": cap_detail,
                         "cards": len(cards), "burned": burn},
            "warnings": warnings,
            "notes": notes,
            "dry_run": bool(a.dry_run),
            "commands": [shlex.join(cmd)] + ([shlex.join(sil_cmd)] if sil_cmd else []),
            "run_from": "(a temp folder holding captions.ass)" if ass_name else None,
            "files": files,
        }
        if a.dry_run:
            report["caption_cards"] = cards
            return report

        out.parent.mkdir(parents=True, exist_ok=True)
        if ass_name:
            doc = ass_document(cards if burn else [], hook, hook_end)
            (workdir / ass_name).write_text(doc, encoding="utf-8")
            ass_path.write_text(doc, encoding="utf-8")
            files.append(str(ass_path))
        if cards and a.captions in ("burn", "srt"):
            write_srt(cards, srt_path)
            files.append(str(srt_path))
        r = run(cmd, cwd=workdir)
        if r.returncode != 0 or not out.exists():
            raise EditError(f"ffmpeg failed: {r.stderr.strip()[-800:]}")
        final = probe(out)
        report["output_probe"] = final
        report["output_duration"] = final["duration"]

        if not a.no_check_frames:
            times = sorted({0.5, round(min(5.0, final["duration"] * 0.5), 2),
                            round(final["duration"] * 0.8, 2)})
            frames = cover.check_frames(out, times, out.parent / "check")
            report["check_frames"] = [str(p) for p in frames]
            files += report["check_frames"]
        if a.cover_at is not None:
            c = cover.make_cover(out, a.cover_at, out.with_name(out.stem + "-cover.jpg"))
            report["cover"] = c["cover"]
            files.append(c["cover"])
        files.append(str(report_path))
        report_path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
        return report
    finally:
        shutil.rmtree(workdir, ignore_errors=True)


# ---------------------------------------------------------------- report

def print_report(r, out=sys.stdout):
    p = r["probe"]
    P = lambda s="": print(s, file=out)  # noqa: E731
    P()
    P(("EDIT PLAN" if r["dry_run"] else "EDITED") + f"  ·  {Path(r['output']).name}")
    P(RULE)
    P(f"  input       {Path(r['input']).name}  {p['width']}x{p['height']} "
      f"{orientation(p['width'], p['height'])}, {p['fps']:g} fps, {p['duration']:.1f}s, "
      f"{'audio' if p['has_audio'] else 'no audio'}")
    w = r["window"]
    if w["start"] > 0 or w["end"] < p["duration"]:
        P(f"  clip        {tc(w['start'])} - {tc(w['end'])}  ({w['length']:.1f}s)")
    P(f"  length      {w['length']:.1f}s -> {r['output_duration']:.1f}s")
    s = r["silence"]
    if s["enabled"]:
        P(f"  cut         {r['seconds_cut']:.1f}s in {r['cuts']} cuts  "
          f"(quieter than {s['db']:g} dB for {s['min_silence']:g}s+, {s['pad']:g}s pad)")
    else:
        P(f"  cut         {r['seconds_cut']:.1f}s in {r['cuts']} cuts  (silence cutting off)")
    if r["first_word_at"] is not None:
        P(f"  first word  {r['first_word_at']:.2f}s")
    P(f"  frame       1080x1920, {r['crop']}, H.264 high + AAC, 30 fps")
    h = r["hook_card"]
    P(f"  hook card   " + (f"\"{h['text']}\"  0:00.0 - {tc(h['end'])}" if h else "none"))
    c = r["captions"]
    if c["source"] == "none":
        P("  captions    none")
    else:
        how = {"burn": "burned in", "srt": "sidecar .srt only", "none": "off"}[c["mode"]]
        P(f"  captions    {c['cards']} cards, {how}, from {c['source']}")
        if c["detail"]:
            P(f"              {c['detail']}")
    P(THIN)
    if r["warnings"]:
        P("  WARNINGS")
        for x in r["warnings"]:
            P(f"  ! {x}")
    else:
        P("  no warnings")
    for n in r["notes"]:
        P(f"  - {n}")
    P(THIN)
    if r["dry_run"]:
        P("  ffmpeg, not run:")
        for cmd in r["commands"]:
            P(f"  $ {cmd}")
        if r.get("run_from"):
            P(f"  (run from {r['run_from']})")
        P("\n  Dry run. Nothing was encoded.\n")
        return
    P("  files")
    for f in r["files"]:
        P(f"  {f}")
    P("\n  Look at the check frames before you post. Red is covered by the app.")
    P("  Nothing was uploaded. Nothing was posted.\n")


def build_parser():
    ap = argparse.ArgumentParser(description="Turn raw footage into a 1080x1920 Reel, locally.")
    ap.add_argument("input")
    ap.add_argument("--out", required=True, help="output .mp4")
    ap.add_argument("--script", help="script text, one line per beat (captions, approximate)")
    ap.add_argument("--srt", help="subtitles timed against the input file")
    ap.add_argument("--cut-silence", action="store_true", help="cut pauses out")
    ap.add_argument("--silence-db", type=float, default=-35.0)
    ap.add_argument("--min-silence", type=float, default=0.45)
    ap.add_argument("--pad", type=float, default=0.12)
    ap.add_argument("--max-length", type=float, default=90.0)
    ap.add_argument("--crop", choices=["auto", "center", "none"], default="auto")
    ap.add_argument("--captions", choices=["burn", "srt", "none"], default="burn")
    ap.add_argument("--hook-text", default=None)
    ap.add_argument("--start", default=None, help="HH:MM:SS, clip start in the input")
    ap.add_argument("--end", default=None, help="HH:MM:SS, clip end in the input")
    ap.add_argument("--cover-at", type=float, default=None, help="also save a cover frame")
    ap.add_argument("--lang", default="auto", help="language for Whisper, e.g. en, hi")
    ap.add_argument("--no-transcribe", action="store_true", help="do not use Whisper")
    ap.add_argument("--no-check-frames", action="store_true")
    # ultrafast is left out: it switches off CABAC and x264 falls back to
    # Baseline, which is not the High profile Instagram handles best.
    ap.add_argument("--preset", default="medium",
                    choices=["superfast", "veryfast", "faster", "fast", "medium", "slow", "slower"],
                    help="x264 speed/size trade-off (default medium)")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--json", action="store_true")
    return ap


def main(argv=None, out=sys.stdout):
    a = build_parser().parse_args(argv)
    if a.pad < 0 or a.min_silence <= 0 or a.max_length <= 0:
        print("error: --pad, --min-silence and --max-length must be positive", file=sys.stderr)
        return 2
    try:
        report = edit(a)
    except (EditError, cover.CoverError) as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    if a.json:
        print(json.dumps(report, indent=2), file=out)
    else:
        print_report(report, out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
