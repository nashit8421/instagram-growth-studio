#!/usr/bin/env python3
"""
audio.py - which sound to put on a Reel, from a list you keep of what is
trending, what your account can actually use, and what fits the reel.

Audio is one factor in reach, not the factor. A trending sound on a reel
nobody finishes does nothing. This ranks your options honestly and tells you
how to use the winner. It never promises a result.

The list is a plain CSV at $DATA/sounds.csv. $DATA is $IG_DATA_DIR if set,
else the active account folder under $IG_HOME (default ~/.claude/instagram),
else $IG_HOME itself. Empty cell means unknown.

Usage
  python3 audio.py add --name "Espresso" --artist "Sabrina Carpenter" \\
      --source instagram --region IN --reels-count 12K --trend rising \\
      --bpm 104 --mood upbeat --business-ok no
  python3 audio.py suggest --reel-length 28 --mood upbeat --account creator
  python3 audio.py suggest --reel-length 28 --voiceover yes --script script.txt
  python3 audio.py list [--region IN] [--json]
  python3 audio.py prune --older-than 28 [--dry-run]

Music is added inside the Instagram app when posting. This tool never
downloads, rips or stores audio.
"""

import argparse
import csv
import datetime as dt
import importlib.util
import json
import os
import re
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))

COLUMNS = [
    "name", "artist", "source", "region", "reels_count", "first_seen",
    "last_seen", "trend", "bpm", "mood", "business_ok", "url", "notes",
    # Two extra columns at the end so growth survives between sightings.
    # The previous reels_count and the date it was seen.
    "prev_reels_count", "prev_seen",
]
SOURCES = ("instagram", "tiktok", "other")
TRENDS = ("rising", "peaking", "fading")
MOODS = ("upbeat", "calm", "dramatic", "funny", "emotional", "lofi")
BUSINESS_OK = ("yes", "no", "unknown")

# ------------------------------------------------------- rules of thumb
# None of these numbers come from Instagram. They are working rules of thumb.
# Change them when your own ledger tells you something different.

# Instagram sound page reel counts. Under IG_UNPROVEN nobody has shown the
# sound works. Between IG_SWEET_LOW and IG_SWEET_HIGH it has proof and room
# left. Past IG_SATURATED you are one of a very large crowd.
IG_UNPROVEN = 300
IG_SWEET_LOW = 1_000
IG_SWEET_HIGH = 50_000
IG_SATURATED = 200_000

# TikTok counts run roughly an order of magnitude bigger for the same stage.
TT_UNPROVEN = 3_000
TT_SWEET_LOW = 10_000
TT_SWEET_HIGH = 500_000
TT_SATURATED = 2_000_000

# Growth per day between two sightings, compounded.
GROWTH_HOT = 0.10        # 10%+ a day: catching fire
GROWTH_WARM = 0.03       # 3%+ a day: still climbing
# When --trend is not given on a re-add, growth sets it.
INFER_RISING = 0.05
INFER_FADING = 0.0

# Freshness, by days since the sound was first seen trending.
FRESH_FULL_DAYS = 7      # full marks for the first week
FRESH_HALF_DAYS = 21     # down to half by about three weeks
FRESH_HALVING_DAYS = 7   # then halves again every week
STALE_SIGHTING_DAYS = 7  # last_seen older than this: re-check before using

# Account eligibility multipliers.
ELIG_UNKNOWN_BUSINESS = 0.7   # business account, business_ok unknown
OTHER_REGION = 0.8            # sound seen trending in a different region

# Cut pace from beat length (seconds per beat-sheet beat).
FAST_CUTS = 2.0          # beats shorter than this are fast cutting
SLOW_CUTS = 3.5          # beats longer than this are slow
# Song tempo bands.
SLOW_BPM = 90
FAST_BPM = 120
# Cutting every 2, 4, 8 or 16 musical beats sits on the song's grid in 4/4.
GRID = (2, 4, 8, 16)

# Background music under a voice.
VOICEOVER_VOLUME = "10-20%"

WEIGHTS = {"momentum": 0.40, "freshness": 0.20, "mood": 0.20, "bpm": 0.20}

