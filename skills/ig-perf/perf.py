#!/usr/bin/env python3
"""
perf.py - follow one reel (or post) over its first week, log every check, and
say what to do about it.

A reel's life is mostly decided in its first 72 hours. The ledger keeps the
final totals. This keeps the curve: a row per check in snapshots.csv, so you
can see whether a post is still climbing, already done, or stuck on one
problem you can still fix.

Every check also updates the post's row in the ledger (ig-ledger) to the
latest totals, so /ig-audit always sees the newest numbers.

What this does NOT do: post, like, comment or touch Instagram at all. You read
the numbers off the app (or a screenshot, or the ig-kweo browser) and this
keeps the books and does the arithmetic.

The diagnosis rules are rules of thumb, not Meta numbers. On a few hundred
views every rate on this page is noisy, and the report says so.

Usage
  python3 perf.py check P0004 --views 1200 --reach 950 --shares 6 --skip-rate 41 --hours 24
  python3 perf.py check P0004 --views 3400 --at "2026-10-14 18:00" --source screenshot
  python3 perf.py status P0004 [--script script.txt] [--json]
  python3 perf.py due [--json]
  python3 perf.py retention P0004 --points "0:100,1:82,3:61,10:40,20:22" [--script script.txt]
"""

import argparse
import csv
import datetime as dt
import importlib.util
import json
import os
import statistics
import sys

HERE = os.path.dirname(os.path.abspath(__file__))

LEDGER_DIRS = [
    os.path.join(HERE, "..", "ig-ledger"),
    os.path.expanduser("~/.claude/skills/ig-ledger"),
]
REEL_DIRS = [
    os.path.join(HERE, "..", "ig-reel"),
    os.path.expanduser("~/.claude/skills/ig-reel"),
]

SNAP_COLUMNS = [
    "post_id", "taken_at", "hours_since_post", "views", "reach", "likes",
    "comments", "shares", "saves", "follows", "skip_rate", "nonfollower_pct",
    "avg_watch_s", "source", "notes",
]
COUNT_FIELDS = ("views", "reach", "likes", "comments", "shares", "saves", "follows")
PCT_FIELDS = ("skip_rate", "nonfollower_pct")
METRICS = COUNT_FIELDS + PCT_FIELDS + ("avg_watch_s",)
SOURCES = ("manual", "screenshot", "kweo", "csv")
TIME_FMT = "%Y-%m-%d %H:%M"

# ---------------------------------------------------------------- thresholds
# All rules of thumb. They come from how reels usually behave on small and
# mid-sized accounts, not from Meta. Tune them for a niche that runs hot or
# cold, but keep the order: a hook problem hides every problem after it.

# Hook. Skip rate is the share of viewers gone inside the first 3 seconds.
# Most reels sit somewhere in the 30s to low 40s. Past 45%, nearly half the
# people who were shown it left before the first idea landed. That is the
# hook, whatever else is wrong.
SKIP_RATE_HOOK = 45.0

# Middle. Average watch time over length. Under 40%, the typical viewer left
# before the halfway mark, so the payoff never reached them. With an OK skip
# rate, the hook did its job and the body lost them.
WATCH_RATIO_MIDDLE = 0.40

# Nothing to send. Sends (shares) per reach. A send is a person putting their
# name on the post. Under 0.5% (5 per 1,000 reached) the reel was watched and
# not passed on, which is what caps reach for most reels that hold well.
SENDS_PER_REACH_MIN = 0.005

# Profile. Same two-part test as audit.py: the reel travelled (half or more
# of reach from non-followers) but fewer than 2 follows per 1,000 reached.
# The attention arrived and the profile let it leave.
PROFILE_NONFOLLOWER_MIN = 50.0
FOLLOWS_PER_REACH_MIN = 0.002

# Not travelling. After a day, a reel shown mostly to followers (under 30%
# non-followers) has not been pushed out. Before 24h that is normal: the
# first wave always goes to followers.
TRAVEL_NONFOLLOWER_MIN = 30.0
TRAVEL_MIN_HOURS = 24.0

# Stalled. After 72h most reels have had their run. If the last stretch
# earned under a tenth of the post's average hourly views, it is done
# growing on its own. If the metrics were good, the content deserves a
# second life in another format.
STALL_MIN_HOURS = 72.0
STALL_RATE_RATIO = 0.10

# Accelerating. Views per hour normally fall after the first day. A later
# stretch running 20% faster than the one before is a second wave.
ACCEL_RATIO = 1.2

# Small numbers. Under this reach, one send or one follow moves the rates a
# lot. The report still shows them, with a warning.
NOISY_REACH = 1000

# Comparing at the same age needs this many other posts with snapshots near
# that age. Fewer, and it falls back to the ledger median.
PEER_MIN = 3
PEER_HOURS_TOLERANCE = 0.25        # a snapshot within 25% of the age counts

# Outlier multiples worth acting on.
PIN_MULTIPLE = 1.5

# Checkpoints: name, hours, and the window a snapshot has to fall in to count.
CHECKPOINTS = (
    ("1h", 1, 0.5, 3),
    ("24h", 24, 18, 36),
    ("72h", 72, 60, 96),
    ("7d", 168, 144, 216),
)
TRACK_HOURS = 216                   # after this, the post is out of `due`

# Hook formulas that usually hold the first 3 seconds better, because they
# put a number, a result or motion in frame one. Used when the ledger does
# not have enough of the account's own evidence.
FALLBACK_FORMULAS = (1, 18, 23, 21, 6, 13)

# Retention: a stretch is "steep" if it loses this many points per second.
STEEP_DROP_PER_S = 5.0
HOOK_WINDOW_S = 3.0


# ---------------------------------------------------------------- data dir

def data_dir():
    """IG_DATA_DIR, else the active account under IG_HOME, else IG_HOME."""
    env = os.environ.get("IG_DATA_DIR")
    if env:
        return os.path.expanduser(env)
    home = os.path.expanduser(os.environ.get("IG_HOME") or "~/.claude/instagram")
    marker = os.path.join(home, "active-account")
    try:
        with open(marker, encoding="utf-8") as f:
            handle = f.read().strip().lstrip("@")
    except OSError:
        handle = ""
    if handle:
        acct = os.path.join(home, "accounts", handle)
        if os.path.isdir(acct):
            return acct
    return home


def snapshots_path():
    return os.path.join(data_dir(), "snapshots.csv")


def retention_path():
    return os.path.join(data_dir(), "retention.csv")


_LEDGER = None


