#!/usr/bin/env python3
"""
direct.py - the engine behind /ig-direct: Claude directs, ffmpeg renders.

Claude (the director) and its section agents never touch ffmpeg. They read
what this script finds in the footage and write small JSON files: the brief,
the cuts, the caption design, the look and the sound. This script merges them
into one plan, checks the plan against a virality checklist, renders a
storyboard of real frames for the user to approve, and only then renders the
Reel.

  python3 direct.py analyze raw.mov [--dir DIR] [--lang en]   # footage.json, transcript, frame sheets
  python3 direct.py merge DIR                                 # brief+cuts+captions+look+sound -> plan.json
  python3 direct.py check DIR                                 # the virality checklist, scored
  python3 direct.py storyboard DIR [--preview]                # storyboard/ frames + storyboard.html
  python3 direct.py render DIR [--out reel.mp4]               # the Reel, after the user approved
  python3 direct.py fonts                                     # fetch the free caption fonts

Everything runs locally. The only network use is `fonts` (Google Fonts, OFL)
and whatever a local Whisper does when it loads its model. Nothing is posted.
"""

import argparse
import datetime as dt
import html
import json
import math
import os
import re
import shutil
import subprocess
import sys
import tempfile
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
for cand in (HERE.parent / "ig-edit", Path.home() / ".claude" / "skills" / "ig-edit"):
    if (cand / "edit.py").exists():
        sys.path.insert(0, str(cand))
        break
import edit  # noqa: E402
import cover  # noqa: E402

W, H, FPS = edit.W, edit.H, edit.FPS
SAFE_TOP, SAFE_BOTTOM, SAFE_RIGHT, SIDE = edit.SAFE_TOP, edit.SAFE_BOTTOM, edit.SAFE_RIGHT, edit.SIDE
RAIL_TOP = 1000            # below this the like/comment/share rail sits on the right
WORD_PAD_IN, WORD_PAD_OUT = 0.16, 0.10      # Whisper word starts run late; ends are the next start
SECTION_FILES = ("brief", "cuts", "captions", "look", "sound")

FONTS_DIR = Path(os.environ.get("IG_STUDIO_HOME") or "~/.ig-studio").expanduser() / "fonts"
FONT_SOURCES = {           # family -> file in github.com/google/fonts (all SIL Open Font License)
    "Anton": "ofl/anton/Anton-Regular.ttf",
    "Bebas Neue": "ofl/bebasneue/BebasNeue-Regular.ttf",
    "Archivo Black": "ofl/archivoblack/ArchivoBlack-Regular.ttf",
    "Poppins ExtraBold": "ofl/poppins/Poppins-ExtraBold.ttf",
    "Poppins SemiBold": "ofl/poppins/Poppins-SemiBold.ttf",
}
FONT_FALLBACK = {"darwin": "Helvetica Neue", "win32": "Arial", "linux": "DejaVu Sans"}
WIDTH_FACTOR = {"Anton": 0.43, "Bebas Neue": 0.36, "Archivo Black": 0.70,     # measured, upper case
                "Poppins ExtraBold": 0.63, "Poppins SemiBold": 0.61}

GRADES = {
    "natural": "",
    "punchy": "eq=contrast=1.10:saturation=1.22:gamma=0.98",
    "vibrant": "eq=saturation=1.40:contrast=1.05",
    "warm": "colorbalance=rs=0.05:gs=0.01:bs=-0.05:rm=0.04:bm=-0.03,eq=saturation=1.08",
    "cool": "colorbalance=rs=-0.04:bs=0.05:rm=-0.02:bm=0.04,eq=saturation=1.02",
    "cinematic": "colorbalance=rs=-0.04:bs=0.05:rh=0.05:bh=-0.04,eq=contrast=1.08:saturation=0.92",
    "moody": "eq=brightness=-0.03:contrast=1.15:saturation=0.80,colorbalance=bs=0.03",
    "vintage": "curves=preset=vintage,eq=saturation=0.90",
    "bw": "hue=s=0,eq=contrast=1.18",
}
CAPTION_STYLES = ("bold-pop", "karaoke", "clean", "boxed", "minimal", "none")
OVERLAY_STYLES = ("hook", "label", "stat", "cta")
TRANSITIONS = ("cut", "flash", "dip", "punch")
ROLES = ("hook", "setup", "value", "proof", "payoff", "cta", "loop", "broll")
SFX_KINDS = ("none", "whoosh", "pop")
EMOJI_RE = re.compile("[\U0001F000-\U0001FAFF☀-➿️‍⭐⭕←-⇿]")
SENTENCE_END = re.compile(r"[.!?।۔؟]$")


class DirectError(Exception):
    pass


# ---------------------------------------------------------------- helpers

def tc(t):
    return edit.tc(t)


def stamp():
    return dt.datetime.now().strftime("%Y%m%d-%H%M%S")


def read_json(path, default=None):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except FileNotFoundError:
        return default
    except json.JSONDecodeError as e:
        raise DirectError(f"{Path(path).name} is not valid JSON: {e}")


def write_json(path, data):
    Path(path).write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def ffmpeg():
    return cover.tool("ffmpeg")


def run(cmd, cwd=None):
    return subprocess.run(cmd, capture_output=True, text=True, cwd=cwd)


def num(v, lo, hi, default):
    try:
        x = float(v)
    except (TypeError, ValueError):
        return default
    if math.isnan(x):
        return default
    return max(lo, min(hi, x))


def ass_color(value, default="#FFFFFF"):
    """'#RRGGBB' or '#RRGGBBAA' (AA = opacity) -> ASS &HAABBGGRR."""
    s = str(value or default).strip().lstrip("#")
    if not re.fullmatch(r"[0-9a-fA-F]{6}([0-9a-fA-F]{2})?", s):
        s = default.lstrip("#")
    r, g, b = s[0:2], s[2:4], s[4:6]
    a = 255 - int(s[6:8], 16) if len(s) == 8 else 0
    return f"&H{a:02X}{b}{g}{r}".upper()


def ffcolor(value, default="#FFFFFF"):
    s = str(value or default).strip().lstrip("#")
    if not re.fullmatch(r"[0-9a-fA-F]{6}([0-9a-fA-F]{2})?", s):
        s = default.lstrip("#")
    return "0x" + s[:6]


def filter_path(p):
    """A path inside an ffmpeg filter argument."""
    return str(p).replace("\\", "/").replace(":", "\\:").replace("'", "\\'")


# ---------------------------------------------------------------- fonts

def fetch_fonts(quiet=False):
    """Download the free caption fonts once. Missing ones fall back to the system font."""
    FONTS_DIR.mkdir(parents=True, exist_ok=True)
    got = {}
    for fam, rel in FONT_SOURCES.items():
        dest = FONTS_DIR / Path(rel).name
        if not dest.exists() or dest.stat().st_size < 10000:
            url = "https://github.com/google/fonts/raw/main/" + rel
            try:
                with urllib.request.urlopen(url, timeout=30) as r:
                    data = r.read()
                if len(data) < 10000 or data[:4] not in (b"\x00\x01\x00\x00", b"OTTO", b"true"):
                    raise ValueError("not a font file")
                tmp = dest.with_suffix(".part")
                tmp.write_bytes(data)
                tmp.replace(dest)
            except Exception as e:  # noqa: BLE001 - any failure means "use the system font"
                if not quiet:
                    print(f"  could not fetch {fam}: {e}", file=sys.stderr)
                continue
        got[fam] = str(dest)
    return got


def available_fonts():
    return {fam for fam, rel in FONT_SOURCES.items() if (FONTS_DIR / Path(rel).name).exists()}


def font_name(requested):
    fam = str(requested or "").strip()
    have = available_fonts()
    for f in FONT_SOURCES:
        if f.lower() == fam.lower() and f in have:
            return f
    if fam.lower() in ("poppins",) and "Poppins ExtraBold" in have:
        return "Poppins ExtraBold"
    return FONT_FALLBACK.get(sys.platform, "Arial")


# ---------------------------------------------------------------- analyze

def detect_scenes(src):
    r = run([ffmpeg(), "-hide_banner", "-nostdin", "-i", str(src), "-an",
             "-vf", "scale=320:-2,select='gt(scene,0.32)',showinfo", "-f", "null", "-"])
    return [round(float(m), 2) for m in re.findall(r"pts_time:([\d.]+)", r.stderr)]