TREND_SCORE = {"rising": 1.0, "peaking": 0.6, "fading": 0.15, "": 0.4}
MOOD_NEIGHBOURS = {
    "upbeat": {"funny"},
    "funny": {"upbeat"},
    "calm": {"lofi", "emotional"},
    "lofi": {"calm"},
    "dramatic": {"emotional"},
    "emotional": {"dramatic", "calm"},
}

DEFAULT_WPM = 165


# ---------------------------------------------------------------- storage

def ig_home():
    return os.path.expanduser(os.environ.get("IG_HOME") or "~/.claude/instagram")


def data_dir():
    """$IG_DATA_DIR, else $IG_HOME/accounts/<active handle>/, else $IG_HOME."""
    env = os.environ.get("IG_DATA_DIR")
    if env:
        return os.path.expanduser(env)
    home = ig_home()
    marker = os.path.join(home, "active-account")
    if os.path.isfile(marker):
        with open(marker, encoding="utf-8") as f:
            handle = f.read().strip().lstrip("@")
        if handle:
            acct = os.path.join(home, "accounts", handle)
            if os.path.isdir(acct):
                return acct
    return home


def sounds_path():
    return os.path.join(data_dir(), "sounds.csv")


def load_rows():
    path = sounds_path()
    if not os.path.exists(path):
        return []
    with open(path, encoding="utf-8-sig", newline="") as f:
        return [{c: (raw.get(c) or "").strip() for c in COLUMNS}
                for raw in csv.DictReader(f)]


def save_rows(rows):
    """Atomic write: temp file in the same folder, then os.replace."""
    path = sounds_path()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=".sounds.", suffix=".csv",
                               dir=os.path.dirname(path))
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="") as f:
            w = csv.DictWriter(f, fieldnames=COLUMNS, extrasaction="ignore")
            w.writeheader()
            for r in rows:
                w.writerow({c: "" if r.get(c) is None else str(r.get(c)) for c in COLUMNS})
        os.replace(tmp, path)
    except BaseException:
        if os.path.exists(tmp):
            os.unlink(tmp)
        raise


# ---------------------------------------------------------------- values

def parse_count(v):
    """'12,400' -> 12400, '1.2K' -> 1200, '3M' -> 3000000, '' -> None."""
    if v is None:
        return None
    s = str(v).strip().replace(",", "").replace(" ", "")
    if not s or s in ("-", "--"):
        return None
    mult = 1
    if s[-1:] in ("K", "k"):
        mult, s = 1_000, s[:-1]
    elif s[-1:] in ("M", "m"):
        mult, s = 1_000_000, s[:-1]
    try:
        n = float(s) * mult
    except ValueError:
        raise ValueError(f"not a count: {v!r}")
    if n < 0:
        raise ValueError(f"count cannot be negative: {v!r}")
    return int(round(n))


def parse_date(s):
    if not s:
        return None
    try:
        return dt.date.fromisoformat(str(s)[:10])
    except ValueError:
        return None


def num(s):
    try:
        return float(s)
    except (TypeError, ValueError):
        return None


def key(name, artist):
    norm = lambda s: re.sub(r"\s+", " ", (s or "").strip().lower())
    return (norm(name), norm(artist))


def fmt_count(n):
    return "?" if n is None else f"{int(n):,}"


def daily_growth(prev, now, days):
    """Compounded growth per day between two sightings, or None."""
    if prev is None or now is None or days is None or days <= 0 or prev <= 0:
        return None
    if now <= 0:
        return -1.0
    return (now / prev) ** (1.0 / days) - 1.0


def row_growth(r):
    prev = parse_count(r.get("prev_reels_count"))
    now = parse_count(r.get("reels_count"))
    a, b = parse_date(r.get("prev_seen")), parse_date(r.get("last_seen"))
    days = (b - a).days if a and b else None
    return daily_growth(prev, now, days), prev, now, days


# ---------------------------------------------------------------- add