def get_ledger():
    """The ig-ledger module, pointed at the same data dir as this script.
    None when ig-ledger is not installed."""
    global _LEDGER
    # Pin the ledger to our resolved dir, whatever its own data_dir() does.
    os.environ["IG_DATA_DIR"] = data_dir()
    if _LEDGER is not None:
        return _LEDGER
    if "ledger" in sys.modules:
        _LEDGER = sys.modules["ledger"]
        return _LEDGER
    for d in LEDGER_DIRS:
        path = os.path.join(d, "ledger.py")
        if os.path.isfile(path):
            try:
                spec = importlib.util.spec_from_file_location("ledger", path)
                mod = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(mod)
                sys.modules["ledger"] = mod
                _LEDGER = mod
                return mod
            except Exception:
                continue
    return None


def load_beats():
    """beats.analyse from ig-reel, or None."""
    for d in REEL_DIRS:
        path = os.path.join(d, "beats.py")
        if os.path.isfile(path):
            try:
                spec = importlib.util.spec_from_file_location("_ig_beats", path)
                mod = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(mod)
                return mod.analyse
            except Exception:
                continue
    return None


def load_hooks():
    """{id(str): hook dict} from ig-reel/hooks.json, or {}."""
    for d in REEL_DIRS:
        path = os.path.join(d, "hooks.json")
        try:
            with open(path, encoding="utf-8") as f:
                return {str(h["id"]): h for h in json.load(f)["hooks"]}
        except Exception:
            continue
    return {}


# ---------------------------------------------------------------- values

def num(v):
    """'12,400' -> 12400.0, '1.2k' -> 1200.0, '34%' -> 34.0, '' -> None."""
    if v is None:
        return None
    s = str(v).strip().replace(",", "").replace(" ", "")
    if s in ("", "-", "--", "n/a", "N/A", "None"):
        return None
    s = s.rstrip("%").rstrip("s")
    mult = 1
    if s[-1:] in ("k", "K"):
        mult, s = 1000, s[:-1]
    elif s[-1:] in ("m", "M"):
        mult, s = 1000000, s[:-1]
    try:
        return float(s) * mult
    except ValueError:
        return None


def count_arg(text):
    n = num(text)
    if n is None or n < 0:
        raise argparse.ArgumentTypeError(f"not a count: {text!r}")
    return int(round(n))


def pct_arg(text):
    """Percent 0-100. A bare 0.34 is a fraction from a spreadsheet: 34."""
    n = num(text)
    if n is None:
        raise argparse.ArgumentTypeError(f"not a percentage: {text!r}")
    if 0 < n < 1 and "%" not in str(text):
        n *= 100
    if not 0 <= n <= 100:
        raise argparse.ArgumentTypeError(f"percentage is 0 to 100, got {text!r}")
    return round(n, 2)


def secs_arg(text):
    n = num(text)
    if n is None or n < 0:
        raise argparse.ArgumentTypeError(f"not seconds: {text!r}")
    return n


def parse_time(s):
    s = (s or "").strip()
    for fmt in (TIME_FMT, "%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d"):
        try:
            return dt.datetime.strptime(s, fmt)
        except ValueError:
            continue
    return None


def time_arg(text):
    t = parse_time(text)
    if t is None:
        raise argparse.ArgumentTypeError(f'time must be "YYYY-MM-DD HH:MM", got {text!r}')
    return t


def now():
    return dt.datetime.now().replace(second=0, microsecond=0)


def fmt_n(x):
    if x is None:
        return "-"
    return f"{int(round(x)):,}"


def fmt_pct(x, digits=1):
    return "-" if x is None else f"{x * 100:.{digits}f}%"


def fmt_hours(h):
    if h is None:
        return "-"
    if h < 48:
        return f"{h:.0f}h" if h >= 10 else f"{h:.1f}h".replace(".0h", "h")
    return f"{h / 24:.1f}d".replace(".0d", "d")


def ratio(a, b):
    if a is None or not b:
        return None
    return a / b


def norm_id(pid):
    p = pid.strip().upper()
    if p.isdigit():
        p = f"P{int(p):04d}"
    return p


# ---------------------------------------------------------------- snapshots

def load_snapshots(post_id=None):
    path = snapshots_path()
    if not os.path.exists(path):
        return []
    out = []
    with open(path, encoding="utf-8-sig", newline="") as f:
        for raw in csv.DictReader(f):
            r = {c: (raw.get(c) or "").strip() for c in SNAP_COLUMNS}
            if post_id and r["post_id"] != post_id:
                continue
            out.append(r)
    return out


def append_snapshot(row):
    path = snapshots_path()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    new = not os.path.exists(path) or os.path.getsize(path) == 0
    with open(path, "a", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=SNAP_COLUMNS, extrasaction="ignore")
        if new:
            w.writeheader()
        w.writerow({c: "" if row.get(c) is None else str(row.get(c)) for c in SNAP_COLUMNS})


def snap_values(r):
    """A snapshot row as numbers (None for empty)."""
    out = {k: num(r.get(k)) for k in METRICS}
    out["hours"] = num(r.get("hours_since_post"))
    out["taken_at"] = r.get("taken_at", "")
    out["source"] = r.get("source", "")
    out["notes"] = r.get("notes", "")
    return out


def series(post_id, snaps=None):
    """Snapshots for one post as numbers, sorted by age."""
    rows = snaps if snaps is not None else load_snapshots(post_id)
    vals = [snap_values(r) for r in rows if r["post_id"] == post_id]
    vals = [v for v in vals if v["hours"] is not None]
    return sorted(vals, key=lambda v: v["hours"])


def posted_at(post_id, row=None, snaps=None):
    """(datetime, how) for when the post went up.
    From a snapshot (taken_at minus its hours), else noon on the ledger date."""
    for v in series(post_id, snaps):
        t = parse_time(v["taken_at"])
        if t is not None:
            return t - dt.timedelta(hours=v["hours"]), "from a check"
    if row and row.get("date"):
        d = parse_time(row["date"])
        if d is not None:
            return d.replace(hour=12), "assumed noon"
    return None, "unknown"


def checkpoint_for(hours):
    for name, _, lo, hi in CHECKPOINTS:
        if lo <= hours <= hi:
            return name
    return ""


# ---------------------------------------------------------------- check

