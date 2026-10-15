#!/usr/bin/env python3
"""
grow.py - the head coach. Tracks follower growth, finds the one thing holding
growth back, and turns it into this week's short list of actions, each one
handed to the skill that does it.

It reads, it never posts. Nothing here touches Instagram.

Data lives in the pack's data dir (see data_dir()):
  followers.csv   date,followers,following,posts,notes   (written here)
  posts.csv       the ig-ledger ledger                   (read only)
  snapshots.csv   per-post checks from ig-perf           (read only, optional)
  trends.md       from ig-trends                         (read only, optional)
  plan.md, voice.md, engaged.md                          (read only, optional)

Usage
  python3 grow.py checkin --followers 1240 [--following 310] [--posts 58] [--date 2026-10-15]
  python3 grow.py report [--weeks 4] [--json]
  python3 grow.py plan [--json]
  python3 grow.py milestones [--json]

--today YYYY-MM-DD pins "today" (for backfills and tests).
"""

import argparse
import csv
import datetime as dt
import json
import os
import re
import statistics
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))

FOLLOWER_COLUMNS = ["date", "followers", "following", "posts", "notes"]
MILESTONES = (100, 500, 1000, 5000, 10000, 50000, 100000, 500000, 1000000)
RULE = "=" * 60

# ------------------------------------------------------------- thresholds
# One bottleneck, checked in pipeline order. An upstream failure hides the
# downstream ones: no posts means nothing to retain, a reel nobody holds past
# 3 seconds never travels, and a reel that never travels converts nobody new.
# These are rules of thumb, not Meta numbers. Tune them for your niche.

# Consistency. ig-plan asks for 4 to 5 posts a week, at least 3 of them reels.
# Under 3 a week the account gives the system too few chances to find an
# audience, and every other number is too thin to read.
TARGET_POSTS_PER_WEEK = 4
CONSISTENCY_MIN_POSTS_PER_WEEK = 3

# Retention. Skip rate is the share who swipe away in the first 3 seconds
# (lower is better). In ig-audit's worked example the top five sat near 34%
# and the bottom five near 67%. A median over 50% means most reels lose half
# the room before the hook lands, and Mosseri names watch time as a top
# ranking signal for both followers and non-followers.
RETENTION_MAX_SKIP_RATE = 50.0

# Reach. A reel that "travels" is one where a real share of reach comes from
# people who do not follow. Under 30% median, the reels are mostly being
# shown to the existing audience. If non-follower share is not logged, fall
# back to reach as a multiple of follower count: a median reel reaching
# under half the follower count is not leaving the building.
REACH_MIN_NONFOLLOWER_PCT = 30.0
REACH_MIN_REACH_PER_FOLLOWER = 0.5

# Conversion. Same line as ig-ledger's audit.py profile check: under 2
# follows per 1,000 accounts reached (0.2%), attention arrived and the
# profile let it leave. A reel that reaches strangers and earns a profile
# visit usually lands around 0.5% to 1%.
CONVERSION_MIN_FOLLOWS_PER_REACH = 0.002

# Engagement round. ig-plan says 20 minutes a day. Five days a week counts.
ENGAGE_TARGET_DAYS_PER_WEEK = 5

# Fewer posts with numbers than this and the bottleneck is called "early".
EVIDENCE_MIN_POSTS = 5

# A post younger than this with no views logged is due a check (ig-perf).
PERF_DUE_MAX_DAYS = 7

MAX_ACTIONS = 7

BOTTLENECKS = ("consistency", "retention", "reach", "conversion")
BOTTLENECK_TEXT = {
    "consistency": "CONSISTENCY - not posting often enough to be found",
    "retention": "RETENTION - people swipe before the hook lands",
    "reach": "REACH - reels are not travelling past your followers",
    "conversion": "CONVERSION - reels travel but the profile does not turn viewers into followers",
    "onboarding": "ONBOARDING - not enough data yet, build the base first",
}


# ------------------------------------------------------------- paths

def ig_home():
    return os.path.expanduser(os.environ.get("IG_HOME") or "~/IGStudio")


def data_dir():
    """IG_DATA_DIR, else the active account's folder, else IG_HOME."""
    env = os.environ.get("IG_DATA_DIR")
    if env:
        return os.path.expanduser(env)
    home = ig_home()
    try:
        with open(os.path.join(home, "active-account"), encoding="utf-8") as f:
            handle = f.read().strip().lstrip("@")
    except OSError:
        handle = ""
    if handle:
        acct = os.path.join(home, "accounts", handle)
        if os.path.isdir(acct):
            return acct
    return home


def path_in(name):
    return os.path.join(data_dir(), name)


def read_text(name):
    try:
        with open(path_in(name), encoding="utf-8") as f:
            return f.read()
    except OSError:
        return None


# ------------------------------------------------------------- numbers

def num(v):
    """'12,400' -> 12400.0, '1.2k' -> 1200.0, '38%' -> 38.0, '' -> None."""
    if v is None:
        return None
    s = str(v).strip().replace(",", "").replace(" ", "")
    if s in ("", "-", "--", "n/a", "N/A", "None", "null"):
        return None
    s = s.rstrip("%")
    mult = 1
    if s[-1:] in ("k", "K"):
        mult, s = 1000, s[:-1]
    elif s[-1:] in ("m", "M"):
        mult, s = 1000000, s[:-1]
    try:
        return float(s) * mult
    except ValueError:
        return None