def group_lines(words, gap=0.35, max_words=14):
    lines, cur = [], []
    for w in words:
        if cur and (w["start"] - cur[-1]["end"] > gap or len(cur) >= max_words):
            lines.append(cur)
            cur = []
        cur.append(w)
        if SENTENCE_END.search(w["w"]):
            lines.append(cur)
            cur = []
    if cur:
        lines.append(cur)
    return [{"line": i, "words": [ws[0]["i"], ws[-1]["i"]], "start": ws[0]["start"], "end": ws[-1]["end"],
             "text": " ".join(x["w"] for x in ws)} for i, ws in enumerate(lines)]


def clean_words(raw):
    out = []
    for w in raw:
        text = str(w.get("word") or "").strip()
        if not text or text.startswith("[") or text in ("-", "--"):
            continue
        s, e = float(w["start"]), float(w["end"])
        if out and text[0] in ",.!?;:'’" and len(text) <= 3:      # whisper.cpp splits punctuation off
            out[-1]["w"] += text
            out[-1]["end"] = max(out[-1]["end"], e)
            continue
        out.append({"i": len(out), "w": text, "start": round(s, 3), "end": round(max(e, s + 0.02), 3)})
    return out


def refine_words(words, silences):
    """Whisper's word ends run straight through pauses (DTW gives good starts,
    and each end is just the next start). Trust the start, end the word where
    the pause begins. A start a little way into a pause is the tail of the
    speech before it, so it moves back to just before the pause."""
    for k, w in enumerate(words):
        prev_end = words[k - 1]["end"] if k else 0.0
        for a, b in silences:
            if b <= w["start"] or a >= w["end"]:
                continue
            if a <= w["start"] < b:
                if w["start"] - a <= min(0.5, b - w["start"]):
                    w["end"] = round(a, 3)
                    w["start"] = round(max(prev_end, a - 0.25), 3)
                else:
                    w["start"] = round(b, 3)
            elif w["start"] < a < w["end"]:
                w["end"] = round(a, 3)
        for a, b in silences:              # the first word after a pause starts where the pause ends
            if b <= w["start"] <= b + 0.6 and (k == 0 or words[k - 1]["end"] <= b + 0.01):
                w["start"] = round(b, 3)
                break
        if w["end"] - w["start"] < 0.04:
            w["end"] = round(w["start"] + 0.04, 3)
    return words