def record_check(post_id, metrics, hours=None, at=None, posted=None, source="manual",
                 notes=""):
    """Append one snapshot and bring the ledger row up to the latest totals.
    metrics: {field: number or None}. Returns (snapshot dict, ledger_note)."""
    pid = norm_id(post_id)
    led = get_ledger()
    row = led.get_row(pid) if led else None
    if led and row is None:
        raise KeyError(f"no post with id {pid} in the ledger. Log it first: "
                       f"ledger.py add --format reel ...")
    if all(metrics.get(k) is None for k in METRICS):
        raise ValueError("no numbers given. Pass at least --views.")

    taken = at or now()
    if hours is None:
        start = posted
        if start is None:
            start, how = posted_at(pid, row)
            if start is None:
                raise ValueError("cannot tell how old the post is. Pass --hours or --posted-at.")
        hours = (taken - start).total_seconds() / 3600
    if hours < 0:
        raise ValueError("that check is before the post went up. Check --at / --posted-at.")

    snap = {"post_id": pid, "taken_at": taken.strftime(TIME_FMT),
            "hours_since_post": f"{hours:.2f}".rstrip("0").rstrip("."),
            "source": source or "manual", "notes": notes or ""}
    for k in METRICS:
        v = metrics.get(k)
        if v is None:
            snap[k] = ""
        elif k in COUNT_FIELDS:
            snap[k] = str(int(round(v)))
        else:
            snap[k] = f"{v:g}"
    earlier = series(pid)
    append_snapshot(snap)

    note = "ledger not found, snapshot only"
    if led:
        latest = max((v["hours"] for v in earlier), default=-1)
        if hours + 1e-9 >= latest:
            fields = {}
            for k in METRICS:
                v = metrics.get(k)
                if v is None:
                    continue
                fields[k] = f"{v:g}%" if k in PCT_FIELDS else f"{v:g}"
            led.update_row(pid, **fields)
            note = "ledger updated to these totals"
        else:
            note = (f"older than the latest check ({fmt_hours(latest)}), "
                    "so the ledger keeps the newer totals")
    return snap, note


# ---------------------------------------------------------------- analysis

def velocity(points):
    """points: series. Returns dict with segments and a trend word."""
    pts = [(v["hours"], v["views"]) for v in points if v["views"] is not None]
    segs, prev = [], (0.0, 0.0)
    for h, views in pts:
        dh = h - prev[0]
        if dh > 0:
            segs.append({"from_h": prev[0], "to_h": h, "views": views - prev[1],
                         "per_hour": (views - prev[1]) / dh})
        prev = (h, views)
    out = {"segments": segs, "trend": "none", "line": "No views logged yet."}
    if not segs:
        return out
    last = segs[-1]
    total_h, total_v = pts[-1]
    avg = total_v / total_h if total_h else None
    out["avg_per_hour"] = avg
    if len(segs) == 1:
        out["trend"] = "one check"
        out["line"] = (f"One check so far: {last['per_hour']:,.0f} views/hour on average "
                       "since posting. Velocity needs a second check.")
        return out
    before = segs[-2]
    r = ratio(last["per_hour"], before["per_hour"])
    span = f"{fmt_hours(last['from_h'])} to {fmt_hours(last['to_h'])}"
    if avg and last["per_hour"] < STALL_RATE_RATIO * avg:
        out["trend"] = "stalled"
        out["line"] = (f"Stalled. {last['per_hour']:,.1f} views/hour from {span}, under a "
                       f"tenth of its {avg:,.0f}/hour average. It is done growing on its own.")
    elif r is not None and r >= ACCEL_RATIO:
        out["trend"] = "accelerating"
        out["line"] = (f"Accelerating. {last['per_hour']:,.0f} views/hour from {span}, up from "
                       f"{before['per_hour']:,.0f}. A second wave: it is being pushed to new people.")
    else:
        out["trend"] = "slowing"
        out["line"] = (f"Slowing, which is normal. {last['per_hour']:,.0f} views/hour from "
                       f"{span}, down from {before['per_hour']:,.0f}.")
    return out


def views_at(points, hours):
    """Views at a given age from a post's snapshots: interpolated between two
    checks, or the nearest check within the tolerance. None if neither."""
    pts = [(v["hours"], v["views"]) for v in points if v["views"] is not None]
    if not pts:
        return None
    for (h0, v0), (h1, v1) in zip(pts, pts[1:]):
        if h0 <= hours <= h1 and h1 > h0:
            return v0 + (v1 - v0) * (hours - h0) / (h1 - h0)
    near = min(pts, key=lambda p: abs(p[0] - hours))
    if abs(near[0] - hours) <= PEER_HOURS_TOLERANCE * max(hours, 1):
        return near[1]
    return None


def compare(pid, row, points, rows, snaps):
    """Outlier multiple at the same age, or against the ledger median."""
    out = {"multiple": None, "basis": None, "n": 0, "baseline": None, "note": ""}
    if not points or points[-1]["views"] is None:
        out["note"] = "No views yet, nothing to compare."
        return out
    age, views = points[-1]["hours"], points[-1]["views"]
    trial = (row or {}).get("trial") == "yes"

    def same_kind(r):
        return (r["id"] != pid and (r.get("trial") == "yes") == trial
                and r.get("format") != "story")

    others = [r for r in rows if same_kind(r)]
    peers = []
    for r in others:
        v = views_at(series(r["id"], snaps), age)
        if v is not None:
            peers.append(v)
    if len(peers) >= PEER_MIN:
        base = statistics.median(peers)
        out.update(basis="same age", n=len(peers), baseline=base,
                   multiple=ratio(views, base))
        out["note"] = (f"Against {len(peers)} other posts at about {fmt_hours(age)} old "
                       f"(median {fmt_n(base)} views).")
        return out
    totals = [num(r.get("views")) for r in others]
    totals = [t for t in totals if t is not None]
    if totals:
        base = statistics.median(totals)
        out.update(basis="ledger median", n=len(totals), baseline=base,
                   multiple=ratio(views, base))
        msg = (f"Against the ledger median of {len(totals)} posts ({fmt_n(base)} views). "
               f"Only {len(peers)} had checks near this age, under the {PEER_MIN} needed.")
        if age < 168:
            msg += (" Those are mostly finished totals, so a young post looks worse "
                    "than it is.")
        if len(totals) < 10:
            msg += f" n={len(totals)} is thin: treat the multiple as a rough guide."
        out["note"] = msg
    else:
        out["note"] = "No other posts with views in the ledger yet, nothing to compare."
    return out


def latest_metrics(points, row):
    """Newest non-empty value of each metric across checks, then the ledger."""
    m = {}
    for k in METRICS:
        v = None
        for p in reversed(points):
            if p[k] is not None:
                v = p[k]
                break
        if v is None and row:
            v = num(row.get(k))
        m[k] = v
    m["length_s"] = num(row.get("length_s")) if row else None
    m["hours"] = points[-1]["hours"] if points else None
    return m