def parse_date(s):
    try:
        return dt.date.fromisoformat(str(s).strip()[:10])
    except (ValueError, TypeError):
        return None


def median(vals):
    vals = [v for v in vals if v is not None]
    return statistics.median(vals) if vals else None


def fmt_int(x):
    return "-" if x is None else f"{int(round(x)):,}"


def fmt_signed(x):
    return "-" if x is None else f"{int(round(x)):+,}"


def fmt_pct(x, places=1):
    return "-" if x is None else f"{x:.{places}f}%"


# ------------------------------------------------------------- followers

def load_followers():
    """Rows sorted by date, one per date (last write wins), numbers parsed."""
    try:
        with open(path_in("followers.csv"), encoding="utf-8-sig", newline="") as f:
            raw = list(csv.DictReader(f))
    except OSError:
        return []
    by_date = {}
    for r in raw:
        d = parse_date(r.get("date"))
        n = num(r.get("followers"))
        if d is None or n is None:
            continue
        by_date[d] = {
            "date": d, "followers": int(n),
            "following": num(r.get("following")), "posts": num(r.get("posts")),
            "notes": (r.get("notes") or "").strip(),
        }
    return [by_date[d] for d in sorted(by_date)]


def save_followers(rows):
    path = path_in("followers.csv")
    os.makedirs(os.path.dirname(path), exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=".followers.", suffix=".csv", dir=os.path.dirname(path))
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="") as f:
            w = csv.writer(f)
            w.writerow(FOLLOWER_COLUMNS)
            for r in rows:
                w.writerow([
                    r["date"].isoformat(), int(r["followers"]),
                    "" if r.get("following") is None else int(r["following"]),
                    "" if r.get("posts") is None else int(r["posts"]),
                    r.get("notes") or "",
                ])
        os.replace(tmp, path)
    except BaseException:
        if os.path.exists(tmp):
            os.unlink(tmp)
        raise


def value_at(rows, day):
    """Follower count at the latest check-in on or before day, else None."""
    best = None
    for r in rows:
        if r["date"] <= day:
            best = r
        else:
            break
    return best


def window_growth(rows, end, days):
    """Net change over the last `days` ending at `end`, with the real span."""
    now = value_at(rows, end)
    base = value_at(rows, end - dt.timedelta(days=days))
    if now is None or base is None or base["date"] >= now["date"]:
        return None
    net = now["followers"] - base["followers"]
    span = (now["date"] - base["date"]).days
    rate = (net / base["followers"] * 100) if base["followers"] else None
    return {"net": net, "span_days": span, "rate_pct": rate,
            "from": base["date"].isoformat(), "to": now["date"].isoformat(),
            "start": base["followers"], "end": now["followers"]}


def weekly_series(rows, end, weeks=4):
    """Net gain for each of the last `weeks` 7-day blocks, newest first."""
    out = []
    for k in range(weeks):
        hi = end - dt.timedelta(days=7 * k)
        lo = hi - dt.timedelta(days=7)
        a, b = value_at(rows, lo), value_at(rows, hi)
        if a is None or b is None or a["date"] >= b["date"]:
            out.append(None)
        else:
            out.append(b["followers"] - a["followers"])
    return out


def daily_pace(rows, end):
    """Followers per day, from the widest window available up to 28 days."""
    for days in (28, 14, 7):
        g = window_growth(rows, end, days)
        if g and g["span_days"] >= 5:
            return g["net"] / g["span_days"], g["span_days"]
    if len(rows) >= 2:
        span = (rows[-1]["date"] - rows[0]["date"]).days
        if span > 0:
            return (rows[-1]["followers"] - rows[0]["followers"]) / span, span
    return None, 0


def next_milestone(followers):
    for m in MILESTONES:
        if m > followers:
            return m
    return None


def projection(rows, end):
    if not rows:
        return None
    current = value_at(rows, end) or rows[-1]
    m = next_milestone(current["followers"])
    pace, span = daily_pace(rows, end)
    out = {"current": current["followers"], "milestone": m,
           "per_day": pace, "pace_days": span, "days": None, "eta": None}
    if m is not None and pace and pace > 0:
        days = (m - current["followers"]) / pace
        out["days"] = int(round(days + 0.4999))
        out["eta"] = (current["date"] + dt.timedelta(days=out["days"])).isoformat()
    return out


def milestones_hit(rows):
    hit = []
    if not rows:
        return hit
    first = rows[0]
    for m in MILESTONES:
        for r in rows:
            if r["followers"] >= m:
                hit.append({"milestone": m, "date": r["date"].isoformat(),
                            "followers": r["followers"],
                            "before_tracking": r is first})
                break
    return hit


def trend_word(series):
    """This week vs the mean of the previous weeks that have data."""
    this, prev = series[0], [x for x in series[1:] if x is not None]
    if this is None or not prev:
        return None, None
    avg = sum(prev) / len(prev)
    if abs(this - avg) <= max(2, abs(avg) * 0.15):
        return "flat", avg
    return ("up" if this > avg else "down"), avg