def upsert(rows, fields, today):
    """Insert or update by name+artist. Returns (row, created, growth_info)."""
    k = key(fields["name"], fields.get("artist"))
    existing = next((r for r in rows if key(r["name"], r["artist"]) == k), None)
    seen = fields.get("seen") or today.isoformat()
    new_count = fields.get("reels_count")

    if existing is None:
        row = {c: "" for c in COLUMNS}
        row.update({
            "name": fields["name"].strip(),
            "artist": (fields.get("artist") or "").strip(),
            "first_seen": seen, "last_seen": seen,
            "business_ok": "unknown",
        })
        created = True
        rows.append(row)
    else:
        row, created = existing, False

    info = None
    if not created and new_count is not None:
        old_count = parse_count(row["reels_count"])
        old_seen = parse_date(row["last_seen"])
        if old_count is not None and old_seen is not None:
            days = (parse_date(seen) - old_seen).days
            if days > 0:
                row["prev_reels_count"] = str(old_count)
                row["prev_seen"] = old_seen.isoformat()
            g = daily_growth(old_count, new_count, days)
            info = {"from": old_count, "to": new_count, "days": days,
                    "daily": g,
                    "total": (new_count / old_count - 1.0) if old_count else None}

    for f in ("source", "region", "trend", "mood", "business_ok", "url", "notes"):
        if fields.get(f):
            row[f] = fields[f].strip()
    if fields.get("region"):
        row["region"] = fields["region"].strip().upper()
    if fields.get("bpm") is not None:
        row["bpm"] = str(int(round(fields["bpm"])))
    if new_count is not None:
        row["reels_count"] = str(new_count)
    if not created:
        last = parse_date(row["last_seen"])
        if last is None or parse_date(seen) >= last:
            row["last_seen"] = seen
        first = parse_date(row["first_seen"])
        if first is None or parse_date(seen) < first:
            row["first_seen"] = seen

    # Growth sets the trend when the user did not.
    if info and info["daily"] is not None and not fields.get("trend"):
        if info["daily"] >= INFER_RISING:
            row["trend"] = "rising"
        elif info["daily"] <= INFER_FADING:
            row["trend"] = "fading"
        else:
            row["trend"] = "peaking"
        info["inferred_trend"] = row["trend"]
    return row, created, info


def cmd_add(args, out):
    today = args.today
    try:
        count = parse_count(args.reels_count)
    except ValueError as e:
        print(f"error: {e}", file=sys.stderr)
        return 2
    if args.seen and parse_date(args.seen) is None:
        print(f"error: --seen must be YYYY-MM-DD, got {args.seen!r}", file=sys.stderr)
        return 2
    rows = load_rows()
    row, created, info = upsert(rows, {
        "name": args.name, "artist": args.artist, "source": args.source,
        "region": args.region, "reels_count": count, "trend": args.trend,
        "bpm": args.bpm, "mood": args.mood, "business_ok": args.business_ok,
        "url": args.url, "notes": args.notes, "seen": args.seen,
    }, today)
    save_rows(rows)
    who = f"{row['name']}" + (f" - {row['artist']}" if row["artist"] else "")
    print(f"{'added' if created else 'updated'}: {who}", file=out)
    if info:
        line = f"  reels {fmt_count(info['from'])} -> {fmt_count(info['to'])}"
        if info["days"] > 0 and info["daily"] is not None:
            line += (f" in {info['days']} days ({info['total'] * 100:+.0f}%, "
                     f"about {info['daily'] * 100:+.1f}% a day)")
        elif info["days"] <= 0:
            line += " (same day, no growth rate)"
        print(line, file=out)
        if info.get("inferred_trend"):
            print(f"  trend set to {info['inferred_trend']} from growth. "
                  "Pass --trend to override.", file=out)
    print(f"  saved to {sounds_path()}", file=out)
    return 0


# ---------------------------------------------------------------- scoring