def rates(m):
    return {
        "skip_rate": m["skip_rate"],
        "watch_ratio": ratio(m["avg_watch_s"], m["length_s"]),
        "sends_per_reach": ratio(m["shares"], m["reach"]),
        "saves_per_reach": ratio(m["saves"], m["reach"]),
        "follows_per_reach": ratio(m["follows"], m["reach"]),
        "nonfollower_pct": m["nonfollower_pct"],
    }


def formula_name(hooks, fid):
    h = hooks.get(str(fid).strip()) if fid else None
    return f"#{fid} {h['name']}" if h else (f"#{fid}" if fid else None)


def suggest_formulas(current, rows, hooks, k=2):
    """Two other formulas: the account's own winners first (mean outlier
    multiple above 1 with at least 2 posts), then the fallback list."""
    picks, why = [], {}
    vals = [num(r.get("views")) for r in rows if r.get("trial") != "yes"]
    vals = [v for v in vals if v is not None]
    if vals:
        med = statistics.median(vals)
        groups = {}
        for r in rows:
            v, f = num(r.get("views")), (r.get("hook_formula") or "").strip()
            if v is None or not f or r.get("trial") == "yes" or not med:
                continue
            groups.setdefault(f, []).append(v / med)
        ranked = sorted(((statistics.mean(g), f, len(g)) for f, g in groups.items()
                         if len(g) >= 2 and statistics.mean(g) > 1), reverse=True)
        for mean, f, n in ranked:
            if f != str(current) and f in hooks and f not in picks:
                picks.append(f)
                why[f] = f"{mean:.1f}x your median over {n} posts"
    for f in map(str, FALLBACK_FORMULAS):
        if len(picks) >= k:
            break
        if f != str(current) and f in hooks and f not in picks:
            picks.append(f)
            why[f] = "puts something concrete in frame one"
    return [(f, hooks[f], why[f]) for f in picks[:k]]


def diagnose(m, r, vel, rows, row, hooks):
    """All rules that fire, in priority order. The first is THE problem."""
    found, missing = [], []
    hours = m["hours"] or 0
    skip, watch = r["skip_rate"], r["watch_ratio"]
    sends, follows, nonf = r["sends_per_reach"], r["follows_per_reach"], r["nonfollower_pct"]

    # 1. hook
    if skip is None:
        missing.append("skip rate (for the hook check)")
    elif skip > SKIP_RATE_HOOK:
        fid = (row or {}).get("hook_formula", "")
        cur = formula_name(hooks, fid)
        alts = suggest_formulas(fid, rows, hooks)
        alt_txt = "; ".join(f"#{f} {h['name']} (\"{h['example']}\", {w})" for f, h, w in alts)
        detail = (f"Skip rate {skip:.0f}%, over the {SKIP_RATE_HOOK:.0f}% line. Nearly half "
                  f"left in the first 3 seconds. Rewrite the first 2 seconds: spoken line "
                  f"and on-screen line both.")
        if cur:
            detail += f" This one used {cur}."
        else:
            detail += " No hook formula logged for this post, so the ledger cannot learn from it."
        if alt_txt:
            detail += f" Try instead: {alt_txt}."
        found.append({"rule": "hook", "title": "HOOK PROBLEM", "detail": detail,
                      "alternatives": [{"id": f, "name": h["name"], "example": h["example"],
                                        "why": w} for f, h, w in alts]})

    # 2. middle
    if watch is None:
        missing.append("average watch time and length (for the middle check)")
    elif watch < WATCH_RATIO_MIDDLE and (skip is None or skip <= SKIP_RATE_HOOK):
        found.append({"rule": "middle", "title": "MIDDLE PROBLEM", "detail": (
            f"Average watch {m['avg_watch_s']:.1f}s of {m['length_s']:.0f}s ({watch * 100:.0f}%), "
            f"under {WATCH_RATIO_MIDDLE * 100:.0f}%. The hook held and the body lost them. "
            f"Shorten it, change the frame every beat, and re-run beats.py on the script "
            f"to find the beats over 4 seconds.")})

    # 3. nothing worth sending
    if sends is None:
        missing.append("shares and reach (for the sends check)")
    elif sends < SENDS_PER_REACH_MIN and (watch is None or watch >= WATCH_RATIO_MIDDLE):
        found.append({"rule": "sends", "title": "NOTHING WORTH SENDING", "detail": (
            f"{fmt_n(m['shares'])} sends on {fmt_n(m['reach'])} reach ({sends * 100:.2f}%), under "
            f"{SENDS_PER_REACH_MIN * 100:.1f}%. People watched and kept it to themselves. "
            f"Add a takeaway or recap line someone would forward with \"this is you\", "
            f"and make one claim sharp enough to send.")})

    # 4. not travelling
    if nonf is None:
        missing.append("non-follower % (for the travel and profile checks)")
    elif nonf < TRAVEL_NONFOLLOWER_MIN and hours >= TRAVEL_MIN_HOURS:
        found.append({"rule": "travel", "title": "NOT TRAVELLING", "detail": (
            f"Only {nonf:.0f}% of reach is non-followers after {fmt_hours(hours)}. It went to "
            f"your followers and stopped there. Push it out: a trial reel of a recut, a collab "
            f"with someone in the niche, or a reply-with-reel to a comment.")})

    # 5. profile
    if nonf is not None and follows is not None and nonf >= PROFILE_NONFOLLOWER_MIN \
            and follows < FOLLOWS_PER_REACH_MIN:
        found.append({"rule": "profile", "title": "PROFILE PROBLEM", "detail": (
            f"{nonf:.0f}% of reach was strangers, and only {fmt_n(m['follows'])} follows on "
            f"{fmt_n(m['reach'])} reach ({follows * 100:.2f}%, under "
            f"{FOLLOWS_PER_REACH_MIN * 100:.1f}%). The reel did its job. The profile did not. "
            f"Run /ig-profile.")})
    elif follows is None and nonf is not None:
        missing.append("follows and reach (for the profile check)")

    # 6. stalled with good metrics
    if vel.get("trend") == "stalled" and hours >= STALL_MIN_HOURS and not found:
        found.append({"rule": "stalled", "title": "RAN ITS COURSE", "detail": (
            f"Views have stalled after {fmt_hours(hours)} and the numbers that were checked "
            f"look healthy. The idea worked. Give it a second life: repurpose it into a "
            f"carousel (/ig-carousel), and reply to its best comments with new reels.")})

    if (m["reach"] or 0) and m["reach"] < NOISY_REACH:
        noise = (f"Small numbers: {fmt_n(m['reach'])} reach. One send moves the send rate by "
                 f"{100 / m['reach']:.2f} points. Read the rates as direction, not fact.")
    elif m["reach"] is None and (m["views"] or 0) < NOISY_REACH:
        noise = "Small numbers and no reach logged. Read every rate as direction, not fact."
    else:
        noise = ""
    return found, missing, noise