# ------------------------------------------------------------- ledger

def _import_ledger():
    if "ledger" in sys.modules:
        return sys.modules["ledger"]
    for d in (os.path.join(HERE, "..", "ig-ledger"),
              os.path.expanduser("~/.claude/skills/ig-ledger")):
        if os.path.isfile(os.path.join(d, "ledger.py")):
            sys.path.insert(0, d)
            sys.dont_write_bytecode = True     # leave sibling folders as found
            try:
                import ledger  # noqa: F401
                return ledger
            except Exception:
                sys.path.remove(d)
    return None


def load_posts():
    """Ledger rows via ig-ledger's load_rows(); plain CSV read as a fallback."""
    lg = _import_ledger()
    if lg is not None:
        # ledger.py only knows IG_DATA_DIR, so point it at the resolved dir
        # (active account included) for this one call, then put it back.
        prev = os.environ.get("IG_DATA_DIR")
        os.environ["IG_DATA_DIR"] = data_dir()
        try:
            return lg.load_rows()
        except Exception:
            pass
        finally:
            if prev is None:
                os.environ.pop("IG_DATA_DIR", None)
            else:
                os.environ["IG_DATA_DIR"] = prev
    try:
        with open(path_in("posts.csv"), encoding="utf-8-sig", newline="") as f:
            return [{k: (v or "").strip() for k, v in r.items()} for r in csv.DictReader(f)]
    except OSError:
        return []


def load_snapshot_ids():
    try:
        with open(path_in("snapshots.csv"), encoding="utf-8-sig", newline="") as f:
            ids = set()
            for r in csv.DictReader(f):
                pid = (r.get("id") or r.get("post_id") or "").strip()
                if pid:
                    ids.add(pid)
            return ids
    except OSError:
        return set()


def load_formula_names():
    for p in (os.path.join(HERE, "..", "ig-reel", "hooks.json"),
              os.path.expanduser("~/.claude/skills/ig-reel/hooks.json")):
        try:
            with open(p, encoding="utf-8") as f:
                return {str(h["id"]): h["name"] for h in json.load(f)["hooks"]}
        except Exception:
            continue
    return {}


def is_trial(r):
    return (r.get("trial") or "").strip().lower() in ("yes", "y", "true", "1")


def is_collab(r):
    return "collab" in (r.get("notes") or "").lower()


def post_view(r):
    reach = num(r.get("reach"))
    follows = num(r.get("follows"))
    shares = num(r.get("shares"))
    return {
        "id": r.get("id", ""), "date": r.get("date", ""),
        "format": (r.get("format") or "").lower(), "theme": r.get("theme", ""),
        "hook_formula": r.get("hook_formula", ""),
        "first_line": r.get("first_line", ""),
        "views": num(r.get("views")), "reach": reach, "follows": follows,
        "shares": shares, "saves": num(r.get("saves")),
        "skip_rate": num(r.get("skip_rate")),
        "nonfollower_pct": num(r.get("nonfollower_pct")),
        "trial": is_trial(r), "collab": is_collab(r),
        "test_id": r.get("test_id", ""),
        "follows_per_reach": (follows / reach) if (follows is not None and reach) else None,
        "sends_per_reach": (shares / reach) if (shares is not None and reach) else None,
    }


def group_conversion(posts, key):
    """Pooled follows / reach per group, so one tiny post cannot dominate."""
    groups = {}
    for p in posts:
        k = p.get(key) or ""
        if not k or p["reach"] is None or p["follows"] is None or not p["reach"]:
            continue
        g = groups.setdefault(k, {"key": k, "n": 0, "reach": 0.0, "follows": 0.0})
        g["n"] += 1
        g["reach"] += p["reach"]
        g["follows"] += p["follows"]
    out = []
    for g in groups.values():
        g["follows_per_reach"] = g["follows"] / g["reach"] if g["reach"] else None
        g["thin"] = g["n"] < 3
        out.append(g)
    out.sort(key=lambda g: (g["follows_per_reach"] or 0), reverse=True)
    return out


# ------------------------------------------------------------- engaged.md

DATE_RE = re.compile(r"\b(20\d\d-\d\d-\d\d)\b")


def engaged_days(text):
    days = set()
    for m in DATE_RE.finditer(text or ""):
        d = parse_date(m.group(1))
        if d:
            days.add(d)
    return days


def first_trend(text):
    """The first bullet or heading under the title in trends.md, trimmed."""
    if not text:
        return None
    seen_title = False
    for line in text.splitlines():
        s = line.strip()
        if not s:
            continue
        if s.startswith("# ") and not seen_title:
            seen_title = True
            continue
        if s.startswith(("- ", "* ", "## ", "### ")) or re.match(r"^\d+[.)] ", s):
            s = re.sub(r"^(#+|[-*]|\d+[.)])\s*", "", s).strip()
            s = s.replace("**", "")
            if s and not s.lower().startswith(("updated", "region", "niche", "source")):
                return s[:70]
    return None


# ------------------------------------------------------------- analysis