def count_fit(source, count):
    """0..1 for where the reel count sits on the proof vs saturation curve."""
    if count is None or source not in ("instagram", "tiktok"):
        return 0.5, "no reel count"
    lo_p, lo, hi, sat = ((IG_UNPROVEN, IG_SWEET_LOW, IG_SWEET_HIGH, IG_SATURATED)
                         if source == "instagram" else
                         (TT_UNPROVEN, TT_SWEET_LOW, TT_SWEET_HIGH, TT_SATURATED))
    unit = "reels" if source == "instagram" else "TikTok videos"
    if count < lo_p:
        return 0.3, f"only {fmt_count(count)} {unit}, unproven"
    if count < lo:
        return 0.6, f"{fmt_count(count)} {unit}, early"
    if count <= hi:
        return 1.0, f"{fmt_count(count)} {unit}, proven and not crowded"
    if count <= sat:
        return 0.6, f"{fmt_count(count)} {unit}, getting crowded"
    return 0.3, f"{fmt_count(count)} {unit}, saturated"


def growth_fit(g):
    if g is None:
        return 0.5, None
    if g >= GROWTH_HOT:
        return 1.0, f"growing {g * 100:.0f}% a day"
    if g >= GROWTH_WARM:
        return 0.7, f"growing {g * 100:.1f}% a day"
    if g > 0:
        return 0.45, f"growing slowly ({g * 100:.1f}% a day)"
    return 0.1, f"flat or shrinking ({g * 100:.1f}% a day)"


def freshness(r, today):
    """0..1 from age since first seen. Also returns a staleness warning."""
    first = parse_date(r["first_seen"]) or parse_date(r["last_seen"])
    if first is None:
        return 0.5, None, None
    age = max(0, (today - first).days)
    if age <= FRESH_FULL_DAYS:
        f = 1.0
    elif age <= FRESH_HALF_DAYS:
        f = 1.0 - 0.5 * (age - FRESH_FULL_DAYS) / (FRESH_HALF_DAYS - FRESH_FULL_DAYS)
    else:
        f = 0.5 * 0.5 ** ((age - FRESH_HALF_DAYS) / FRESH_HALVING_DAYS)
    last = parse_date(r["last_seen"])
    stale = None
    if last and (today - last).days > STALE_SIGHTING_DAYS:
        stale = (f"last checked {(today - last).days} days ago. "
                 "Open its sound page and check it is still moving")
    return f, age, stale


def mood_fit(want, have):
    if not want:
        return 0.5
    if not have:
        return 0.5
    if want == have:
        return 1.0
    if have in MOOD_NEIGHBOURS.get(want, set()):
        return 0.6
    return 0.2


def pace_band(beat_s):
    if beat_s < FAST_CUTS:
        return "fast"
    if beat_s > SLOW_CUTS:
        return "slow"
    return "medium"


def bpm_band(bpm):
    if bpm < SLOW_BPM:
        return "slow"
    if bpm > FAST_BPM:
        return "fast"
    return "medium"


def grid_fit(beat_s, bpm):
    """How close one script beat sits to 2, 4, 8 or 16 beats of the song.

    Returns (score 0..1, nearest grid k, musical beats per script beat)."""
    n = beat_s * bpm / 60.0
    k = min(GRID, key=lambda g: abs(n - g))
    err = abs(n - k) / k
    # Halfway between two grid points the error is a half, which scores 0.
    return max(0.0, 1.0 - 2.0 * err), k, n


def bpm_fit(bpm, beat_s, from_script):
    if bpm is None or bpm <= 0:
        return 0.5, None
    order = ["slow", "medium", "fast"]
    gap = abs(order.index(pace_band(beat_s)) - order.index(bpm_band(bpm)))
    pace = (1.0, 0.6, 0.2)[gap]
    if not from_script:
        return pace, None
    g, k, n = grid_fit(beat_s, bpm)
    lo = max([x for x in GRID if x <= n] or [GRID[0]])
    hi = min([x for x in GRID if x >= n] or [GRID[-1]])
    return 0.5 * pace + 0.5 * g, {"grid": k, "per_beat": round(n, 2),
                                  "cut_every_s": round(k * 60.0 / bpm, 2),
                                  "beat_s": round(beat_s, 2),
                                  "lo": lo, "lo_s": round(lo * 60.0 / bpm, 2),
                                  "hi": hi, "hi_s": round(hi * 60.0 / bpm, 2)}