def improve(found, m, r, vel, cmp_, row, hooks, beat_map):
    """3 actions for this post now, 3 lessons for the next one."""
    hours = m["hours"] or 0
    rules = [f["rule"] for f in found]
    top = rules[0] if rules else None
    now_, next_ = [], []

    def add(lst, text):
        if text and text not in lst:
            lst.append(text)

    mult = cmp_.get("multiple")
    if hours < 2:
        add(now_, "Stay on it for the first hour: reply to every comment, with a question "
                  "back where you can. Early replies double the comment count.")
    if top == "hook":
        alts = found[0].get("alternatives") or []
        alt = f"#{alts[0]['id']} {alts[0]['name']}" if alts else "a formula that opens on a number"
        add(now_, f"Recut the first 2 seconds with {alt} and post the recut as a trial reel. "
                  "Same body, new open. /ig-test keeps the books on which hook won.")
        add(now_, "Change the cover and the first caption line so the grid version makes "
                  "the claim the video takes too long to make.")
    if top == "middle":
        cut = (m["avg_watch_s"] or 0) / 0.6 if m["avg_watch_s"] else None
        add(now_, "Cut a tighter version" + (f" of about {cut:.0f}s" if cut else "") +
                  " that drops the slowest beats and post it as a trial reel.")
        add(now_, "Pin a comment that gives the payoff in one line, so the people who left "
                  "early still get it.")
    if top == "sends":
        add(now_, "Edit the caption to open with the one-line takeaway, written so someone "
                  "can send it with \"this is you\".")
        add(now_, "Share it to your story with a poll on the claim. Polls get answered, "
                  "and answers bring people back to the reel.")
    if top == "travel":
        add(now_, "Reply to the best comment with a reel. Reply-reels get shown beyond "
                  "the people who saw the first one.")
        add(now_, "Ask one creator in your niche to share it to their story, or plan a collab "
                  "on the follow-up (/ig-dm for the pitch).")
    if top == "profile":
        add(now_, "Run /ig-profile now, while strangers are still landing on it. The bio's "
                  "first line has to say what following gets them.")
        add(now_, "Pin a comment that says what else you post about and why to follow.")
    if top == "stalled":
        add(now_, "Turn it into a carousel with /ig-carousel. Same idea, new format, new feed.")
        add(now_, "Reply to its top 2 comments with new reels. Those are follow-up ideas "
                  "the audience already asked for.")
    if mult is not None and mult >= PIN_MULTIPLE:
        add(now_, f"Pin it to your profile grid. At {mult:.1f}x it is the best proof a "
                  "visitor sees.")
    if (m["comments"] or 0) >= 3:
        add(now_, "Make a follow-up reel answering the best question in the comments "
                  "(/ig-reply to pick it, /ig-reel to write it).")
    if not any("story" in a for a in now_):
        add(now_, "Share it to your story with a poll or quiz sticker on its main claim.")
    add(now_, "Reply to the top comments with a question back to keep the thread going.")
    add(now_, "Pin a comment that asks the question the reel raises. A pinned question "
              "gets answered, and every answer is another comment.")

    # next reel
    fid = (row or {}).get("hook_formula")
    if top == "hook":
        add(next_, "Write three hook options for the next reel and run hookscore.py on them "
                   "before you shoot. Put a number or a result in frame one.")
        alts = found[0].get("alternatives") or []
        if alts:
            add(next_, f"Lead the next one with #{alts[0]['id']} {alts[0]['name']}. "
                       f"Template: \"{hooks.get(alts[0]['id'], {}).get('template', '')}\"")
    if top == "middle" or "middle" in rules:
        if m["avg_watch_s"]:
            add(next_, f"Script the next reel to land its payoff before {m['avg_watch_s']:.0f}s, "
                       "where this one's average viewer was gone. One idea per beat, new frame "
                       "every beat, run beats.py.")
    if top == "sends" or "sends" in rules:
        add(next_, "Write the sendable line first, then the reel around it. One claim a viewer "
                   "would forward to a specific person.")
    if top == "travel" or "travel" in rules:
        add(next_, "Plan one trial reel or collab a week into /ig-plan, so something always "
                   "goes to strangers first.")
    if top == "profile" or "profile" in rules:
        add(next_, "Fix the profile before the next push. Reach without a profile that "
                   "converts is wasted.")
    if top == "stalled" or (mult is not None and mult >= PIN_MULTIPLE):
        same = formula_name(hooks, fid)
        add(next_, "Make another on the same idea" + (f" with the same hook, {same}" if same else "")
                   + ". A winner is a template, not a one-off. Put it in /ig-plan this week.")
    if beat_map and beat_map.get("drop_beat"):
        b = beat_map["drop_beat"]
        add(next_, f"Beat {b['n']} (\"{b['text'][:50]}\") is where viewers left. Cut or move "
                   "that kind of line in the next script.")
    if not fid:
        add(next_, "Log the hook formula at publish (ledger.py update ID --hook-formula N). "
                   "Without it the audit cannot learn which hooks work for you.")
    add(next_, "Check the next reel at 1h, 24h and 72h. The curve says more than the total.")
    add(next_, "Reply to every comment in the first hour on the next one too.")
    return now_[:3], next_[:3]


def map_script(script_text, m, r, wpm=165):
    """Where the average viewer leaves, on the beat sheet."""
    analyse = load_beats()
    if analyse is None or not script_text.strip():
        return None
    a = analyse(script_text, wpm=wpm, target=m.get("length_s"))
    if not a:
        return None
    beats = a["beats"]
    out = {"total_seconds": a["total_seconds"], "beats": beats, "notes": [], "drop_beat": None}
    length = m.get("length_s") or a["total_seconds"]
    scale = (a["total_seconds"] / length) if length else 1.0
    if m.get("avg_watch_s") is not None:
        t = m["avg_watch_s"] * scale   # map real seconds onto script seconds
        b = beat_at(beats, t)
        if b:
            out["drop_beat"] = b
            out["notes"].append(f"Average viewer leaves around {m['avg_watch_s']:.1f}s, in beat "
                                f"{b['n']} ({b['label'] or 'body'}): \"{b['text'][:60]}\"")
    if r.get("skip_rate") is not None and r["skip_rate"] > SKIP_RATE_HOOK:
        b1 = beats[0]
        out["notes"].append(f"Beat 1 takes {b1['dur']:.1f}s to say. The skip happens inside "
                            f"{HOOK_WINDOW_S:.0f}s, so the hook line is: \"{b1['text'][:60]}\"")
    long_beats = [b for b in beats if b["flags"]]
    for b in long_beats[:3]:
        out["notes"].append(f"Beat {b['n']} at {b['start']:.1f}s: {', '.join(b['flags'])}")
    return out