def analyse(today, weeks=4):
    weeks = max(1, int(weeks))
    start = today - dt.timedelta(days=7 * weeks)
    frows = load_followers()
    rows = load_posts()
    posts = []
    for r in rows:
        d = parse_date(r.get("date"))
        if d is None or d <= start or d > today:
            continue
        p = post_view(r)
        p["_date"] = d
        posts.append(p)

    feed = [p for p in posts if p["format"] != "story"]
    reels = [p for p in feed if p["format"] == "reel"]
    measured = [p for p in feed if p["reach"] is not None]

    # followers
    growth = window_growth(frows, today, 7 * weeks)
    series = weekly_series(frows, today, weeks)
    trend, prev_avg = trend_word(series) if len(series) > 1 else (None, None)
    current = value_at(frows, today)

    # conversion across posts
    conv = [p for p in measured if p["follows_per_reach"] is not None]
    total_reach = sum(p["reach"] for p in conv)
    total_follows = sum(p["follows"] for p in conv)
    pooled_fpr = (total_follows / total_reach) if total_reach else None
    top_converters = sorted(conv, key=lambda p: p["follows_per_reach"], reverse=True)[:3]

    # non-follower share by week, oldest first
    nf_weeks = []
    for k in range(weeks - 1, -1, -1):
        hi = today - dt.timedelta(days=7 * k)
        lo = hi - dt.timedelta(days=7)
        vals = [p["nonfollower_pct"] for p in reels
                if lo < p["_date"] <= hi and p["nonfollower_pct"] is not None and not p["trial"]]
        nf_weeks.append({"week_ending": hi.isoformat(), "n": len(vals),
                         "median": median(vals)})

    # consistency, oldest first
    per_week = []
    for k in range(weeks - 1, -1, -1):
        hi = today - dt.timedelta(days=7 * k)
        lo = hi - dt.timedelta(days=7)
        per_week.append({"week_ending": hi.isoformat(),
                         "posts": sum(1 for p in feed if lo < p["_date"] <= hi),
                         "reels": sum(1 for p in reels if lo < p["_date"] <= hi)})
    posts_per_week = len(feed) / weeks

    # engagement round
    eng_text = read_text("engaged.md")
    eng = None
    if eng_text is not None:
        days = {d for d in engaged_days(eng_text) if start < d <= today}
        eng = {"days": len(days), "per_week": len(days) / weeks,
               "target_per_week": ENGAGE_TARGET_DAYS_PER_WEEK}

    non_trial_reels = [p for p in reels if not p["trial"]]
    signals = {
        "posts_per_week": posts_per_week,
        "median_skip_rate": median(p["skip_rate"] for p in reels),
        "median_nonfollower_pct": median(p["nonfollower_pct"] for p in non_trial_reels),
        "median_reach_per_follower": (
            median(p["reach"] for p in non_trial_reels if p["reach"] is not None)
            / current["followers"]
            if current and current["followers"] and
            any(p["reach"] is not None for p in non_trial_reels) else None),
        "follows_per_reach": pooled_fpr,
        "median_sends_per_reach": median(p["sends_per_reach"] for p in measured),
    }
    bottleneck = pick_bottleneck(signals, n_feed=len(feed), n_measured=len(measured),
                                 has_followers=bool(frows), n_ledger=len(rows))

    return {
        "data_dir": data_dir(), "today": today.isoformat(), "weeks": weeks,
        "window_start": start.isoformat(),
        "followers": {
            "current": current["followers"] if current else None,
            "checkins": len(frows), "growth": growth, "weekly": series,
            "trend": trend, "prev_weekly_avg": prev_avg,
        },
        "posts": {"total": len(posts), "feed": len(feed), "reels": len(reels),
                  "measured": len(measured),
                  "trials": sum(1 for p in posts if p["trial"]),
                  "collabs": sum(1 for p in posts if p["collab"])},
        "conversion": {
            "follows": total_follows, "reach": total_reach,
            "follows_per_reach": pooled_fpr,
            "top": [_slim(p) for p in top_converters],
            "by_format": group_conversion(measured, "format"),
            "by_theme": group_conversion(measured, "theme"),
            "by_formula": group_conversion(measured, "hook_formula"),
        },
        "nonfollower_by_week": nf_weeks,
        "consistency": {"per_week": per_week, "posts_per_week": posts_per_week,
                        "target": TARGET_POSTS_PER_WEEK},
        "engagement": eng,
        "signals": signals,
        "bottleneck": bottleneck,
        "_posts": posts, "_rows": rows,
    }


def _slim(p):
    return {k: p[k] for k in ("id", "date", "format", "theme", "hook_formula",
                              "reach", "follows", "follows_per_reach", "first_line")}