# ---------------------------------------------------------------- script

BEATS_DIRS = [
    os.path.join(HERE, "..", "ig-reel"),
    os.path.expanduser("~/.claude/skills/ig-reel"),
]


def load_beats():
    """ig-reel's beats.py if it can be found, else None."""
    for d in BEATS_DIRS:
        p = os.path.join(d, "beats.py")
        if os.path.isfile(p):
            spec = importlib.util.spec_from_file_location("_igreel_beats", p)
            mod = importlib.util.module_from_spec(spec)
            try:
                spec.loader.exec_module(mod)
                return mod
            except Exception:
                continue
    return None


def analyse_script(text, target=None):
    """Beat timings for a script. Uses beats.py, or a plain word-count
    fallback (one line is one beat at 165 wpm) when it is not installed."""
    mod = load_beats()
    if mod is not None:
        a = mod.analyse(text, wpm=DEFAULT_WPM, target=target)
        if a:
            a["engine"] = "beats.py"
            return a
        return None
    wps = DEFAULT_WPM / 60.0
    rows, clock = [], 0.0
    for line in (l.strip() for l in text.splitlines()):
        if not line:
            continue
        n = len(re.findall(r"\w+", line))
        dur = n / wps
        rows.append({"n": len(rows) + 1, "start": round(clock, 2),
                     "dur": round(dur, 2), "text": line, "label": ""})
        clock += dur
    if not rows:
        return None
    rows[0]["label"] = "HOOK"
    rows[-1]["label"] = "CTA" if len(rows) > 1 else "HOOK/CTA"
    return {"engine": "fallback", "total_seconds": round(clock, 2), "beats": rows}


def script_shape(a):
    """Mean beat length, and where the hook ends and the payoff starts."""
    beats = a["beats"]
    mean = sum(b["dur"] for b in beats) / len(beats)
    hook_end = max((b["start"] + b["dur"] for b in beats
                    if "HOOK" in (b.get("label") or "")), default=beats[0]["dur"])
    payoff = beats[-2] if len(beats) >= 3 else beats[-1]
    return {"mean_beat_s": mean, "hook_end_s": hook_end,
            "payoff_start_s": payoff["start"], "payoff_beat": payoff["n"],
            "total_s": a["total_seconds"], "beats": len(beats),
            "engine": a.get("engine")}


# ---------------------------------------------------------------- suggest

def rank(rows, today, reel_length, mood=None, account="creator", region=None,
         shape=None):
    """Score every sound. Returns (ranked list, excluded list)."""
    beat_s = shape["mean_beat_s"] if shape else (
        1.8 if reel_length and reel_length <= 15 else 3.0)
    ranked, excluded = [], []
    for r in rows:
        name = r["name"] + (f" - {r['artist']}" if r["artist"] else "")
        biz = (r["business_ok"] or "unknown").lower()
        if account == "business" and biz == "no":
            excluded.append({"name": name, "why": "not cleared for business accounts"})
            continue

        trend = (r["trend"] or "").lower()
        t = TREND_SCORE.get(trend, TREND_SCORE[""])
        c, c_why = count_fit(r["source"], parse_count(r["reels_count"]))
        g_rate, *_ = row_growth(r)
        g, g_why = growth_fit(g_rate)
        momentum = 0.45 * t + 0.30 * c + 0.25 * g

        fresh, age, stale = freshness(r, today)
        m = mood_fit(mood, (r["mood"] or "").lower())
        b, grid = bpm_fit(num(r["bpm"]), beat_s, shape is not None)

        mult, flags = 1.0, []
        if account == "business" and biz == "unknown":
            mult *= ELIG_UNKNOWN_BUSINESS
            flags.append("business use unknown. Search it in your audio picker; "
                         "if it does not show up, you cannot use it")
        if region and r["region"] and r["region"].upper() != region.upper():
            mult *= OTHER_REGION
            flags.append(f"trending in {r['region']}, not {region.upper()}")
        if stale:
            flags.append(stale)
        if r["source"] == "tiktok":
            flags.append("seen on TikTok. Check it is in your Instagram picker first")

        score = 100.0 * mult * (WEIGHTS["momentum"] * momentum
                                + WEIGHTS["freshness"] * fresh
                                + WEIGHTS["mood"] * m
                                + WEIGHTS["bpm"] * b)
        why = []
        if trend:
            why.append(trend)
        why.append(c_why)
        if g_why:
            why.append(g_why)
        if age is not None:
            why.append(f"first seen {age} day{'s' if age != 1 else ''} ago")
        if mood and r["mood"]:
            why.append(f"mood {r['mood']}" + (" matches" if m == 1.0 else
                                               " is close" if m >= 0.6 else
                                               f" vs {mood} wanted"))
        if num(r["bpm"]):
            why.append(f"{int(num(r['bpm']))} bpm vs {pace_band(beat_s)} cuts")
        ranked.append({
            "name": name, "row": r, "score": round(score, 1),
            "parts": {"momentum": round(momentum, 3), "freshness": round(fresh, 3),
                      "mood": round(m, 3), "bpm": round(b, 3),
                      "eligibility": round(mult, 3)},
            "why": why, "flags": flags, "grid": grid,
        })
    ranked.sort(key=lambda x: (-x["score"], x["name"].lower()))
    return ranked, excluded