def beat_at(beats, t):
    for b in beats:
        if b["start"] <= t < b["start"] + b["dur"]:
            return b
    return beats[-1] if beats and t >= beats[-1]["start"] else None


# ---------------------------------------------------------------- status

def build_status(post_id, script_text=None):
    pid = norm_id(post_id)
    led = get_ledger()
    rows = led.load_rows() if led else []
    row = next((r for r in rows if r["id"] == pid), None)
    snaps = load_snapshots()
    points = series(pid, snaps)
    if row is None and not points:
        raise KeyError(f"no post with id {pid} in the ledger or the snapshots")
    hooks = load_hooks()
    m = latest_metrics(points, row)
    r = rates(m)
    vel = velocity(points)
    cmp_ = compare(pid, row, points, rows, snaps)
    found, missing, noise = diagnose(m, r, vel, rows, row, hooks)
    beat_map = map_script(script_text, m, r) if script_text else None
    now_, next_ = improve(found, m, r, vel, cmp_, row, hooks, beat_map)
    start, how = posted_at(pid, row, snaps)
    timeline = []
    for p in points:
        timeline.append({"hours": p["hours"], "checkpoint": checkpoint_for(p["hours"]),
                         "taken_at": p["taken_at"], "source": p["source"],
                         **{k: p[k] for k in METRICS}})
    ret = [x for x in load_retention(pid)]
    return {
        "post_id": pid,
        "first_line": (row or {}).get("first_line", ""),
        "format": (row or {}).get("format", ""),
        "hook_formula": formula_name(hooks, (row or {}).get("hook_formula")),
        "length_s": m["length_s"],
        "posted_at": start.strftime(TIME_FMT) if start else None,
        "posted_at_how": how,
        "age_hours": m["hours"],
        "timeline": timeline,
        "checkpoints_missing": [c[0] for c in CHECKPOINTS
                                if m["hours"] is not None and m["hours"] >= c[2]
                                and not any(c[2] <= p["hours"] <= c[3] for p in points)],
        "velocity": vel,
        "compare": cmp_,
        "metrics": m,
        "rates": r,
        "diagnosis": found,
        "missing": missing,
        "noise": noise,
        "improve_now": now_,
        "improve_next": next_,
        "script": beat_map,
        "retention": ret[-1] if ret else None,
    }


def render_status(s, out=None):
    out = out or sys.stdout
    p = lambda *a: print(*a, file=out)  # noqa: E731
    head = f"REEL PERFORMANCE  ·  {s['post_id']}"
    if s["age_hours"] is not None:
        head += f"  ·  {fmt_hours(s['age_hours'])} old"
    p("\n" + head)
    p("=" * 78)
    if s["first_line"]:
        p(f"  \"{s['first_line'][:70]}\"")
    bits = [b for b in (s["format"], s["hook_formula"] and f"hook {s['hook_formula']}",
                        s["length_s"] and f"{s['length_s']:g}s") if b]
    if bits:
        p("  " + "  ·  ".join(bits))
    if s["posted_at"]:
        p(f"  posted {s['posted_at']} ({s['posted_at_how']})")

    p("\nTIMELINE")
    p("-" * 78)
    if not s["timeline"]:
        p("  no checks yet. Run: perf.py check " + s["post_id"] + " --views N --hours H")
    else:
        p(f"  {'age':>6} {'chk':<4} {'views':>9} {'reach':>9} {'sends':>6} {'saves':>6} "
          f"{'follows':>7} {'skip':>6} {'nonf':>6} {'watch':>6}")
        for t in s["timeline"]:
            pc = lambda v: "-" if v is None else f"{v:.0f}%"  # noqa: E731
            w = "-" if t["avg_watch_s"] is None else f"{t['avg_watch_s']:.1f}s"
            p(f"  {fmt_hours(t['hours']):>6} {t['checkpoint']:<4} {fmt_n(t['views']):>9} "
              f"{fmt_n(t['reach']):>9} {fmt_n(t['shares']):>6} {fmt_n(t['saves']):>6} "
              f"{fmt_n(t['follows']):>7} {pc(t['skip_rate']):>6} {pc(t['nonfollower_pct']):>6} "
              f"{w:>6}")
    if s["checkpoints_missing"]:
        p(f"  missed checkpoints: {', '.join(s['checkpoints_missing'])}")

    p("\nVELOCITY")
    p("-" * 78)
    p("  " + s["velocity"]["line"])

    p("\nVERSUS YOUR ACCOUNT")
    p("-" * 78)
    c = s["compare"]
    if c["multiple"] is not None:
        p(f"  {c['multiple']:.2f}x  ({c['basis']}, n={c['n']})")
    for line in wrap(c["note"], 74):
        p("  " + line)

    r = s["rates"]
    p("\nRATES")
    p("-" * 78)
    pc0 = lambda v: "-" if v is None else f"{v:.0f}%"  # noqa: E731
    p(f"  skip rate {pc0(r['skip_rate'])}   watch {fmt_pct(r['watch_ratio'], 0)} of length"
      f"   non-followers {pc0(r['nonfollower_pct'])}")
    p(f"  sends/reach {fmt_pct(r['sends_per_reach'], 2)}   saves/reach "
      f"{fmt_pct(r['saves_per_reach'], 2)}   follows/reach {fmt_pct(r['follows_per_reach'], 2)}")
    if s["noise"]:
        p("  " + s["noise"])

    p("\nDIAGNOSIS")
    p("-" * 78)
    if s["diagnosis"]:
        d = s["diagnosis"][0]
        p(f"  {d['title']}")
        for line in wrap(d["detail"], 74):
            p("  " + line)
        if len(s["diagnosis"]) > 1:
            p("  also: " + ", ".join(x["title"].lower() for x in s["diagnosis"][1:]) +
              ". Fix the first one first.")
    else:
        p("  No rule fired on the numbers given. "
          + ("It is doing its job." if not s["missing"] else "That may be missing data, not health."))
    if s["missing"]:
        p("  not checked, no data: " + "; ".join(s["missing"]))
    p("  Rules of thumb, not Meta numbers.")

    if s["script"]:
        p("\nON THE SCRIPT")
        p("-" * 78)
        for n in s["script"]["notes"] or ["Nothing on the beat sheet lines up with a problem."]:
            for line in wrap(n, 74):
                p("  " + line)
    if s["retention"]:
        p("\nRETENTION GRAPH")
        p("-" * 78)
        for line in wrap(s["retention"]["summary"], 74):
            p("  " + line)

    p("\nIMPROVE")
    p("-" * 78)
    p("  This post, now:")
    for i, a in enumerate(s["improve_now"], 1):
        for j, line in enumerate(wrap(a, 70)):
            p(f"  {str(i) + '.' if j == 0 else '':<3} {line}")
    p("  The next reel:")
    for i, a in enumerate(s["improve_next"], 1):
        for j, line in enumerate(wrap(a, 70)):
            p(f"  {str(i) + '.' if j == 0 else '':<3} {line}")
    p("")