def pick_bottleneck(s, n_feed, n_measured, has_followers, n_ledger):
    """Return {name, reason, value, threshold, early}. Pipeline order."""
    if n_ledger == 0 and not has_followers:
        return {"name": "onboarding", "reason": "No posts logged and no follower check-ins yet.",
                "value": None, "threshold": None, "early": True}
    early = n_measured < EVIDENCE_MIN_POSTS

    ppw = s["posts_per_week"]
    if ppw < CONSISTENCY_MIN_POSTS_PER_WEEK:
        return {"name": "consistency",
                "reason": f"{ppw:.1f} posts a week. Floor is {CONSISTENCY_MIN_POSTS_PER_WEEK}, target {TARGET_POSTS_PER_WEEK}.",
                "value": ppw, "threshold": CONSISTENCY_MIN_POSTS_PER_WEEK, "early": early}

    skip = s["median_skip_rate"]
    if skip is not None and skip > RETENTION_MAX_SKIP_RATE:
        return {"name": "retention",
                "reason": f"Median reel skip rate {skip:.0f}%. Over {RETENTION_MAX_SKIP_RATE:.0f}% means most viewers leave in the first 3 seconds.",
                "value": skip, "threshold": RETENTION_MAX_SKIP_RATE, "early": early}

    nf = s["median_nonfollower_pct"]
    rpf = s["median_reach_per_follower"]
    if nf is not None and nf < REACH_MIN_NONFOLLOWER_PCT:
        return {"name": "reach",
                "reason": f"Median non-follower share {nf:.0f}%. Under {REACH_MIN_NONFOLLOWER_PCT:.0f}% means reels mostly reach people who already follow.",
                "value": nf, "threshold": REACH_MIN_NONFOLLOWER_PCT, "early": early}
    if nf is None and rpf is not None and rpf < REACH_MIN_REACH_PER_FOLLOWER:
        return {"name": "reach",
                "reason": f"Median reel reach is {rpf:.2f}x your follower count. Under {REACH_MIN_REACH_PER_FOLLOWER}x means it is not leaving your followers.",
                "value": rpf, "threshold": REACH_MIN_REACH_PER_FOLLOWER, "early": early}

    fpr = s["follows_per_reach"]
    if fpr is not None and fpr < CONVERSION_MIN_FOLLOWS_PER_REACH:
        return {"name": "conversion",
                "reason": f"{fpr * 100:.2f}% follows per reach. Under {CONVERSION_MIN_FOLLOWS_PER_REACH * 100:.1f}% means people see the reel and do not follow.",
                "value": fpr, "threshold": CONVERSION_MIN_FOLLOWS_PER_REACH, "early": early}

    # Nothing is under its line. Name the stage closest to its line, so the
    # week still has a focus. Margin = how far past the threshold, as a ratio.
    margins = {"consistency": ppw / CONSISTENCY_MIN_POSTS_PER_WEEK}
    if skip is not None:
        margins["retention"] = RETENTION_MAX_SKIP_RATE / max(skip, 1e-9)
    if nf is not None:
        margins["reach"] = nf / REACH_MIN_NONFOLLOWER_PCT
    elif rpf is not None:
        margins["reach"] = rpf / REACH_MIN_REACH_PER_FOLLOWER
    if fpr is not None:
        margins["conversion"] = fpr / CONVERSION_MIN_FOLLOWS_PER_REACH
    weakest = min(margins, key=margins.get)
    missing = [b for b in BOTTLENECKS if b not in margins]
    reason = (f"Nothing is under its line. {weakest} is the closest to it "
              f"({margins[weakest]:.1f}x the threshold).")
    if missing:
        reason += f" Not enough data to check: {', '.join(missing)}."
    return {"name": weakest, "reason": reason, "value": margins[weakest],
            "threshold": 1.0, "early": early, "healthy": True}


# ------------------------------------------------------------- plan

def top_formulas(rows, k=2):
    """Hook formulas ranked by mean views over the account median. Non-trial,
    non-story posts with views only. Formulas need at least 2 posts if any do."""
    posts = [post_view(r) for r in rows]
    posts = [p for p in posts if p["views"] is not None and not p["trial"]
             and p["format"] != "story" and p["hook_formula"]]
    med = median(p["views"] for p in posts)
    if not med:
        return []
    groups = {}
    for p in posts:
        groups.setdefault(p["hook_formula"], []).append(p["views"] / med)
    ranked = sorted(groups.items(), key=lambda kv: sum(kv[1]) / len(kv[1]), reverse=True)
    solid = [kv for kv in ranked if len(kv[1]) >= 2]
    use = solid if len(solid) >= k else ranked
    return [{"formula": f, "mult": sum(v) / len(v), "n": len(v)} for f, v in use[:k]]


def perf_due(rows, today, snap_ids):
    """Posts from the last PERF_DUE_MAX_DAYS days with no views and no snapshot."""
    due = []
    for r in rows:
        d = parse_date(r.get("date"))
        if d is None or (r.get("format") or "").lower() == "story":
            continue
        age = (today - d).days
        if 0 <= age <= PERF_DUE_MAX_DAYS and num(r.get("views")) is None \
                and r.get("id") not in snap_ids:
            due.append({"id": r.get("id"), "date": d.isoformat(), "age_days": age})
    due.sort(key=lambda x: x["age_days"], reverse=True)
    return due


def action(text, cmd, why):
    return {"action": text, "skill": cmd, "why": why}