def tc(seconds):
    m, s = divmod(max(0.0, seconds), 60)
    return f"{int(m)}:{int(round(s)):02d}"


def how_to_use(pick, shape, voiceover, reel_length):
    lines = []
    if shape:
        lines.append(f"Land the drop on the payoff, beat {shape['payoff_beat']} at about "
                     f"{tc(shape['payoff_start_s'])}. Slide the clip in the picker "
                     "until it hits there.")
        lines.append(f"Keep the drop away from the hook (0:00-{tc(shape['hook_end_s'])}). "
                     "The hook has to read on frame 1 without help.")
    else:
        payoff = max(0.0, (reel_length or 30) - 3)
        lines.append(f"Land the drop on the payoff or the reveal, around {tc(payoff)}, "
                     "not on the hook. Slide the clip in the picker until it does.")
    if pick.get("grid"):
        gd = pick["grid"]
        if gd["lo"] == gd["hi"]:
            lines.append(f"Your beats average {gd['beat_s']:.1f}s. That is "
                         f"{gd['lo']} beats of this song, so cuts already sit on the music.")
        else:
            lines.append(f"Your beats average {gd['beat_s']:.1f}s. On this song, "
                         f"{gd['lo']} beats is {gd['lo_s']:.1f}s and {gd['hi']} beats is "
                         f"{gd['hi_s']:.1f}s. Trim or hold shots toward {gd['grid']} beats "
                         f"({gd['cut_every_s']:.1f}s) so cuts land on the music.")
    if voiceover:
        lines.append(f"Volume: music at {VOICEOVER_VOLUME}, voice at 100%. "
                     "The voice is the content. If you have to strain to hear a word, "
                     "the music is too loud.")
    else:
        lines.append("Volume: music at full. Use the part of the song everyone uses; "
                     "the picker usually suggests it.")
    return lines