def wrap(text, width):
    words, lines, cur = text.split(), [], ""
    for w in words:
        if cur and len(cur) + 1 + len(w) > width:
            lines.append(cur)
            cur = w
        else:
            cur = (cur + " " + w).strip()
    if cur:
        lines.append(cur)
    return lines or [""]


# ---------------------------------------------------------------- due

def due_list(at=None):
    """Posts up to 9 days old whose current checkpoint has no snapshot yet."""
    t = at or now()
    led = get_ledger()
    rows = led.load_rows() if led else []
    snaps = load_snapshots()
    out = []
    for row in rows:
        if row.get("format") == "story":
            continue
        start, how = posted_at(row["id"], row, snaps)
        if start is None:
            continue
        age = (t - start).total_seconds() / 3600
        if age < 0 or age > TRACK_HOURS:
            continue
        pts = series(row["id"], snaps)
        current = None
        for name, h, lo, hi in CHECKPOINTS:
            if age >= lo:
                current = (name, h, lo, hi)
        if current is None:
            continue
        name, h, lo, hi = current
        if any(lo <= p["hours"] <= hi for p in pts):
            continue
        late = age > hi
        nxt = next((c for c in CHECKPOINTS if c[2] > age), None)
        out.append({"post_id": row["id"], "first_line": row.get("first_line", ""),
                    "age_hours": round(age, 1), "checkpoint": name, "late": late,
                    "posted_at": start.strftime(TIME_FMT), "posted_at_how": how,
                    "next": nxt[0] if nxt else None})
    return out


def render_due(items, out=None):
    out = out or sys.stdout
    p = lambda *a: print(*a, file=out)  # noqa: E731
    p(f"\nCHECKS DUE  ·  {len(items)} post{'s' if len(items) != 1 else ''}")
    p("=" * 78)
    if not items:
        p("  nothing due. Every post from the last week has its latest checkpoint.")
        p("")
        return
    for d in items:
        when = "late, check anyway" if d["late"] else "due now"
        assumed = "  (post time assumed noon)" if d["posted_at_how"] == "assumed noon" else ""
        p(f"  {d['post_id']:<6} {d['checkpoint']:<4} {when:<19} {fmt_hours(d['age_hours']):>5} old  "
          f"{(d['first_line'] or '')[:30]}{assumed}")
    p("-" * 78)
    p("  Open the reel, tap View insights, and read off views, reach, shares, saves,")
    p("  follows, skip rate, non-follower % and average watch time. Or send a screenshot.")
    p("")


# ---------------------------------------------------------------- retention

def parse_points(text):
    pts = []
    for part in text.replace(";", ",").split(","):
        part = part.strip()
        if not part:
            continue
        if ":" not in part:
            raise ValueError(f"point must be seconds:percent, got {part!r}")
        a, b = part.split(":", 1)
        t, v = num(a), num(b)
        if t is None or v is None or t < 0 or not 0 <= v <= 100:
            raise ValueError(f"bad point {part!r}: seconds:percent, percent 0 to 100")
        pts.append((t, v))
    pts.sort()
    if len(pts) < 2:
        raise ValueError("need at least two points, for example 0:100,3:60")
    return pts


def analyse_retention(points, length=None, script_text=None, skip_rate=None):
    segs = []
    for (t0, v0), (t1, v1) in zip(points, points[1:]):
        if t1 <= t0:
            continue
        drop = v0 - v1
        segs.append({"from_s": t0, "to_s": t1, "drop": drop, "per_s": drop / (t1 - t0)})
    beats = None
    if script_text:
        analyse = load_beats()
        if analyse:
            a = analyse(script_text, target=length)
            beats = a["beats"] if a else None
    scale = 1.0
    if beats and length:
        total = beats[-1]["start"] + beats[-1]["dur"]
        scale = total / length if length else 1.0
    steep = sorted(segs, key=lambda s: s["per_s"], reverse=True)
    for s in segs:
        notes = []
        if s["to_s"] <= HOOK_WINDOW_S + 0.01:
            notes.append("hook window")
        if length and s["from_s"] >= length * 0.9:
            notes.append("end of video, normal")
        s["where"] = ", ".join(notes)
        s["beats"] = []
        if beats:
            a0, a1 = s["from_s"] * scale, s["to_s"] * scale
            s["beats"] = [{"n": b["n"], "label": b["label"], "start": b["start"],
                           "text": b["text"]} for b in beats
                          if b["start"] < a1 and b["start"] + b["dur"] > a0]
    worst = [s for s in steep if "end of video" not in s["where"]][:3]
    held3 = None
    for t, v in points:
        if t <= HOOK_WINDOW_S:
            held3 = v
    end = points[-1]
    summary = "No drop worth naming."
    if worst:
        w = worst[0]
        summary = (f"Steepest drop {w['from_s']:g}s to {w['to_s']:g}s: lost {w['drop']:.0f} points "
                   f"({w['per_s']:.1f}/s)")
        if w["where"]:
            summary += f", {w['where']}"
        if w["beats"]:
            summary += f", beat {w['beats'][0]['n']}: \"{w['beats'][0]['text'][:60]}\""
        summary += f". {end[1]:.0f}% still watching at {end[0]:g}s."
    return {"points": points, "segments": segs, "steepest": worst,
            "held_at_3s": held3, "summary": summary,
            "skip_rate": skip_rate, "mapped_to_script": bool(beats)}