def build_plan(a, today):
    b = a["bottleneck"]["name"]
    rows = a["_rows"]
    names = load_formula_names()
    has_voice = read_text("voice.md") is not None
    trend = first_trend(read_text("trends.md"))
    snaps = load_snapshot_ids()
    due = perf_due(rows, today, snaps)
    tops = top_formulas(rows)
    last_checkin = None
    fr = load_followers()
    if fr:
        last_checkin = fr[-1]["date"]

    if b == "onboarding" or (len(rows) < 3 and not tops):
        acts = []
        if not fr:
            acts.append(action("Log today's follower count so growth has a baseline",
                               "grow.py checkin --followers N",
                               "No check-ins yet. Without a baseline nothing can be measured."))
        if not has_voice:
            acts.append(action("Write voice.md from three of your own reels",
                               "/ig-reel", "Every script and caption reads it. Do this once."))
        acts += [
            action("Score your profile and fix the top two point losses",
                   "/ig-profile", "Every reel sends strangers here. It has to say what you post and for whom."),
            action("Plan your first 9 posts: 6 reels, 3 carousels, mixed themes",
                   "/ig-plan", "Nine is one full grid. Enough to show a visitor what they get by following."),
            action("Find 3 reels beating their account 3x+ in your niche",
                   "/ig-viral", "Start from evidence of what is working, not guesses."),
            action("20-minute engagement round, 5 days this week",
                   "/ig-comment", "Real comments on 10 accounts a day is the free way to get seen early."),
            action("Put the posts and the engagement rounds in your calendar",
                   "/ig-calendar", "A plan that is not in the calendar does not happen."),
        ]
        return {"mode": "onboarding", "bottleneck": b, "actions": acts[:MAX_ACTIONS]}

    acts = []
    if last_checkin is None or (today - last_checkin).days >= 7:
        acts.append(action("Check in your follower count", "grow.py checkin --followers N",
                           "Last check-in is over a week old." if last_checkin
                           else "No check-ins yet."))

    def formulas_text():
        if not tops:
            return "your best hook formulas"
        bits = []
        for t in tops:
            name = names.get(str(t["formula"]))
            bits.append(f"#{t['formula']}" + (f" {name}" if name else "") + f" ({t['mult']:.1f}x, n={t['n']})")
        return " and ".join(bits)

    if tops and tops[0]["mult"] >= 1.2:
        why = "Lean on the formulas that already beat your median views."
    elif tops:
        why = "No formula clearly beats your median yet. These are your best so far."
    else:
        why = "Log hook formulas in /ig-ledger so next week can pick on evidence."
    reels_line = action(f"3 reels using {formulas_text()}", "/ig-reel", why)

    if b == "consistency":
        acts += [
            action("Plan 4 posts this week, at least 3 reels, and stick to it", "/ig-plan",
                   a["bottleneck"]["reason"]),
            action("Cut one long video or call into a week of posts", "/ig-repurpose",
                   "The fastest way to fill the week without new ideas."),
            reels_line,
            action("Edit raw clips into reels in one batch session", "/ig-edit",
                   "Batching is how posting stays consistent."),
        ]
    elif b == "retention":
        acts += [
            action(f"Rewrite the first 2 seconds of the next 3 reels with {formulas_text()}",
                   "/ig-reel", a["bottleneck"]["reason"]),
            action("A/B test two hooks on one reel as Trial Reels", "/ig-test",
                   "Let strangers pick the hook. Skip rate decides."),
            action("Tighten the opening cut: start mid-action, text on screen at frame 1",
                   "/ig-edit", "Dead air at the start is the commonest cause of a high skip rate."),
        ]
    elif b == "reach":
        acts += [
            action("Ride " + (f"trend: {trend}" if trend else "one current trend in your niche"),
                   "/ig-trends", a["bottleneck"]["reason"]),
            action("1 trial reel with a new format to test on non-followers", "/ig-test",
                   "Trial Reels go to non-followers first. A miss costs nothing with followers."),
            action("1 collab pitch to a peer your size", "/ig-dm",
                   "A collab post shows on both grids and reaches both audiences."),
            reels_line,
            action("Pick a trending sound for one reel", "/ig-audio",
                   "Audio gives the reel a second door in, via the audio page."),
        ]
    elif b == "conversion":
        conv = a["conversion"]["top"]
        pin = ", ".join(p["id"] for p in conv) if conv else "your top 3 converters"
        acts += [
            action("Rewrite the name field and bio line one", "/ig-profile", a["bottleneck"]["reason"]),
            action(f"Pin {pin}: the posts that already turned viewers into followers",
                   "/ig-profile", "Pinned posts are what a visitor judges you on."),
            action("End each reel with one reason to follow (what they get next)", "/ig-caption",
                   "Viewers follow for more of the same. Tell them there is more."),
            reels_line,
        ]

    acts.append(action("Reply with a reel to the best question in your comments", "/ig-reply",
                       "The question is the hook, and the asker is notified."))
    eng = a["engagement"]
    if eng is None or eng["per_week"] < ENGAGE_TARGET_DAYS_PER_WEEK:
        acts.append(action(f"Engagement round {ENGAGE_TARGET_DAYS_PER_WEEK} days this week, comments in the first hour of peers' posts",
                           "/ig-comment",
                           "No engagement log found." if eng is None
                           else f"{eng['per_week']:.1f} days a week logged."))
    for d in due[:1]:
        acts.insert(1 if acts and acts[0]["skill"].startswith("grow.py") else 0,
                    action(f"Check {d['id']} ({d['age_days']}d old, no numbers yet)", "/ig-perf",
                           "Read it at 24h and 7d while it can still teach something."))

    acts = _dedupe(acts)[:MAX_ACTIONS - 1]
    acts.append(action("Put this week's actions in your calendar", "/ig-calendar",
                       "Plans that are scheduled get done."))
    return {"mode": "weekly", "bottleneck": b, "actions": acts}