def cmd_suggest(args, out):
    today = args.today
    rows = load_rows()
    voiceover = args.voiceover == "yes"
    shape = None
    if args.script:
        try:
            with open(args.script, encoding="utf-8") as f:
                text = f.read()
        except OSError as e:
            print(f"error: cannot read script: {e}", file=sys.stderr)
            return 2
        a = analyse_script(text, target=args.reel_length)
        if a is None:
            print("error: script is empty", file=sys.stderr)
            return 2
        shape = script_shape(a)

    ranked, excluded = rank(rows, today, args.reel_length, mood=args.mood,
                            account=args.account, region=args.region,
                            shape=shape)
    top = ranked[:args.top]
    for p in top:
        p["how"] = how_to_use(p, shape, voiceover, args.reel_length)

    original = None
    if voiceover:
        original = ("Your voice is the content, so original audio is a real option. "
                    "Post with your voice as the sound and rename it in the app before "
                    "posting. When other people use your sound, their reels sit on your "
                    "sound page under your name. You can still add a trending track under "
                    f"your voice at {VOICEOVER_VOLUME}; check the audio label on the "
                    "preview to see whose sound page the reel joins.")

    licence = ("Add the sound inside Instagram when you post, from the audio picker. "
               "That keeps it licensed and puts your reel on the sound's page. Never "
               "add it in an outside editor or download it.")
    honesty = ("Audio is one factor. The hook, the first two seconds and watch time "
               "decide more. A good pick helps; it does not make a reel go viral.")

    if args.json:
        res = {
            "today": today.isoformat(), "account": args.account,
            "reel_length": args.reel_length, "mood": args.mood,
            "voiceover": voiceover, "region": args.region,
            "script": shape, "total_sounds": len(rows),
            "picks": [{"name": p["name"], "score": p["score"], "parts": p["parts"],
                       "why": p["why"], "flags": p["flags"], "how": p["how"],
                       "grid": p["grid"], "url": p["row"]["url"],
                       "source": p["row"]["source"], "region": p["row"]["region"]}
                      for p in top],
            "excluded": excluded, "original_audio": original,
            "licence": licence, "honesty": honesty,
        }
        print(json.dumps(res, indent=2, ensure_ascii=False), file=out)
        return 0

    head = (f"AUDIO PICKS  ·  {args.reel_length:g}s reel  ·  {args.account} account"
            + (f"  ·  mood {args.mood}" if args.mood else "")
            + ("  ·  voiceover" if voiceover else ""))
    print("\n" + head, file=out)
    print("=" * 72, file=out)
    if not rows:
        print("No sounds saved yet. Add what is trending first:\n"
              "  python3 audio.py add --name \"...\" --source instagram --region IN "
              "--reels-count 8K --trend rising", file=out)
    if shape:
        print(f"script: {shape['beats']} beats, ~{shape['total_s']:.1f}s, "
              f"{shape['mean_beat_s']:.1f}s a beat ({pace_band(shape['mean_beat_s'])} "
              f"cuts, timed with {shape['engine']})", file=out)
    if excluded:
        print(f"left out {len(excluded)} not cleared for business accounts: "
              + ", ".join(e["name"] for e in excluded), file=out)
    if rows and not top:
        print("Nothing on the list is usable for this account.", file=out)
    for i, p in enumerate(top, 1):
        print(f"\n{i}. {p['name']}   score {p['score']:.0f}", file=out)
        print(f"   why:  {'; '.join(p['why'])}", file=out)
        for fl in p["flags"]:
            print(f"   ! {fl}", file=out)
        for h in p["how"]:
            print(f"   - {h}", file=out)
        if p["row"]["url"]:
            print(f"   sound page: {p['row']['url']}", file=out)
    if original:
        print(f"\nORIGINAL AUDIO\n   {original}", file=out)
    print("\n" + licence, file=out)
    print(honesty, file=out)
    print("", file=out)
    return 0


# ---------------------------------------------------------------- list, prune

def cmd_list(args, out):
    rows = load_rows()
    if args.region:
        rows = [r for r in rows if r["region"].upper() == args.region.upper()]
    if args.trend:
        rows = [r for r in rows if r["trend"] == args.trend]
    rows.sort(key=lambda r: (r["last_seen"], r["name"].lower()), reverse=True)
    if args.json:
        out_rows = []
        for r in rows:
            g, *_ = row_growth(r)
            d = dict(r)
            d["daily_growth"] = None if g is None else round(g, 4)
            out_rows.append(d)
        print(json.dumps(out_rows, indent=2, ensure_ascii=False), file=out)
        return 0
    if not rows:
        print("No sounds saved.", file=out)
        return 0
    print(f"{'name':<34} {'src':<9} {'reg':<4} {'reels':>10} {'trend':<8} "
          f"{'bpm':>4} {'mood':<9} {'biz':<7} last seen", file=out)
    for r in rows:
        who = r["name"] + (f" - {r['artist']}" if r["artist"] else "")
        print(f"{who[:34]:<34} {r['source']:<9} {r['region']:<4} "
              f"{fmt_count(parse_count(r['reels_count'])):>10} {r['trend']:<8} "
              f"{r['bpm']:>4} {r['mood']:<9} {r['business_ok']:<7} {r['last_seen']}",
              file=out)
    print(f"\n{len(rows)} sound{'s' if len(rows) != 1 else ''}  ·  {sounds_path()}",
          file=out)
    return 0