def save_retention(post_id, points, summary):
    path = retention_path()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    new = not os.path.exists(path)
    with open(path, "a", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        if new:
            w.writerow(["post_id", "taken_at", "points", "summary"])
        w.writerow([post_id, now().strftime(TIME_FMT),
                    ",".join(f"{t:g}:{v:g}" for t, v in points), summary])


def load_retention(post_id):
    path = retention_path()
    if not os.path.exists(path):
        return []
    with open(path, encoding="utf-8", newline="") as f:
        return [r for r in csv.DictReader(f) if r.get("post_id") == post_id]


def render_retention(pid, a, out=None):
    out = out or sys.stdout
    p = lambda *x: print(*x, file=out)  # noqa: E731
    p(f"\nRETENTION  ·  {pid}  ·  {len(a['points'])} points")
    p("=" * 78)
    p(f"  {'stretch':<13} {'lost':>6} {'per sec':>8}  where")
    for s in a["segments"]:
        mark = " <" if s in a["steepest"] else ""
        where = s["where"]
        if s["beats"]:
            where = (where + "; " if where else "") + "beat " + ", ".join(
                str(b["n"]) for b in s["beats"])
        span = f"{s['from_s']:g}s-{s['to_s']:g}s"
        p(f"  {span:<13} {s['drop']:>5.0f} {s['per_s']:>8.1f}  "
          f"{where}{mark}")
    p("-" * 78)
    for line in wrap(a["summary"], 74):
        p("  " + line)
    for s in a["steepest"]:
        if s["per_s"] < STEEP_DROP_PER_S:
            continue
        for b in s["beats"]:
            p(f"  {s['from_s']:g}-{s['to_s']:g}s  beat {b['n']} {b['label'] or ''}  "
              f"\"{b['text'][:55]}\"")
    if not a["mapped_to_script"]:
        p("  Pass --script script.txt to see which lines sit on the steep stretches.")
    if a["held_at_3s"] is not None:
        p(f"  {a['held_at_3s']:.0f}% held to 3s. Skip rate is roughly 100 minus that.")
    p("  A graph read off a screenshot is approximate. Big drops are real, small ones may not be.")
    p("")


# ---------------------------------------------------------------- cli

def read_script(path):
    if not path:
        return None
    with open(path, encoding="utf-8") as f:
        return f.read()


def main(argv=None, out=None):
    out = out or sys.stdout
    ap = argparse.ArgumentParser(description="Track one reel over its first week.")
    sub = ap.add_subparsers(dest="cmd", required=True)

    c = sub.add_parser("check", help="log a check: append a snapshot, update the ledger")
    c.add_argument("id")
    c.add_argument("--views", type=count_arg)
    for f in ("reach", "likes", "comments", "shares", "saves", "follows"):
        c.add_argument(f"--{f}", type=count_arg)
    c.add_argument("--sends", dest="shares_alias", type=count_arg, help="same as --shares")
    c.add_argument("--skip-rate", type=pct_arg, help="percent 0-100")
    c.add_argument("--nonfollower-pct", type=pct_arg, help="percent of reach, 0-100")
    c.add_argument("--avg-watch", type=secs_arg, help="seconds")
    c.add_argument("--hours", type=secs_arg, help="hours since posting")
    c.add_argument("--at", type=time_arg,
                   help='when you read the numbers, "YYYY-MM-DD HH:MM" (default now). '
                        'With --hours too, both are kept as given (for backfills).')
    c.add_argument("--posted-at", type=time_arg, help='when it went up, "YYYY-MM-DD HH:MM"')
    c.add_argument("--source", choices=SOURCES, default="manual")
    c.add_argument("--notes", default="")
    c.add_argument("--json", action="store_true")
    c.add_argument("--quiet", action="store_true", help="skip the status report")

    s = sub.add_parser("status", help="timeline, velocity, diagnosis, what to do")
    s.add_argument("id")
    s.add_argument("--script", help="the reel's script, to map problems onto beats")
    s.add_argument("--json", action="store_true")

    d = sub.add_parser("due", help="posts that need a check now")
    d.add_argument("--now", type=time_arg, help=argparse.SUPPRESS)
    d.add_argument("--json", action="store_true")

    r = sub.add_parser("retention", help="read a retention graph and find the drops")
    r.add_argument("id")
    r.add_argument("--points", required=True, help='"seconds:percent,..." e.g. "0:100,3:61,10:40"')
    r.add_argument("--script")
    r.add_argument("--length", type=secs_arg, help="reel length in seconds (default: ledger)")
    r.add_argument("--no-save", action="store_true")
    r.add_argument("--json", action="store_true")

    args = ap.parse_args(argv)
    try:
        if args.cmd == "check":
            metrics = {
                "views": args.views, "reach": args.reach, "likes": args.likes,
                "comments": args.comments,
                "shares": args.shares if args.shares is not None else args.shares_alias,
                "saves": args.saves, "follows": args.follows, "skip_rate": args.skip_rate,
                "nonfollower_pct": args.nonfollower_pct, "avg_watch_s": args.avg_watch,
            }
            hours, at = args.hours, args.at
            if hours is None and args.posted_at is not None:
                hours = ((at or now()) - args.posted_at).total_seconds() / 3600
            snap, note = record_check(args.id, metrics, hours=hours, at=at,
                                      source=args.source, notes=args.notes)
            if args.json:
                print(json.dumps({"snapshot": snap, "ledger": note,
                                  "status": build_status(snap["post_id"])},
                                 indent=2, ensure_ascii=False, default=str), file=out)
            else:
                print(f"logged {snap['post_id']} at {fmt_hours(float(snap['hours_since_post']))} "
                      f"({snap['source']}). {note}.", file=out)
                if not args.quiet:
                    render_status(build_status(snap["post_id"]), out)
        elif args.cmd == "status":
            st = build_status(args.id, read_script(args.script))
            if args.json:
                print(json.dumps(st, indent=2, ensure_ascii=False, default=str), file=out)
            else:
                render_status(st, out)
        elif args.cmd == "due":
            items = due_list(args.now)
            if args.json:
                print(json.dumps(items, indent=2, ensure_ascii=False), file=out)
            else:
                render_due(items, out)
        elif args.cmd == "retention":
            pid = norm_id(args.id)
            led = get_ledger()
            row = led.get_row(pid) if led else None
            length = args.length or (num(row.get("length_s")) if row else None)
            skip = num(row.get("skip_rate")) if row else None
            a = analyse_retention(parse_points(args.points), length,
                                  read_script(args.script), skip)
            if not args.no_save:
                save_retention(pid, a["points"], a["summary"])
            if args.json:
                print(json.dumps(a, indent=2, ensure_ascii=False), file=out)
            else:
                render_retention(pid, a, out)
    except (ValueError, KeyError, OSError) as e:
        msg = e.args[0] if isinstance(e, KeyError) and e.args else e
        print(f"error: {msg}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