def _dedupe(acts):
    seen, out = set(), []
    for x in acts:
        if x["action"] in seen:
            continue
        seen.add(x["action"])
        out.append(x)
    return out


# ------------------------------------------------------------- render

def render_checkin(rows, today, row, out):
    p = lambda s="": print(s, file=out)  # noqa: E731
    p(RULE)
    p(f"CHECK-IN  {row['date'].isoformat()}  {row['followers']:,} followers")
    p(RULE)
    for label, days in (("Week", 7), ("Month", 30)):
        g = window_growth(rows, row["date"], days)
        if g:
            p(f"{label:<6} {fmt_signed(g['net'])}  ({fmt_pct(g['rate_pct'], 2)})  "
              f"over {g['span_days']} days since {g['from']}")
        else:
            p(f"{label:<6} not enough history yet")
    series = weekly_series(rows, row["date"], 4)
    word, avg = trend_word(series)
    if word:
        n_prev = sum(1 for x in series[1:] if x is not None)
        p(f"Trend  {word}: {fmt_signed(series[0])} this week vs {avg:+.0f} a week "
          f"over the previous {n_prev}")
    pr = projection(rows, row["date"])
    p()
    if pr and pr["milestone"] and pr["days"]:
        p(f"PROJECTION  {pr['milestone']:,} in about {pr['days']} days (around {pr['eta']}),")
        p(f"at the last {pr['pace_days']} days' pace of {pr['per_day']:+.1f} a day.")
        p("A projection, not a promise. One reel that travels changes it.")
    elif pr and pr["milestone"]:
        p(f"PROJECTION  next milestone {pr['milestone']:,}. Not growing at the current pace,")
        p("so no date. Run `grow.py report` to see why.")
    else:
        p("PROJECTION  needs two check-ins a few days apart.")
    hit = [m for m in milestones_hit(rows) if m["date"] == row["date"].isoformat()
           and not m["before_tracking"]]
    for m in hit:
        p(f"MILESTONE  {m['milestone']:,} reached today.")


def render_report(a, out):
    p = lambda s="": print(s, file=out)  # noqa: E731
    f, c, names = a["followers"], a["conversion"], load_formula_names()
    p(RULE)
    p(f"GROWTH REPORT  {a['window_start']} to {a['today']}  ({a['weeks']} weeks)")
    p(RULE)
    g = f["growth"]
    if g:
        p(f"Followers  {g['start']:,} -> {g['end']:,}  {fmt_signed(g['net'])} "
          f"({fmt_pct(g['rate_pct'], 2)}), {g['net'] / max(g['span_days'], 1) * 7:+.0f} a week")
    elif f["current"] is not None:
        p(f"Followers  {f['current']:,}. One check-in in range, so no growth figure yet.")
    else:
        p("Followers  no check-ins. Run `grow.py checkin --followers N`.")
    if any(x is not None for x in f["weekly"]):
        p("Weekly     " + "  ".join(fmt_signed(x) for x in reversed(f["weekly"])) + "  (oldest to newest)")
    if f["trend"]:
        p(f"Trend      {f['trend']} vs the weeks before")
    p()
    pc = a["posts"]
    p(f"POSTS  {pc['feed']} feed posts ({pc['reels']} reels), {pc['measured']} with numbers, "
      f"{pc['trials']} trial reels, {pc['collabs']} collabs")
    p()
    p("WHAT CONVERTED  (follows per reach)")
    if c["follows_per_reach"] is not None:
        p(f"  All posts   {fmt_int(c['follows'])} follows / {fmt_int(c['reach'])} reach = "
          f"{c['follows_per_reach'] * 100:.2f}%")
        for t in c["top"]:
            fl = (t["first_line"] or "")[:40]
            p(f"  {t['id']:<6} {t['follows_per_reach'] * 100:5.2f}%  {fmt_int(t['follows']):>5} follows  "
              f"{t['format']:<8} {t['theme'] or '-':<10} {fl}")
        for label, key in (("format", "by_format"), ("theme", "by_theme"), ("formula", "by_formula")):
            rows = c[key][:4]
            if not rows:
                continue
            bits = []
            for gr in rows:
                name = f"#{gr['key']}" if key == "by_formula" else gr["key"]
                if key == "by_formula" and names.get(str(gr["key"])):
                    name += f" {names[str(gr['key'])]}"
                bits.append(f"{name} {gr['follows_per_reach'] * 100:.2f}% (n={gr['n']}{', thin' if gr['thin'] else ''})")
            p(f"  By {label:<8} " + "; ".join(bits))
    else:
        p("  No posts with both reach and follows logged. Add them with /ig-ledger.")
    p()
    p("NON-FOLLOWER SHARE  (median per week, reels, trials excluded)")
    p("  " + "  ".join(f"{w['week_ending'][5:]}: {fmt_pct(w['median'], 0)}" for w in a["nonfollower_by_week"]))
    p()
    cs = a["consistency"]
    p(f"CONSISTENCY  {cs['posts_per_week']:.1f} posts a week vs target {cs['target']}")
    p("  " + "  ".join(f"{w['week_ending'][5:]}: {w['posts']} ({w['reels']} reels)" for w in cs["per_week"]))
    e = a["engagement"]
    if e is None:
        p("ENGAGEMENT   no engaged.md, so no record of engagement rounds.")
    else:
        p(f"ENGAGEMENT   {e['days']} days logged in engaged.md, {e['per_week']:.1f} a week vs target {e['target_per_week']}")
    p()
    b = a["bottleneck"]
    p(RULE)
    p(f"BOTTLENECK  {BOTTLENECK_TEXT.get(b['name'], b['name'])}")
    p(f"  {b['reason']}")
    if b.get("early") and b["name"] != "onboarding":
        p(f"  Early read: fewer than {EVIDENCE_MIN_POSTS} posts with numbers. Treat it as a hunch.")
    p(RULE)
    p("Next: `grow.py plan` for this week's actions.")