def cmd_prune(args, out):
    rows = load_rows()
    cutoff = args.today - dt.timedelta(days=args.older_than)
    keep, drop = [], []
    for r in rows:
        last = parse_date(r["last_seen"]) or parse_date(r["first_seen"])
        (drop if last is not None and last < cutoff else keep).append(r)
    for r in drop:
        print(f"  {'would drop' if args.dry_run else 'dropped'}: {r['name']}"
              + (f" - {r['artist']}" if r["artist"] else "")
              + f" (last seen {r['last_seen']})", file=out)
    if not args.dry_run and drop:
        save_rows(keep)
    print(f"{len(drop)} {'would be ' if args.dry_run else ''}pruned, "
          f"{len(keep)} kept (cutoff {cutoff.isoformat()})", file=out)
    return 0


# ---------------------------------------------------------------- cli

def _today(s):
    d = parse_date(s)
    if d is None:
        raise argparse.ArgumentTypeError("use YYYY-MM-DD")
    return d


def _bpm(s):
    v = num(s)
    if v is None or not 30 <= v <= 300:
        raise argparse.ArgumentTypeError("bpm should be a number between 30 and 300")
    return v


def build_parser():
    common = argparse.ArgumentParser(add_help=False)
    # Hidden: pin "today" for tests and for backfilling.
    common.add_argument("--today", type=_today, default=dt.date.today(),
                        help=argparse.SUPPRESS)

    ap = argparse.ArgumentParser(
        prog="audio.py", description="Pick the sound for a Reel from what is trending.")
    sub = ap.add_subparsers(dest="cmd", required=True)

    a = sub.add_parser("add", parents=[common],
                       help="add or update a sound (upserts by name + artist)")
    a.add_argument("--name", required=True)
    a.add_argument("--artist", default="")
    a.add_argument("--source", choices=SOURCES, required=True)
    a.add_argument("--region", required=True, help="country code, e.g. IN, US")
    a.add_argument("--reels-count", help="reels using it, from the sound page (8K, 12,400)")
    a.add_argument("--trend", choices=TRENDS)
    a.add_argument("--bpm", type=_bpm)
    a.add_argument("--mood", choices=MOODS)
    a.add_argument("--business-ok", choices=BUSINESS_OK)
    a.add_argument("--url")
    a.add_argument("--notes")
    a.add_argument("--seen", help="date seen, YYYY-MM-DD (default today)")

    s = sub.add_parser("suggest", parents=[common], help="rank sounds for one reel")
    s.add_argument("--reel-length", type=float, required=True, help="seconds")
    s.add_argument("--mood", choices=MOODS)
    s.add_argument("--account", choices=("business", "creator"), default="creator")
    s.add_argument("--voiceover", choices=("yes", "no"), default="no")
    s.add_argument("--script", help="script file; times it with ig-reel's beats.py")
    s.add_argument("--region", help="your audience's country code")
    s.add_argument("--top", type=int, default=5)
    s.add_argument("--json", action="store_true")

    l = sub.add_parser("list", parents=[common], help="show saved sounds")
    l.add_argument("--region")
    l.add_argument("--trend", choices=TRENDS)
    l.add_argument("--json", action="store_true")

    p = sub.add_parser("prune", parents=[common], help="drop sounds not seen recently")
    p.add_argument("--older-than", type=int, default=28, help="days (default 28)")
    p.add_argument("--dry-run", action="store_true")
    return ap


def main(argv=None, out=sys.stdout):
    args = build_parser().parse_args(argv)
    return {"add": cmd_add, "suggest": cmd_suggest, "list": cmd_list,
            "prune": cmd_prune}[args.cmd](args, out)


if __name__ == "__main__":
    sys.exit(main())