def frame_sheets(src, dur, frames_dir, every, aspect):
    frames_dir.mkdir(parents=True, exist_ok=True)
    r = run([ffmpeg(), "-hide_banner", "-nostdin", "-loglevel", "error", "-y", "-i", str(src), "-an",
             "-vf", f"fps=1/{every:.3f},scale=-2:640", "-q:v", "4", str(frames_dir / "f_%03d.jpg")])
    if r.returncode != 0:
        raise DirectError(f"could not grab frames: {r.stderr.strip()[-300:]}")
    files = sorted(frames_dir.glob("f_*.jpg"))
    frames = [{"t": round(i * every, 2), "path": str(p)} for i, p in enumerate(files)]
    sheets = []
    cw, ch = (240, 427) if aspect < 1 else (320, max(120, int(320 * aspect) // 2 * 2))
    for k in range(0, len(files), 12):
        sheet = frames_dir.parent / f"sheet-{k // 12 + 1}.jpg"
        inputs, chains = [], []
        for j, p in enumerate(files[k:k + 12]):
            t = (k + j) * every
            inputs += ["-i", str(p)]
            label = tc(t).replace(":", "\\:")
            chains.append(f"[{j}:v]scale={cw}:{ch}:force_original_aspect_ratio=decrease,pad={cw}:{ch}:-1:-1:black,"
                          f"drawtext=text='{label}':x=6:y=6:fontsize=22:fontcolor=white:box=1:boxcolor=black@0.7[t{j}]")
        n = len(chains)
        cols = min(6, n)
        rows = math.ceil(n / cols)
        fc = ";".join(chains) + ";" + "".join(f"[t{j}]" for j in range(n)) + \
            f"xstack=inputs={n}:layout=" + "|".join(f"{(j % cols) * cw}_{(j // cols) * ch}" for j in range(n)) + \
            f":fill=black[out]" if n > 1 else ";".join(chains).replace("[t0]", "[out]")
        r = run([ffmpeg(), "-hide_banner", "-nostdin", "-loglevel", "error", "-y", *inputs,
                 "-filter_complex", fc, "-map", "[out]", "-frames:v", "1", "-q:v", "3", str(sheet)])
        if r.returncode == 0:
            sheets.append({"path": str(sheet), "from": round(k * every, 2),
                           "to": round((k + n - 1) * every, 2), "cols": cols, "rows": rows})
    return frames, sheets


def analyze(src, work, lang="auto", every=None, no_transcribe=False):
    src = Path(src).expanduser().resolve()
    if not src.exists():
        raise DirectError(f"{src} not found")
    work.mkdir(parents=True, exist_ok=True)
    info = edit.probe(src)
    dur = info["duration"]
    notes = []

    silences = []
    if info["has_audio"]:
        silences, _ = edit.detect_silences(src, 0.0, dur, True, -35, 0.35)
    words, transcriber = [], None
    if info["has_audio"] and not no_transcribe:
        t = edit.find_transcriber()
        if t:
            tmp = Path(tempfile.mkdtemp(prefix="ig-direct-"))
            try:
                wav = tmp / "speech.wav"
                r = run([ffmpeg(), "-hide_banner", "-nostdin", "-loglevel", "error", "-y", "-i", str(src),
                         "-vn", "-ac", "1", "-ar", "16000", "-c:a", "pcm_s16le", str(wav)])
                if r.returncode != 0:
                    raise DirectError(f"could not extract audio: {r.stderr.strip()[-300:]}")
                words = refine_words(clean_words(edit.transcribe(t, wav, lang, tmp)), silences)
                transcriber = t["kind"]
            finally:
                shutil.rmtree(tmp, ignore_errors=True)
        else:
            notes.append("no local Whisper, so no transcript. IG Studio installs it on start; "
                         "or run: python3 ~/.claude/skills/ig-edit/edit.py --whisper-check")
    lines = group_lines(words)
    every = every or max(1.0, round(dur / 36, 1))
    frames, sheets = frame_sheets(src, dur, work / "frames", every, info["height"] / max(1, info["width"]))
    scenes = detect_scenes(src)

    footage = {
        "version": 1, "source": str(src), "analyzed_at": dt.datetime.now().isoformat(timespec="seconds"),
        "info": {"width": info["width"], "height": info["height"], "fps": info["fps"], "duration": dur,
                 "has_audio": info["has_audio"], "orientation": edit.orientation(info["width"], info["height"])},
        "transcriber": transcriber, "lang": lang, "words": words, "lines": lines,
        "silences": [[round(a, 2), round(b, 2)] for a, b in silences],
        "scenes": scenes, "frame_every": every, "frames": frames, "sheets": sheets, "notes": notes,
    }
    write_json(work / "footage.json", footage)
    (work / "transcript.txt").write_text(transcript_text(footage), encoding="utf-8")
    return footage


def transcript_text(f):
    out = [f"# {Path(f['source']).name}  {f['info']['width']}x{f['info']['height']} "
           f"{f['info']['orientation']}, {f['info']['duration']:.1f}s, transcriber: {f['transcriber'] or 'none'}",
           "# line [first word - last word] start-end: text   (shots refer to word numbers)", ""]
    for ln in f["lines"]:
        out.append(f"L{ln['line']:<3} [{ln['words'][0]}-{ln['words'][1]}] {ln['start']:.2f}-{ln['end']:.2f}: {ln['text']}")
    out += ["", "# words: number start text"]
    out += [f"{w['i']:>4} {w['start']:7.2f} {w['w']}" for w in f["words"]]
    if f["silences"]:
        out += ["", "# pauses (start-end): " + ", ".join(f"{a:.2f}-{b:.2f}" for a, b in f["silences"])]
    if f["scenes"]:
        out += ["# picture changes at: " + ", ".join(f"{s:.2f}" for s in f["scenes"])]
    return "\n".join(out) + "\n"


# ---------------------------------------------------------------- merge + plan

def merge(work):
    parts = {}
    for name in SECTION_FILES:
        parts[name] = read_json(work / f"{name}.json", {})
    footage = read_json(work / "footage.json")
    if not footage:
        raise DirectError(f"no footage.json in {work}. Run: direct.py analyze <video> --dir {work}")
    cuts, caps = parts["cuts"] or {}, parts["captions"] or {}
    plan = {
        "version": 1, "source": footage["source"], "merged_at": dt.datetime.now().isoformat(timespec="seconds"),
        "brief": parts["brief"] or {},
        "shots": cuts.get("shots") or [],
        "captions": caps.get("captions") or {},
        "text_overlays": caps.get("text_overlays") or [],
        "look": parts["look"] or {},
        "sound": parts["sound"] or {},
        "cover": (parts["look"] or {}).get("cover") or cuts.get("cover") or {},
        "notes": {k: (parts[k] or {}).get("why") for k in SECTION_FILES if (parts[k] or {}).get("why")},
    }
    old = read_json(work / "plan.json", {}) or {}
    if old.get("approved"):
        plan["previously_approved"] = old.get("approved")
    write_json(work / "plan.json", plan)
    return plan


def load(work):
    footage = read_json(work / "footage.json")
    plan = read_json(work / "plan.json")
    if not footage:
        raise DirectError(f"no footage.json in {work}. Run analyze first.")
    if not plan:
        raise DirectError(f"no plan.json in {work}. Run merge first.")
    return footage, plan


def resolve_shots(plan, footage):
    """Shots -> concrete source windows and their place on the output timeline."""
    words = footage["words"]
    dur = footage["info"]["duration"]
    errors, shots, t = [], [], 0.0
    for k, s in enumerate(plan.get("shots") or []):
        sid = str(s.get("id") or f"s{k + 1}")
        if "words" in s and s["words"] is not None:
            try:
                i, j = int(s["words"][0]), int(s["words"][1])
            except (TypeError, ValueError, IndexError):
                errors.append(f"{sid}: words must be [first, last] word numbers")
                continue
            if not (0 <= i <= j < len(words)):
                errors.append(f"{sid}: words [{i}, {j}] are outside 0-{len(words) - 1}")
                continue
            a = words[i]["start"] - num(s.get("pad_in"), 0, 1, WORD_PAD_IN)
            b = words[j]["end"] + num(s.get("pad_out"), 0, 1.5, WORD_PAD_OUT)
            if i > 0:       # never reach back into more than the last 40% of the word before
                pw = words[i - 1]
                a = max(a, pw["start"] + 0.6 * (pw["end"] - pw["start"]))
            if j + 1 < len(words):
                nw = words[j + 1]
                b = min(b, max(words[j]["end"], nw["start"] - 0.03))
        else:
            try:
                a, b = float(s["in"]), float(s["out"])
            except (KeyError, TypeError, ValueError):
                errors.append(f"{sid}: needs words [first, last] or in/out seconds")
                continue
        a, b = max(0.0, a), min(dur, b)
        if b - a < 0.2:
            errors.append(f"{sid}: shorter than 0.2s")
            continue
        speed = num(s.get("speed"), 0.5, 2.0, 1.0)
        z = s.get("zoom", 1.0)
        z0, z1 = (z if isinstance(z, (list, tuple)) and len(z) == 2 else (z, z))
        z0, z1 = num(z0, 1.0, 2.5, 1.0), num(z1, 1.0, 2.5, 1.0)
        focus = s.get("focus") or [0.5, 0.45]
        fx = num(focus[0] if len(focus) > 0 else 0.5, 0, 1, 0.5)
        fy = num(focus[1] if len(focus) > 1 else 0.45, 0, 1, 0.45)
        trans = s.get("transition") or "cut"
        if trans not in TRANSITIONS:
            errors.append(f"{sid}: transition must be one of {', '.join(TRANSITIONS)}")
            trans = "cut"
        role = s.get("role") or "value"
        d = (b - a) / speed
        shots.append({"id": sid, "a": round(a, 3), "b": round(b, 3), "speed": speed, "z0": z0, "z1": z1,
                      "fx": fx, "fy": fy, "transition": trans, "role": role, "off": round(t, 3),
                      "dur": round(d, 3), "note": s.get("note") or "", "words": s.get("words")})
        t += d
    return shots, round(t, 3), errors


def to_out(shots, src_t):
    for s in shots:
        if s["a"] <= src_t <= s["b"]:
            return s["off"] + (src_t - s["a"]) / s["speed"], s
    return None, None


def caption_spec(plan):
    c = dict(plan.get("captions") or {})
    style = c.get("style") or "bold-pop"
    if style not in CAPTION_STYLES:
        style = "bold-pop"
    defaults = {"bold-pop": (3, 108, "upper"), "karaoke": (4, 96, "upper"), "clean": (5, 74, "as-is"),
                "boxed": (5, 72, "as-is"), "minimal": (6, 60, "lower"), "none": (0, 0, "as-is")}[style]
    return {
        "style": style,
        "font": font_name(c.get("font") or ("Anton" if style in ("bold-pop", "karaoke") else "Poppins ExtraBold")),
        "size": int(num(c.get("size"), 40, 140, defaults[1])),
        "case": c.get("case") or defaults[2],
        "max_words": int(num(c.get("max_words"), 1, 8, defaults[0])),
        "color": c.get("color") or "#FFFFFF",
        "highlight": c.get("highlight") or "#FFD400",
        "outline": num(c.get("outline"), 0, 14, 6 if style != "boxed" else 0),
        "outline_color": c.get("outline_color") or "#000000",
        "shadow": num(c.get("shadow"), 0, 8, 2),
        "box_color": c.get("box_color") or "#000000B0",
        "y": num(c.get("y"), 0.1, 0.9, 0.66),
        "emphasis": {str(x).lower().strip(".,!?") for x in (c.get("emphasis") or [])},
        "emphasis_words": {int(x) for x in (c.get("emphasis_words") or []) if str(x).lstrip("-").isdigit()},
        "emphasis_scale": num(c.get("emphasis_scale"), 1.0, 1.6, 1.2),
        "fixes": {int(k): str(v) for k, v in (c.get("fixes") or {}).items() if str(k).isdigit()},
        "overrides": {str(o.get("shot")): o for o in (c.get("overrides") or []) if o.get("shot")},
        "hide_during_overlays": c.get("hide_during_overlays", True),
        "pop": c.get("pop", style in ("bold-pop", "karaoke")),
    }


def apply_case(text, case):
    if case == "upper":
        return text.upper()
    if case == "lower":
        return text.lower()
    if case == "sentence":
        return text[:1].upper() + text[1:]
    return text


def caption_cards(plan, footage, shots):
    spec = caption_spec(plan)
    if spec["style"] == "none":
        return [], spec
    words = footage["words"]
    placed = []
    for w in words:
        mid = (w["start"] + w["end"]) / 2
        t, s = to_out(shots, mid)
        if s is None:
            continue
        text = spec["fixes"].get(w["i"], w["w"])
        if not text.strip():
            # a fix of "" hides the word. When it is glued to the word before (auto|correlation
            # -> "autocorrelation", ""), that word stays on screen through it: no caption gap.
            st = s["off"] + (max(w["start"], s["a"]) - s["a"]) / s["speed"]
            en = s["off"] + (min(w["end"], s["b"]) - s["a"]) / s["speed"]
            if placed and placed[-1]["shot"] == s["id"] and st - placed[-1]["end"] < 0.3:
                placed[-1]["end"] = round(max(placed[-1]["end"], en), 3)
            continue
        st = s["off"] + (max(w["start"], s["a"]) - s["a"]) / s["speed"]
        en = s["off"] + (min(w["end"], s["b"]) - s["a"]) / s["speed"]
        placed.append({"i": w["i"], "text": text, "start": round(st, 3), "end": round(max(en, st + 0.05), 3),
                       "shot": s["id"]})
    placed.sort(key=lambda w: w["start"])            # shots can be reordered: caption in output order
    cards, cur = [], []
    for w in placed:
        if cur and (len(cur) >= spec["max_words"] or w["shot"] != cur[-1]["shot"]
                    or w["start"] - cur[-1]["end"] > 0.5 or SENTENCE_END.search(cur[-1]["text"])
                    or (cur[-1]["text"].endswith(",") and len(cur) >= 2)):
            cards.append(cur)
            cur = []
        cur.append(w)
    if cur:
        cards.append(cur)
    merged = []                              # a card on screen for a blink is a flicker: fold it in
    for ws in cards:
        short = ws[-1]["end"] - ws[0]["start"] < 0.3
        if short and merged and merged[-1][-1]["shot"] == ws[0]["shot"] \
                and ws[0]["start"] - merged[-1][-1]["end"] < 0.3:
            merged[-1].extend(ws)
        else:
            merged.append(ws)
    cards = merged
    out = []
    for k, ws in enumerate(cards):
        start = ws[0]["start"]
        end = max(ws[-1]["end"], start + 0.45)
        if k + 1 < len(cards):
            nxt = cards[k + 1][0]["start"]
            end = nxt if nxt - end < 0.35 else end
            end = min(end, nxt)
        ov = spec["overrides"].get(ws[0]["shot"], {})
        out.append({"start": round(start, 3), "end": round(end, 3), "shot": ws[0]["shot"], "words": ws,
                    "y": num(ov.get("y"), 0.1, 0.9, spec["y"]),
                    "size": int(num(ov.get("size"), 40, 140, spec["size"])),
                    "hide": bool(ov.get("hide"))})
    return out, spec


def overlay_list(plan, out_dur):
    res, errors = [], []
    for k, o in enumerate(plan.get("text_overlays") or []):
        text = str(o.get("text") or "").strip()
        if not text:
            continue
        style = o.get("style") or "label"
        if style not in OVERLAY_STYLES:
            errors.append(f"overlay {k + 1}: style must be one of {', '.join(OVERLAY_STYLES)}")
            style = "label"
        st = num(o.get("start"), 0, out_dur, 0.0)
        en = num(o.get("end"), 0, out_dur, min(out_dur, st + 2.5))
        if en <= st:
            errors.append(f"overlay {k + 1}: end must be after start")
            continue
        size = {"hook": 108, "label": 78, "stat": 180, "cta": 84}[style]
        res.append({"text": text, "style": style, "start": round(st, 3), "end": round(en, 3),
                    "y": num(o.get("y"), 0.1, 0.9, {"hook": 0.24, "label": 0.2, "stat": 0.36, "cta": 0.72}[style]),
                    "size": int(num(o.get("size"), 36, 220, size)),
                    "color": o.get("color") or ("#000000" if style == "cta" else "#FFFFFF"),
                    "bg": o.get("bg") or {"hook": "#000000C0", "label": "", "stat": "", "cta": "#FFD400"}[style],
                    "font": font_name(o.get("font") or ("Anton" if style in ("stat", "hook") else "Poppins ExtraBold"))})
    return res, errors


# ---------------------------------------------------------------- ASS

def strip_emoji(text):
    return re.sub(r"\s{2,}", " ", EMOJI_RE.sub("", text)).strip()


def ass_escape(text):
    return strip_emoji(text).replace("->", "→").replace("\\", "/").replace("{", "(").replace("}", ")")


_FONT_CACHE = {}


def _measure(font):
    """A Pillow font at 100px for the real width, if Pillow and the font file are there."""
    if font not in _FONT_CACHE:
        _FONT_CACHE[font] = None
        rel = FONT_SOURCES.get(font)
        path = FONTS_DIR / Path(rel).name if rel else None
        if path and path.exists():
            try:
                from PIL import ImageFont
                _FONT_CACHE[font] = ImageFont.truetype(str(path), 100)
            except Exception:  # noqa: BLE001 - no Pillow: use the measured factors
                pass
    return _FONT_CACHE[font]


def text_width(text, size, font):
    ft = _measure(font)
    if ft is not None:
        return ft.getlength(text) * size / 100
    return len(text) * size * WIDTH_FACTOR.get(font, 0.6)


def fit_lines(text, size, font, max_w):
    """One line if it fits, else two balanced lines, else a smaller size."""
    if text_width(text, size, font) <= max_w:
        return [text], size
    words = text.split()
    if len(words) >= 2:
        best = None
        for k in range(1, len(words)):
            a, b = " ".join(words[:k]), " ".join(words[k:])
            m = max(text_width(a, size, font), text_width(b, size, font))
            if best is None or m < best[0]:
                best = (m, [a, b])
        if best[0] <= max_w:
            return best[1], size
        return best[1], max(36, int(size * max_w / best[0]))
    return [text], max(36, int(size * max_w / text_width(text, size, font)))


def card_x_and_width(y_px, text_w=None):
    """Centred, unless the line is wide enough to run under the like/comment/share
    buttons on the right (below RAIL_TOP): then it shifts left, just enough."""
    if y_px <= RAIL_TOP:
        return W / 2, W - 2 * SIDE
    max_w = W - SAFE_RIGHT - 2 * SIDE + 40
    if text_w is None:
        return (SIDE + (W - SAFE_RIGHT - SIDE)) / 2, max_w
    right_limit = W - SAFE_RIGHT - 10
    x = min(W / 2, right_limit - text_w / 2)
    return max(SIDE + text_w / 2, x), max_w


def safe_y(y_frac, size, lines):
    half = size * lines * 0.6
    return int(max(SAFE_TOP + half, min(SAFE_BOTTOM - half, y_frac * H)))


def ass_document(cards, spec, overlays):
    font = spec["font"]
    cap_border = 3 if spec["style"] == "boxed" else 1
    outline = 14 if spec["style"] == "boxed" else spec["outline"]
    back = spec["box_color"] if spec["style"] == "boxed" else "#00000080"
    head = f"""[Script Info]
ScriptType: v4.00+
PlayResX: {W}
PlayResY: {H}
WrapStyle: 2
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Caption,{font},{spec['size']},{ass_color(spec['color'])},{ass_color(spec['highlight'])},{ass_color(spec['box_color'] if cap_border == 3 else spec['outline_color'])},{ass_color(back)},-1,0,0,0,100,100,1,0,{cap_border},{outline},{spec['shadow']},5,{SIDE},{SIDE},0,1
Style: Over,{font},80,&H00FFFFFF,&H00FFFFFF,&H00000000,&H80000000,-1,0,0,0,100,100,1,0,1,6,2,5,{SIDE},{SIDE},0,1
Style: Box,{font},80,&H00FFFFFF,&H00FFFFFF,&H40000000,&H40000000,-1,0,0,0,100,100,1,0,3,20,0,5,{SIDE},{SIDE},0,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
    ev = []
    hi = ass_color(spec["highlight"])
    base = ass_color(spec["color"])
    for c in cards:
        if c["hide"]:
            continue
        texts = [apply_case(ass_escape(w["text"]), spec["case"]) for w in c["words"]]
        if not any(texts):
            continue
        y0 = c["y"] * H
        x, max_w = card_x_and_width(y0)
        lines, size = fit_lines(" ".join(t for t in texts if t), c["size"], font, max_w)
        y = safe_y(c["y"], size, len(lines))
        widest = max(text_width(ln, size, font) for ln in lines) * (spec["emphasis_scale"] if spec["style"] == "bold-pop" else 1)
        x, _ = card_x_and_width(y, widest)
        split_at = len(lines[0].split()) if len(lines) == 2 else None
        emph = [(w["i"] in spec["emphasis_words"]) or (w["text"].lower().strip(".,!?\"'") in spec["emphasis"])
                for w in c["words"]]
        karaoke = spec["style"] in ("bold-pop", "karaoke")
        steps = range(len(c["words"])) if karaoke else [None]
        for n in steps:
            st = c["start"] if n in (None, 0) else c["words"][n]["start"]
            en = c["end"] if n is None or n == len(c["words"]) - 1 else c["words"][n + 1]["start"]
            if en - st < 0.02:
                continue
            parts, wi = [], 0
            for k, t in enumerate(texts):
                if not t:
                    continue
                active = karaoke and k == n
                tag = ""
                if active or emph[k]:
                    sc = int(100 * (spec["emphasis_scale"] if (emph[k] or spec["style"] == "bold-pop") else 1.0))
                    tag = f"{{\\c{hi}\\fscx{sc}\\fscy{sc}}}"
                piece = f"{tag}{t}{{\\c{base}\\fscx100\\fscy100}}" if tag else t
                if split_at is not None and wi == split_at:
                    parts.append("\\N")
                elif parts:
                    parts.append(" ")
                parts.append(piece)
                wi += 1
            pop = "\\fscx86\\fscy86\\t(0,90,\\fscx100\\fscy100)" if spec["pop"] and n in (None, 0) and st > 0.05 else ""
            ev.append(f"Dialogue: 0,{edit.ass_time(st)},{edit.ass_time(en)},Caption,,0,0,0,,"
                      f"{{\\an5\\pos({int(x)},{y})\\fs{size}{pop}}}{''.join(parts)}")
    for o in overlays:
        text = ass_escape(o["text"])
        if not text:
            continue
        lines, size = fit_lines(text, o["size"], o["font"], W - 2 * SIDE - 60)
        y = safe_y(o["y"], size, len(lines))
        x, _ = card_x_and_width(y, max(text_width(ln, size, o["font"]) for ln in lines) + 40)
        body = "\\N".join(lines)
        boxed = bool(o["bg"])
        style = "Box" if boxed else "Over"
        tags = f"\\an5\\pos({int(x)},{y})\\fn{o['font']}\\fs{size}\\c{ass_color(o['color'])}"
        if boxed:
            tags += f"\\3c{ass_color(o['bg'])}\\4c{ass_color(o['bg'])}\\3a&H{255 - int((o['bg'] + 'FF')[7:9] if len(o['bg']) > 7 else 'FF', 16):02X}&"
        if o["start"] > 0.05:                # frame 1 is the thumbnail in the feed: no fade-in there
            tags += "\\fad(60,80)"
            if o["style"] in ("hook", "stat"):
                tags += "\\fscx80\\fscy80\\t(0,120,\\fscx100\\fscy100)"
        else:
            tags += "\\fad(0,80)"
        ev.append(f"Dialogue: 2,{edit.ass_time(o['start'])},{edit.ass_time(o['end'])},{style},,0,0,0,,{{{tags}}}{body}")
    return head + "\n".join(ev) + "\n"


# ---------------------------------------------------------------- ffmpeg graph

def shot_video_chain(k, s, info, look):
    """[0:v] -> 1080x1920 framed, zoomed, focused shot k."""
    w, h = info["width"], info["height"]
    s0 = max(W / w, H / h)
    bw, bh = w * s0, h * s0
    d = max(s["dur"], 0.05)
    z = f"({s['z0']:.4f}+({s['z1'] - s['z0']:.4f})*min(t/{d:.3f},1))"
    if s["transition"] == "punch":
        z = f"({z}*(1+0.12*max(0,1-t/0.25)))"
    chain = [f"[0:v]trim=start={s['a']:.4f}:end={s['b']:.4f},setpts=(PTS-STARTPTS)/{s['speed']:.4f},fps={FPS}"]
    chain.append(f"scale=w='trunc({bw:.2f}*{z}/2)*2':h='trunc({bh:.2f}*{z}/2)*2':eval=frame:flags=bicubic")
    chain.append(f"crop={W}:{H}:x='max(0,min(iw-{W},{s['fx']:.4f}*iw-{W // 2}))'"
                 f":y='max(0,min(ih-{H},{s['fy']:.4f}*ih-{H // 2}))'")
    chain.append("setsar=1")
    if s["transition"] == "flash" and k > 0:
        chain.append(f"fade=t=in:st=0:d=0.14:color={ffcolor(look.get('flash_color'), '#FFFFFF')}")
    elif s["transition"] == "dip" and k > 0:
        chain.append("fade=t=in:st=0:d=0.18:color=black")
    return ",".join(chain) + f"[v{k}]"


def look_chain(look):
    grade = look.get("grade") or "natural"
    parts = [GRADES.get(grade, "")]
    if look.get("vignette"):
        parts.append("vignette=angle=PI/5")
    if look.get("sharpen", True):
        parts.append("unsharp=5:5:0.45")
    return ",".join(p for p in parts if p)


def sfx_source(kind, volume):
    if kind == "pop":
        return f"sine=f=880:d=0.07:sample_rate=48000,afade=t=out:st=0.02:d=0.05,volume={volume:.2f}"
    return (f"anoisesrc=d=0.32:c=pink:r=48000:a=0.6,highpass=f=500,lowpass=f=4000,"
            f"afade=t=in:d=0.12,afade=t=out:st=0.12:d=0.2,volume={volume:.2f}")


def build_graph(plan, footage, shots, out_dur, ass_name, fontsdir, extra_inputs):
    info = footage["info"]
    look = plan.get("look") or {}
    sound = plan.get("sound") or {}
    parts, labels = [], []
    has_audio = info["has_audio"]
    for k, s in enumerate(shots):
        parts.append(shot_video_chain(k, s, info, look))
        if has_audio:
            at = f"atempo={s['speed']:.4f}," if abs(s["speed"] - 1) > 0.001 else ""
            parts.append(f"[0:a]atrim=start={s['a']:.4f}:end={s['b']:.4f},asetpts=PTS-STARTPTS,{at}"
                         f"aresample=48000,aformat=sample_rates=48000:channel_layouts=stereo[a{k}]")
            labels.append(f"[v{k}][a{k}]")
        else:
            labels.append(f"[v{k}]")
    n = len(shots)
    if has_audio:
        parts.append(f"{''.join(labels)}concat=n={n}:v=1:a=1[vc][voice0]")
    else:
        parts.append(f"{''.join(labels)}concat=n={n}:v=1:a=0[vc]")
        parts.append(f"anullsrc=r=48000:cl=stereo,atrim=duration={out_dur:.3f}[voice0]")

    # Picture: grade, captions, progress bar.
    v = "[vc]"
    lc = look_chain(look)
    chain = f"{v}{lc + ',' if lc else ''}"
    if ass_name:
        fd = f":fontsdir='{filter_path(fontsdir)}'" if fontsdir else ""
        chain += f"ass={ass_name}{fd},"
    chain += "format=yuv420p[vg]"
    parts.append(chain)
    pb = look.get("progress_bar")
    if pb:
        pb = pb if isinstance(pb, dict) else {}
        hgt = int(num(pb.get("height"), 4, 24, 10))
        y = 0 if (pb.get("position") or "top") == "top" else H - hgt
        parts.append(f"color=c={ffcolor(pb.get('color'), '#FFD400')}:s={W}x{hgt}:r={FPS}:d={out_dur:.3f}[pbar]")
        parts.append(f"[vg][pbar]overlay=x='-w+w*t/{out_dur:.3f}':y={y}:eval=frame:shortest=1,format=yuv420p[vout]")
    else:
        parts.append("[vg]null[vout]")

    # Sound: voice levelled, then SFX and music under it.
    lufs = num(sound.get("loudness"), -20, -9, -14)
    parts.append(f"[voice0]loudnorm=I={lufs:.1f}:TP=-1.5:LRA=11,aresample=48000[voice]")
    mix = ["[voice]"]
    sfx = sound.get("sfx") or {}
    kind = sfx.get("cuts") if sfx.get("cuts") in SFX_KINDS else "none"
    times = []
    if kind != "none":
        times = [s["off"] for s in shots[1:] if s["transition"] != "cut" or sfx.get("on_every_cut")]
    times += [num(t, 0, out_dur, None) for t in (sfx.get("at") or []) if num(t, 0, out_dur, None) is not None]
    times = sorted({round(t, 2) for t in times if t is not None})[:40]
    if times:
        vol = num(sfx.get("volume"), 0.05, 1.0, 0.35)
        src = sfx_source(kind if kind != "none" else "whoosh", vol)
        parts.append(f"{src},asplit={len(times)}" + "".join(f"[sx{i}]" for i in range(len(times))))
        for i, t in enumerate(times):
            ms = int(max(0, t - 0.08) * 1000)
            parts.append(f"[sx{i}]adelay={ms}|{ms},aformat=channel_layouts=stereo[sd{i}]")
            mix.append(f"[sd{i}]")
    music = sound.get("music") or {}
    if music.get("file") and extra_inputs.get("music") is not None:
        idx = extra_inputs["music"]
        vol = num(music.get("volume"), 0.02, 0.6, 0.12)
        mstart = num(music.get("start"), 0, 3600, 0)
        fade_at = max(0, out_dur - 1.2)
        parts.append(f"[{idx}:a]atrim=start={mstart:.2f},asetpts=PTS-STARTPTS,atrim=duration={out_dur:.3f},"
                     f"aresample=48000,aformat=sample_rates=48000:channel_layouts=stereo,volume={vol:.3f},"
                     f"afade=t=in:d=0.4,afade=t=out:st={fade_at:.2f}:d=1.2[mus0]")
        if music.get("duck", True):
            mix[0] = "[voicek]"
            parts.append("[voice]asplit=2[voicek][voicesc]")
            parts.append("[mus0][voicesc]sidechaincompress=threshold=0.04:ratio=8:attack=15:release=350[mus]")
        else:
            parts.append("[mus0]anull[mus]")
        mix.append("[mus]")
    if len(mix) > 1:
        parts.append(f"{''.join(mix)}amix=inputs={len(mix)}:duration=first:normalize=0,"
                     f"alimiter=limit=0.95,atrim=duration={out_dur:.3f}[aout]")
    else:
        parts.append(f"{mix[0]}atrim=duration={out_dur:.3f}[aout]")
    return ";".join(parts)


# ---------------------------------------------------------------- the checklist

def checklist(plan, footage, shots, out_dur, cards, overlays):
    """The things that decide whether people keep watching, as pass/fail lines."""
    items = []

    def add(key, ok, weight, msg, fix=""):
        items.append({"key": key, "ok": bool(ok), "weight": weight, "msg": msg, "fix": "" if ok else fix})

    brief = plan.get("brief") or {}
    first_word = min((c["start"] for c in cards), default=None)
    hook_ov = [o for o in overlays if o["start"] <= 0.3]
    add("hook_now", (first_word is not None and first_word <= 0.4) or hook_ov, 3,
        f"something to read or hear by 0.4s (first word {first_word if first_word is not None else 'none'}s)",
        "Start the first shot on the first word, or put a hook text up from frame 1.")
    add("hook_text", any(o["style"] in ("hook", "stat") and o["start"] <= 0.3 and len(o["text"].split()) <= 8
                         for o in overlays), 2,
        "a short hook text on screen from frame 1 (8 words or fewer)",
        "Add a text_overlays entry with style hook, start 0, 2-3 s long, 8 words or fewer.")
    first = shots[0] if shots else None
    add("hook_shot", first and first["role"] == "hook" and first["dur"] <= 4.0, 2,
        "the first shot is the hook and lasts 4 s or less",
        "Open on the strongest line (cold open). Move it to the front and keep it under 4 s.")
    add("length", 7 <= out_dur <= 90, 3, f"length {out_dur:.1f}s is between 7 and 90 s",
        "Trim to 15-45 s, or split into two Reels.")
    add("sweet_spot", 12 <= out_dur <= 45 or (brief.get("target_seconds") and abs(out_dur - float(brief["target_seconds"])) <= 5),
        1, f"length {out_dur:.1f}s is in the 12-45 s range (or within 5 s of the brief's target)",
        "Tighten: drop the weakest beat.")
    changes = sorted({0.0} | {s["off"] for s in shots} |
                     {s["off"] + s["dur"] / 2 for s in shots if abs(s["z1"] - s["z0"]) >= 0.05 and s["dur"] > 2.5})
    gaps = [b - a for a, b in zip(changes, changes[1:] + [out_dur])]
    longest = max(gaps) if gaps else out_dur
    add("pacing", longest <= 4.5, 2, f"the picture changes at least every 4.5 s (longest still stretch {longest:.1f}s)",
        "Split long shots, or give them a slow zoom or a punch-in halfway.")
    avg = out_dur / max(1, len(shots))
    add("cut_rate", avg <= 3.5, 1, f"average shot {avg:.1f}s (3.5 s or less keeps attention)",
        "Cut more often: one thought per shot.")
    dead = []
    spoken = sorted((c["start"], c["end"]) for c in cards)
    for (a1, b1), (a2, b2) in zip(spoken, spoken[1:]):
        if a2 - b1 > 0.8:
            dead.append(f"{a2 - b1:.1f}s at {tc(b1)}")
    if cards and out_dur - max(c["end"] for c in cards) > 1.2:
        dead.append(f"{out_dur - max(c['end'] for c in cards):.1f}s at the end")
    add("no_dead_air", not dead, 2, "no silence over 0.8 s inside the Reel" + (f" (found {', '.join(dead[:4])})" if dead else ""),
        "End those shots earlier or start the next one on its first word.")
    spec = caption_spec(plan)
    add("captions_on", spec["style"] == "none" or bool(cards), 3, "captions burned in (most people watch muted first)",
        "Set a caption style. There must be a transcript (Whisper) for word captions.")
    add("caption_size", spec["style"] == "none" or spec["size"] >= 64, 1, f"caption size {spec['size']}px is 64 or more",
        "Raise captions.size: 90-120 for bold styles, 70-80 for clean ones.")
    add("caption_words", spec["style"] == "none" or spec["max_words"] <= 5, 1,
        f"{spec['max_words']} words or fewer per caption card (5 max reads at a glance)",
        "Lower captions.max_words to 2-4 for bold styles.")
    clash = []
    for o in overlays:
        for c in cards:
            if c["hide"] or c["end"] <= o["start"] or c["start"] >= o["end"]:
                continue
            if abs(c["y"] - o["y"]) < 0.12 and not spec["hide_during_overlays"]:
                clash.append(f"{tc(max(c['start'], o['start']))}")
    add("no_clash", not clash, 2, "captions and on-screen text never sit on top of each other",
        "Move the caption (captions.overrides y) or the overlay, at " + ", ".join(clash[:4]))
    roles = [s["role"] for s in shots]
    tail = [s for s in shots if s["off"] >= out_dur * 0.6]
    add("payoff", any(r in ("payoff", "cta", "loop") for r in (s["role"] for s in tail)), 2,
        "a payoff, CTA or loop in the last 40%", "End on the answer, the punchline or one ask.")
    add("loop", bool(brief.get("loop")) or (roles and roles[-1] == "loop"), 1,
        "the ending leads back into the start (a loop)", "Write brief.loop: how the last line sets up the first.")
    add("one_ask", sum(1 for o in overlays if o["style"] == "cta") <= 1, 1, "one ask at most on screen",
        "Keep a single CTA.")
    music = (plan.get("sound") or {}).get("music") or {}
    add("music_safe", not music.get("file") or music.get("licensed"), 1,
        "no unlicensed music burned in (add trending audio inside Instagram instead)",
        "Remove sound.music.file, or set music.licensed true if you own the rights.")
    add("emoji", not any(EMOJI_RE.search(o["text"]) for o in overlays), 1,
        "no emoji in burned-in text (the renderer cannot draw colour emoji)",
        "Put emoji in the Instagram caption instead.")
    total = sum(i["weight"] for i in items)
    got = sum(i["weight"] for i in items if i["ok"])
    return {"score": round(100 * got / total) if total else 0, "items": items}


# ---------------------------------------------------------------- prepare (shared by storyboard + render)

def prepare(work, need_fonts=True):
    footage, plan = load(work)
    shots, out_dur, errors = resolve_shots(plan, footage)
    if not shots:
        errors.append("the plan has no usable shots")
    cards, spec = caption_cards(plan, footage, shots) if shots else ([], caption_spec(plan))
    overlays, ov_err = overlay_list(plan, out_dur)
    errors += ov_err
    if spec["hide_during_overlays"]:
        for c in cards:
            for o in overlays:
                if o["style"] in ("hook", "stat", "cta") and c["start"] < o["end"] and c["end"] > o["start"] \
                        and abs(c["y"] - o["y"]) < 0.15:
                    c["y"] = 0.72 if o["y"] < 0.5 else 0.3
    music = ((plan.get("sound") or {}).get("music") or {}).get("file")
    if music and not Path(music).expanduser().exists():
        errors.append(f"music file not found: {music}")
    if need_fonts and not available_fonts() and not os.environ.get("IG_DIRECT_NO_FETCH"):
        fetch_fonts(quiet=True)
        cards, spec = caption_cards(plan, footage, shots) if shots else ([], caption_spec(plan))
        overlays, _ = overlay_list(plan, out_dur)
    lint = checklist(plan, footage, shots, out_dur, cards, overlays) if shots else {"score": 0, "items": []}
    return {"footage": footage, "plan": plan, "shots": shots, "out_dur": out_dur, "cards": cards,
            "spec": spec, "overlays": overlays, "errors": errors, "lint": lint}


def timeline_text(p):
    """The output timeline: where every shot and every kept word lands in the Reel.
    Overlays, SFX hits and the cover are timed against this."""
    out = [f"# OUTPUT timeline of the Reel ({p['out_dur']:.2f}s). Times are seconds from the start of the Reel.",
           "# Use these for text_overlays start/end, sfx.at and cover.at.", "", "## shots"]
    for s in p["shots"]:
        z = f"zoom {s['z0']:.2f}" + (f"->{s['z1']:.2f}" if abs(s["z1"] - s["z0"]) > 0.001 else "")
        out.append(f"{s['id']:<5} {s['off']:6.2f}-{s['off'] + s['dur']:6.2f}  {s['role']:<7} {s['transition']:<6} {z}")
    out += ["", "## caption cards (as they will show)"]
    for c in p["cards"]:
        out.append(f"{c['start']:6.2f}-{c['end']:6.2f}  {c['shot']:<5} y={c['y']:.2f}  " + " ".join(w["text"] for w in c["words"]))
    out += ["", "## words: output time, word number, text"]
    for c in p["cards"]:
        for w in c["words"]:
            out.append(f"{w['start']:6.2f}  #{w['i']:<4} {w['text']}")
    if p["overlays"]:
        out += ["", "## on-screen text"]
        for o in p["overlays"]:
            out.append(f"{o['start']:6.2f}-{o['end']:6.2f}  {o['style']:<6} y={o['y']:.2f}  {o['text']}")
    return "\n".join(out) + "\n"


def ffmpeg_inputs(p):
    src = p["footage"]["source"]
    inputs = ["-i", src]
    extra = {}
    music = ((p["plan"].get("sound") or {}).get("music") or {}).get("file")
    if music:
        inputs += ["-stream_loop", "-1", "-i", str(Path(music).expanduser())]
        extra["music"] = 1
    return inputs, extra


def write_ass(p, work):
    path = work / "captions.ass"
    path.write_text(ass_document(p["cards"], p["spec"], p["overlays"]), encoding="utf-8")
    return path


# ---------------------------------------------------------------- storyboard

def storyboard_times(p):
    times = [(0.0, p["shots"][0]["id"] if p["shots"] else "", "first frame")]
    for s in p["shots"]:
        cs = [c for c in p["cards"] if c["shot"] == s["id"] and not c["hide"]]
        t = (cs[0]["start"] + min(cs[0]["end"], cs[0]["start"] + 0.5)) / 2 if cs else s["off"] + s["dur"] / 2
        t = min(max(t, s["off"] + 0.1), s["off"] + s["dur"] - 0.05)
        times.append((round(t, 3), s["id"], s["role"]))
    return times


def storyboard(work, preview=False):
    p = prepare(work)
    if p["errors"]:
        raise DirectError("fix the plan first:\n  - " + "\n  - ".join(p["errors"]))
    (work / "timeline.txt").write_text(timeline_text(p), encoding="utf-8")
    sb = work / "storyboard"
    if sb.exists():
        shutil.rmtree(sb)
    sb.mkdir()
    write_ass(p, work)
    inputs, extra = ffmpeg_inputs(p)
    graph = build_graph(p["plan"], p["footage"], p["shots"], p["out_dur"], "captions.ass",
                        FONTS_DIR if FONTS_DIR.exists() else None, extra)
    times = storyboard_times(p)
    frames = sorted({min(int(round(t * FPS)), int(p["out_dur"] * FPS) - 1) for t, _, _ in times})
    sel = "+".join(f"eq(n\\,{n})" for n in frames)
    graph = graph.replace("[vout]", "[vfull]", 1) + f";[vfull]select='{sel}',scale=720:1280[vsel];[aout]anullsink"
    r = run([ffmpeg(), "-hide_banner", "-nostdin", "-loglevel", "error", "-y", *inputs,
             "-filter_complex", graph, "-map", "[vsel]", "-fps_mode", "passthrough", "-q:v", "3",
             str(sb / "frame_%02d.jpg")], cwd=str(work))
    if r.returncode != 0:
        raise DirectError(f"storyboard render failed: {r.stderr.strip()[-600:]}")
    files = sorted(sb.glob("frame_*.jpg"))
    by_n = dict(zip(frames, files))
    panels = []
    for t, sid, role in times:
        n = min(int(round(t * FPS)), int(p["out_dur"] * FPS) - 1)
        f = by_n.get(n)
        s = next((x for x in p["shots"] if x["id"] == sid), None)
        said = " ".join(w["w"] for w in p["footage"]["words"]
                        if s and s["a"] <= (w["start"] + w["end"]) / 2 <= s["b"])
        panels.append({"t": t, "shot": sid, "role": role, "image": f"storyboard/{f.name}" if f else None,
                       "said": said if role != "first frame" else "",
                       "shot_info": s})
    preview_path = None
    if preview:
        preview_path = render(work, out=work / "preview.mp4", preview=True)["video"]
    data = {"made_at": dt.datetime.now().isoformat(timespec="seconds"), "length": p["out_dur"],
            "score": p["lint"]["score"], "checklist": p["lint"]["items"], "panels": panels,
            "preview": "preview.mp4" if preview_path else None}
    write_json(work / "storyboard.json", data)
    (work / "storyboard.html").write_text(storyboard_html(p, data), encoding="utf-8")
    (work / "storyboard.md").write_text(storyboard_md(p, data), encoding="utf-8")
    return data


def storyboard_md(p, data):
    b = p["plan"].get("brief") or {}
    look = p["plan"].get("look") or {}
    sound = p["plan"].get("sound") or {}
    L = [f"# Storyboard: {b.get('concept') or Path(p['footage']['source']).name}", "",
         f"- **Mood:** {b.get('mood', '-')}  ·  **Grade:** {look.get('grade', 'natural')}  ·  "
         f"**Length:** {p['out_dur']:.1f}s in {len(p['shots'])} shots",
         f"- **Hook:** {b.get('hook', '-')}", f"- **Loop:** {b.get('loop', '-')}",
         f"- **Captions:** {p['spec']['style']}, {p['spec']['font']} {p['spec']['size']}px, "
         f"{p['spec']['max_words']} words a card, highlight {p['spec']['highlight']}",
         f"- **Sound:** {sound.get('brief', '-')}", f"- **Checklist:** {data['score']}/100", ""]
    for it in data["checklist"]:
        L.append(f"  - {'✅' if it['ok'] else '❌'} {it['msg']}" + (f" → {it['fix']}" if it["fix"] else ""))
    L += ["", "| # | time | shot | role | said | frame |", "|---|---|---|---|---|---|"]
    for k, pn in enumerate(data["panels"]):
        s = pn["shot_info"] or {}
        extra = []
        if s.get("z1", 1) != s.get("z0", 1):
            extra.append(f"zoom {s['z0']:.2f}→{s['z1']:.2f}")
        if s.get("transition") not in (None, "cut"):
            extra.append(s["transition"])
        L.append(f"| {k} | {tc(pn['t'])} | {pn['shot']} {' '.join(extra)} | {pn['role']} | "
                 f"{(pn['said'] or '')[:80]} | {pn['image'] or '-'} |")
    return "\n".join(L) + "\n"


def storyboard_html(p, data):
    b = p["plan"].get("brief") or {}
    look = p["plan"].get("look") or {}
    sound = p["plan"].get("sound") or {}
    e = html.escape
    sugg = "".join(f"<li><b>{e(str(a.get('name', '')))}</b> {e(str(a.get('why', '')))}</li>"
                   for a in (sound.get("suggested_audio") or [])[:5] if isinstance(a, dict))
    checks = "".join(f"<li class='{'ok' if i['ok'] else 'no'}'>{'✓' if i['ok'] else '✗'} {e(i['msg'])}"
                     + (f"<br><small>{e(i['fix'])}</small>" if i["fix"] else "") + "</li>" for i in data["checklist"])
    panels = []
    for k, pn in enumerate(data["panels"]):
        s = pn["shot_info"] or {}
        tags = [pn["role"]]
        if s and abs(s["z1"] - s["z0"]) > 0.01:
            tags.append(f"zoom {s['z0']:.2f}→{s['z1']:.2f}")
        if s and s.get("transition") not in (None, "cut"):
            tags.append(s["transition"])
        img = f"<img src='{e(pn['image'])}' alt='frame at {tc(pn['t'])}'>" if pn["image"] else "<div class='noimg'></div>"
        panels.append(f"<figure>{img}<figcaption><b>{k}. {tc(pn['t'])}</b> · {e(pn['shot'])} · "
                      f"{e(', '.join(tags))}<br><span>{e(pn['said'][:140])}</span>"
                      + (f"<br><i>{e(s.get('note', ''))}</i>" if s and s.get("note") else "") + "</figcaption></figure>")
    prev = f"<video src='{e(data['preview'])}' controls playsinline></video>" if data.get("preview") else ""
    return f"""<!doctype html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Storyboard</title><style>
:root{{--bg:#0f0f12;--fg:#f2f2f4;--mut:#9a9aa6;--card:#1a1a20;--ok:#3ddc84;--no:#ff6b6b}}
@media (prefers-color-scheme: light){{:root{{--bg:#fafafa;--fg:#18181b;--mut:#6b6b76;--card:#fff}}}}
body{{margin:0;padding:16px;background:var(--bg);color:var(--fg);font:15px/1.45 -apple-system,system-ui,sans-serif}}
h1{{font-size:22px;margin:0 0 6px}} .meta{{color:var(--mut);margin-bottom:14px}}
.grid{{display:grid;grid-template-columns:repeat(auto-fill,minmax(170px,1fr));gap:12px}}
figure{{margin:0;background:var(--card);border-radius:12px;overflow:hidden}}
figure img,.noimg{{width:100%;aspect-ratio:9/16;object-fit:cover;display:block;background:#000}}
figcaption{{padding:8px 10px;font-size:13px}} figcaption span{{color:var(--mut)}}
.cols{{display:grid;grid-template-columns:repeat(auto-fit,minmax(260px,1fr));gap:12px;margin:12px 0}}
.box{{background:var(--card);border-radius:12px;padding:12px 14px}} ul{{margin:6px 0;padding-left:18px}}
li.ok{{color:var(--ok)}} li.no{{color:var(--no)}} li small{{color:var(--mut)}} video{{max-width:300px;border-radius:12px}}
</style></head><body>
<h1>{e(b.get('concept') or 'Storyboard')}</h1>
<div class="meta">{p['out_dur']:.1f}s · {len(p['shots'])} shots · mood {e(str(b.get('mood', '-')))} · grade {e(str(look.get('grade', 'natural')))} · checklist {data['score']}/100</div>
<div class="cols"><div class="box"><b>Hook</b><br>{e(str(b.get('hook', '-')))}<br><br><b>Loop</b><br>{e(str(b.get('loop', '-')))}</div>
<div class="box"><b>Sound</b><br>{e(str(sound.get('brief', '-')))}<ul>{sugg}</ul></div>
<div class="box"><b>Checklist</b><ul>{checks}</ul></div></div>
{prev}
<div class="grid">{''.join(panels)}</div>
</body></html>"""


# ---------------------------------------------------------------- render

def render(work, out=None, preview=False, preset="fast"):
    p = prepare(work)
    if p["errors"]:
        raise DirectError("fix the plan first:\n  - " + "\n  - ".join(p["errors"]))
    out = Path(out or work / "reel.mp4").resolve()
    write_ass(p, work)
    inputs, extra = ffmpeg_inputs(p)
    graph = build_graph(p["plan"], p["footage"], p["shots"], p["out_dur"], "captions.ass",
                        FONTS_DIR if FONTS_DIR.exists() else None, extra)
    vmap = "[vout]"
    if preview:
        graph = graph.replace("[vout]", "[vfull]", 1) + ";[vfull]scale=540:960[vprev]"
        vmap = "[vprev]"
    enc = (["-c:v", "libx264", "-preset", "ultrafast", "-crf", "30"] if preview else
           ["-c:v", "libx264", "-preset", preset, "-profile:v", "high", "-level:v", "4.1",
            "-b:v", edit.VIDEO_BITRATE, "-maxrate", edit.VIDEO_MAX, "-bufsize", edit.VIDEO_BUF])
    cmd = [ffmpeg(), "-hide_banner", "-nostdin", "-loglevel", "error", "-y", *inputs,
           "-filter_complex", graph, "-map", vmap, "-map", "[aout]", *enc,
           "-pix_fmt", "yuv420p", "-r", str(FPS), "-g", str(FPS * 2),
           "-c:a", "aac", "-b:a", edit.AUDIO_BITRATE, "-ar", "48000", "-ac", "2",
           "-t", f"{p['out_dur']:.3f}", "-movflags", "+faststart", str(out)]
    r = run(cmd, cwd=str(work))
    if r.returncode != 0:
        raise DirectError(f"render failed: {r.stderr.strip()[-800:]}")
    report = {"video": str(out), "length": p["out_dur"], "shots": len(p["shots"]), "captions": len(p["cards"]),
              "overlays": len(p["overlays"]), "score": p["lint"]["score"],
              "failed_checks": [i["msg"] for i in p["lint"]["items"] if not i["ok"]],
              "font": p["spec"]["font"], "grade": (p["plan"].get("look") or {}).get("grade", "natural"),
              "preview": preview}
    if not preview:
        chk = work / "check"
        chk.mkdir(exist_ok=True)
        times = [0.1] + [round(s["off"] + s["dur"] / 2, 2) for s in p["shots"][1::max(1, len(p["shots"]) // 3)]][:3]
        try:
            report["checks"] = [str(x) for x in cover.check_frames(out, times, chk)]
        except Exception as ex:  # noqa: BLE001
            report["checks_error"] = str(ex)
        c = p["plan"].get("cover") or {}
        if c.get("at") is not None:
            cp = out.with_name(out.stem + "-cover.jpg")
            try:
                cover.make_cover(out, num(c.get("at"), 0, p["out_dur"], 1.0), cp)
                report["cover"] = str(cp)
            except Exception as ex:  # noqa: BLE001
                report["cover_error"] = str(ex)
        write_json(work / "render-report.json", report)
    return report


# ---------------------------------------------------------------- CLI

def default_work(src):
    stem = re.sub(r"[^A-Za-z0-9._-]+", "-", Path(src).stem).strip("-")[:40] or "reel"
    return edit.data_dir() / "edits" / f"{stem}-direct-{stamp()}"


def print_check(p, out):
    lint = p["lint"]
    print(f"CHECKLIST  {lint['score']}/100  ·  {p['out_dur']:.1f}s, {len(p['shots'])} shots, "
          f"{len(p['cards'])} caption cards, {len(p['overlays'])} overlays", file=out)
    for i in lint["items"]:
        print(f"  {'✓' if i['ok'] else '✗'} {i['msg']}" + (f"\n      fix: {i['fix']}" if i["fix"] else ""), file=out)
    for e in p["errors"]:
        print(f"  ERROR {e}", file=out)


def main(argv=None, out=sys.stdout):
    ap = argparse.ArgumentParser(description="Claude directs, ffmpeg renders. See SKILL.md.")
    sub = ap.add_subparsers(dest="cmd", required=True)
    a = sub.add_parser("analyze")
    a.add_argument("video")
    a.add_argument("--dir")
    a.add_argument("--lang", default="auto")
    a.add_argument("--every", type=float)
    a.add_argument("--no-transcribe", action="store_true")
    for name in ("merge", "check", "storyboard", "render"):
        s = sub.add_parser(name)
        s.add_argument("dir")
        if name == "storyboard":
            s.add_argument("--preview", action="store_true")
        if name == "render":
            s.add_argument("--out")
            s.add_argument("--preset", default="fast",
                           choices=("ultrafast", "superfast", "veryfast", "faster", "fast", "medium", "slow"))
    sub.add_parser("fonts")
    for s in sub.choices.values():
        s.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)
    try:
        if args.cmd == "fonts":
            got = fetch_fonts()
            res = {"fonts_dir": str(FONTS_DIR), "fonts": sorted(got)}
        elif args.cmd == "analyze":
            work = Path(args.dir).expanduser() if args.dir else default_work(args.video)
            f = analyze(args.video, work, args.lang, args.every, args.no_transcribe)
            if not os.environ.get("IG_DIRECT_NO_FETCH"):
                fetch_fonts(quiet=True)
            res = {"dir": str(work), "duration": f["info"]["duration"], "words": len(f["words"]),
                   "lines": len(f["lines"]), "transcriber": f["transcriber"], "sheets": [s["path"] for s in f["sheets"]],
                   "transcript": str(work / "transcript.txt"), "notes": f["notes"]}
        else:
            work = Path(args.dir).expanduser().resolve()
            if args.cmd == "merge":
                merge(work)
                p = prepare(work, need_fonts=False)
                if p["shots"]:
                    (work / "timeline.txt").write_text(timeline_text(p), encoding="utf-8")
                res = {"plan": str(work / "plan.json"), "errors": p["errors"], "score": p["lint"]["score"],
                       "length": p["out_dur"], "failed": [i for i in p["lint"]["items"] if not i["ok"]]}
            elif args.cmd == "check":
                p = prepare(work, need_fonts=False)
                if not args.json:
                    print_check(p, out)
                    return 1 if p["errors"] else 0
                res = {"score": p["lint"]["score"], "items": p["lint"]["items"], "errors": p["errors"],
                       "length": p["out_dur"]}
            elif args.cmd == "storyboard":
                d = storyboard(work, args.preview)
                res = {"html": str(work / "storyboard.html"), "md": str(work / "storyboard.md"),
                       "frames": [str(work / x["image"]) for x in d["panels"] if x["image"]],
                       "score": d["score"], "preview": str(work / d["preview"]) if d["preview"] else None}
            else:
                res = render(work, args.out, preset=args.preset)
    except (DirectError, edit.EditError) as e:
        if getattr(args, "json", False):
            print(json.dumps({"error": str(e)}), file=out)
        else:
            print(f"error: {e}", file=sys.stderr)
        return 1
    if args.json:
        print(json.dumps(res, ensure_ascii=False), file=out)
    else:
        for k, v in res.items():
            print(f"{k:>12}  {v}", file=out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