def render_plan(plan, a, out):
    p = lambda s="": print(s, file=out)  # noqa: E731
    p(RULE)
    title = "ONBOARDING PLAN" if plan["mode"] == "onboarding" else "THIS WEEK'S GROWTH PLAN"
    p(f"{title}  week of {a['today']}")
    p(RULE)
    p(f"Bottleneck: {BOTTLENECK_TEXT.get(plan['bottleneck'], plan['bottleneck'])}")
    p()
    for i, x in enumerate(plan["actions"], 1):
        p(f"{i}. {x['action']}: {x['skill']}")
        p(f"   {x['why']}")
    p()
    p("Free growth only. No bought followers, no follow/unfollow, no pods, no bots.")


def render_milestones(rows, out):
    p = lambda s="": print(s, file=out)  # noqa: E731
    p(RULE)
    p("MILESTONES")
    p(RULE)
    hit = milestones_hit(rows)
    if not hit:
        p("None yet." if rows else "No check-ins yet. Run `grow.py checkin --followers N`.")
    for m in hit:
        tag = "  (already past at first check-in)" if m["before_tracking"] else ""
        p(f"{m['milestone']:>9,}  {m['date']}{tag}")
    if rows:
        nm = next_milestone(rows[-1]["followers"])
        if nm:
            p(f"Next: {nm:,} ({nm - rows[-1]['followers']:,} to go)")


def public(a):
    return {k: v for k, v in a.items() if not k.startswith("_")}


# ------------------------------------------------------------- CLI

def main(argv=None, out=None):
    out = out or sys.stdout
    ap = argparse.ArgumentParser(description="Free audience growth coach for Instagram.")
    ap.add_argument("--today", help="pin today's date, YYYY-MM-DD")
    sub = ap.add_subparsers(dest="cmd", required=True)

    c = sub.add_parser("checkin", help="log today's follower count")
    c.add_argument("--followers", required=True)
    c.add_argument("--following")
    c.add_argument("--posts")
    c.add_argument("--date")
    c.add_argument("--notes", default="")
    c.add_argument("--json", action="store_true")

    r = sub.add_parser("report", help="growth report and the one bottleneck")
    r.add_argument("--weeks", type=int, default=4)
    r.add_argument("--json", action="store_true")

    pl = sub.add_parser("plan", help="this week's growth actions")
    pl.add_argument("--weeks", type=int, default=4)
    pl.add_argument("--json", action="store_true")

    m = sub.add_parser("milestones", help="milestones hit, with dates")
    m.add_argument("--json", action="store_true")

    args = ap.parse_args(argv)
    today = parse_date(args.today) if args.today else dt.date.today()
    if today is None:
        ap.error("--today must be YYYY-MM-DD")

    if args.cmd == "checkin":
        d = parse_date(args.date) if args.date else today
        n = num(args.followers)
        if d is None:
            ap.error("--date must be YYYY-MM-DD")
        if n is None or n < 0:
            ap.error("--followers must be a number")
        rows = load_followers()
        row = {"date": d, "followers": int(n), "following": num(args.following),
               "posts": num(args.posts), "notes": args.notes}
        rows = [x for x in rows if x["date"] != d] + [row]
        rows.sort(key=lambda x: x["date"])
        save_followers(rows)
        if args.json:
            json.dump({"row": {**row, "date": d.isoformat()},
                       "week": window_growth(rows, d, 7), "month": window_growth(rows, d, 30),
                       "weekly": weekly_series(rows, d, 4), "projection": projection(rows, d)},
                      out, indent=2)
            print(file=out)
        else:
            render_checkin(rows, today, row, out)
        return 0

    if args.cmd == "milestones":
        rows = load_followers()
        if args.json:
            json.dump(milestones_hit(rows), out, indent=2)
            print(file=out)
        else:
            render_milestones(rows, out)
        return 0

    a = analyse(today, args.weeks)
    if args.cmd == "report":
        if args.json:
            json.dump(public(a), out, indent=2, default=str)
            print(file=out)
        else:
            render_report(a, out)
        return 0

    plan = build_plan(a, today)
    if args.json:
        json.dump({"bottleneck": a["bottleneck"], **plan}, out, indent=2, default=str)
        print(file=out)
    else:
        render_plan(plan, a, out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
