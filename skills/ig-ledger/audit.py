#!/usr/bin/env python3
"""
audit.py - read the ledger and do the /ig-audit maths in code, not by hand.

Raw views mostly measure how many people already follow the account. So the
unit here is the outlier multiple: a post's views over the account's own
median. Then the rates that say why: sends per reach, saves per reach,
follows per reach, skip rate, and the share of reach from non-followers.

Trial reels are shown to non-followers only, so they are not a normal day for
the account. They are kept out of the median and out of the rankings, and
listed on their own at the end.

Usage
  python3 audit.py
  python3 audit.py --format reel --since 2026-06-01
  python3 audit.py --json
"""

import argparse
import json
import os
import statistics
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import ledger  # noqa: E402

HOOKS_PATHS = (
    os.path.join(HERE, "..", "ig-reel", "hooks.json"),
    os.path.expanduser("~/.claude/skills/ig-reel/hooks.json"),
)

# How many posts before a pattern means anything. Under 10, one lucky post
# moves every mean on the page. By 30 the top and bottom fifths each hold
# enough posts that a difference between them is probably not noise.
TRUST_MIN = 10
VISIBLE_MIN = 30

# A group mean from fewer posts than this gets marked "thin".
GROUP_MIN = 3

# Profile problem: the reel travelled but the profile did not convert.
# - "Travelled" = at least half of reach came from people who do not follow.
#   Below that the post mostly went to the existing audience, and follows
#   per reach is low by construction (they already follow).
# - "Did not convert" = fewer than 2 follows per 1,000 accounts reached
#   (0.2%). A reel that reaches strangers and earns a profile visit usually
#   lands somewhere around 0.5% to 1%. Under 0.2% the attention arrived and
#   the profile let it leave.
# These are rules of thumb, not Meta numbers. Tune them if your niche runs
# hot or cold, but keep the two-part test: a no-view post is a hook problem,
# a views-but-no-follows post is a profile problem.
PROFILE_NONFOLLOWER_MIN = 50.0
PROFILE_FOLLOWS_PER_REACH_MAX = 0.002
# The account-level flag needs this many travelling posts before it fires.
PROFILE_MIN_POSTS = 3

LENGTH_BUCKETS = (("<15s", 0, 15), ("15-30s", 15, 30), ("30-60s", 30, 60), ("60s+", 60, None))


def load_formulas():
    for path in HOOKS_PATHS:
        try:
            with open(path, encoding="utf-8") as f:
                return {str(h["id"]): h["name"] for h in json.load(f)["hooks"]}
        except Exception:
            continue
    return {}


def num(v):
    return ledger.parse_number(v)


def ratio(a, b):
    if a is None or not b:
        return None
    return a / b


def mean(vals):
    vals = [v for v in vals if v is not None]
    return statistics.mean(vals) if vals else None


def length_bucket(s):
    if s is None:
        return "unknown"
    for name, lo, hi in LENGTH_BUCKETS:
        if s >= lo and (hi is None or s < hi):
            return name
    return "unknown"


def enrich(r, median):
    views, reach = num(r["views"]), num(r["reach"])
    shares, saves, follows = num(r["shares"]), num(r["saves"]), num(r["follows"])
    nf = num(r["nonfollower_pct"])
    fpr = ratio(follows, reach)
    profile = (nf is not None and fpr is not None
               and nf >= PROFILE_NONFOLLOWER_MIN and fpr < PROFILE_FOLLOWS_PER_REACH_MAX)
    return {
        "id": r["id"], "date": r["date"], "format": r["format"], "theme": r["theme"],
        "hook_formula": r["hook_formula"], "first_line": r["first_line"],
        "length_s": num(r["length_s"]), "trial": r["trial"] == "yes",
        "test_id": r["test_id"], "variant": r["variant"],
        "views": views, "reach": reach, "shares": shares, "saves": saves, "follows": follows,
        "outlier": round(views / median, 2) if views is not None and median else None,
        "sends_per_reach": ratio(shares, reach),
        "saves_per_reach": ratio(saves, reach),
        "follows_per_reach": fpr,
        "skip_rate": num(r["skip_rate"]),
        "nonfollower_pct": nf,
        "avg_watch_s": num(r["avg_watch_s"]),
        "profile_problem": profile,
    }


def group(posts, key, label=None):
    buckets = {}
    for p in posts:
        k = key(p)
        buckets.setdefault(k, []).append(p)
    out = []
    for k, items in buckets.items():
        out.append({
            "group": label(k) if label else k,
            "n": len(items),
            "mean_outlier": round(mean(p["outlier"] for p in items), 2),
            "mean_sends_per_reach": mean(p["sends_per_reach"] for p in items),
            "thin": len(items) < GROUP_MIN,
        })
    return sorted(out, key=lambda g: (-g["mean_outlier"], -g["n"]))


def compare(top, bottom, field):
    a = [p[field] for p in top if p[field] is not None]
    b = [p[field] for p in bottom if p[field] is not None]
    if len(a) < 2 or len(b) < 2:
        return None
    return {"top": statistics.mean(a), "bottom": statistics.mean(b), "n_top": len(a), "n_bottom": len(b)}


def analyse(rows, fmt=None, since=None, formulas=None):
    formulas = formulas or {}
    n_stories = 0
    if fmt:
        rows = [r for r in rows if r["format"] == fmt]
    else:
        # Stories live 24 hours and go mostly to followers. Their views are a
        # different number from a reel's, and mixing them in drags the median
        # down so every reel looks like a hit. Audit them with --format story.
        n_stories = sum(1 for r in rows if r["format"] == "story")
        rows = [r for r in rows if r["format"] != "story"]
    if since:
        rows = [r for r in rows if r["date"] and r["date"] >= since]
    with_views = [r for r in rows if num(r["views"]) is not None]
    base_rows = [r for r in with_views if r["trial"] != "yes"]
    median = statistics.median(num(r["views"]) for r in base_rows) if base_rows else None

    posts = [enrich(r, median) for r in base_rows]
    trials = [enrich(r, median) for r in with_views if r["trial"] == "yes"]
    ranked = sorted(posts, key=lambda p: -(p["outlier"] or 0))
    # Five and five once there are ten. Below that, split so no post is in both.
    k_bottom = min(5, len(ranked) // 2)
    top = ranked[:min(5, len(ranked) - k_bottom)]
    bottom = ranked[::-1][:k_bottom]

    def hook_label(k):
        if not k:
            return "(not logged)"
        name = formulas.get(k)
        return f"#{k} {name}" if name else f"#{k}"

    groups = {}
    if posts:
        groups = {
            "hook_formula": group(posts, lambda p: p["hook_formula"], hook_label),
            "format": group(posts, lambda p: p["format"] or "(unknown)"),
            "length": group(posts, lambda p: length_bucket(p["length_s"])),
            "theme": group(posts, lambda p: p["theme"] or "(not logged)"),
        }

    travelled = [p for p in posts if p["nonfollower_pct"] is not None
                 and p["nonfollower_pct"] >= PROFILE_NONFOLLOWER_MIN
                 and p["follows"] is not None and p["reach"]]
    pooled = (sum(p["follows"] for p in travelled) / sum(p["reach"] for p in travelled)
              if travelled else None)
    profile = {
        "posts_flagged": [p["id"] for p in posts if p["profile_problem"]],
        "travelled_posts": len(travelled),
        "pooled_follows_per_reach": pooled,
        "flag": (len(travelled) >= PROFILE_MIN_POSTS and pooled is not None
                 and pooled < PROFILE_FOLLOWS_PER_REACH_MAX),
        "thresholds": {"nonfollower_pct_min": PROFILE_NONFOLLOWER_MIN,
                       "follows_per_reach_max": PROFILE_FOLLOWS_PER_REACH_MAX},
    }

    n = len(posts)
    if n < TRUST_MIN:
        confidence = "too_few"
    elif n < VISIBLE_MIN:
        confidence = "early"
    else:
        confidence = "visible"

    dates = sorted(p["date"] for p in posts + trials if p["date"])
    return {
        "n": n,
        "n_logged": len(rows),
        "n_without_views": len(rows) - len(with_views),
        "n_trials": len(trials),
        "n_stories_excluded": n_stories,
        "median_views": median,
        "date_from": dates[0] if dates else None,
        "date_to": dates[-1] if dates else None,
        "filter": {"format": fmt, "since": since},
        "confidence": confidence,
        "posts": sorted(posts, key=lambda p: (p["date"] or "", p["id"])),
        "top": top,
        "bottom": bottom,
        "compare": {f: compare(top, bottom, f) for f in
                    ("skip_rate", "nonfollower_pct", "sends_per_reach",
                     "saves_per_reach", "follows_per_reach", "avg_watch_s")},
        "groups": groups,
        "profile": profile,
        "trials": trials,
    }


# ---------------------------------------------------------------- render

def f_pct(x, scale=1, places=0):
    if x is None:
        return "-"
    return f"{x * scale:.{places}f}%"


def f_int(x):
    return "-" if x is None else f"{int(x):,}"


def f_mult(x):
    return "   ?" if x is None else f"{x:.1f}x"


def clip(s, n=72):
    return s if len(s) <= n else s[:n - 3].rstrip() + "..."


def post_line(p, formulas):
    hook = f"#{p['hook_formula']}" if p["hook_formula"] else "-"
    return (f"  {f_mult(p['outlier']):>6}  {p['id']:<6} {p['date'] or '-':<10} "
            f"{(p['format'] or '-')[:8]:<8} {hook:>4} {f_int(p['views']):>9}  "
            f"{f_pct(p['nonfollower_pct']):>5} {f_pct(p['skip_rate']):>5} "
            f"{f_pct(p['sends_per_reach'], 100, 2):>6} {f_pct(p['saves_per_reach'], 100, 2):>6} "
            f"{f_pct(p['follows_per_reach'], 100, 2):>6}")


COLS = (f"  {'mult':>6}  {'id':<6} {'date':<10} {'format':<8} {'hook':>4} {'views':>9}  "
        f"{'nonf':>5} {'skip':>5} {'sends':>6} {'saves':>6} {'follow':>6}")


def render(a, formulas=None, out=None):
    out = out or sys.stdout
    formulas = formulas or {}
    P = lambda *s: print(*s, file=out)  # noqa: E731
    span = f"{a['date_from']} to {a['date_to']}" if a["date_from"] else "no dates"
    med = f"{a['median_views']:,.0f}" if a["median_views"] is not None else "-"
    scope = []
    if a["filter"]["format"]:
        scope.append(a["filter"]["format"] + " only")
    if a["filter"]["since"]:
        scope.append("since " + a["filter"]["since"])
    head = (f"AUDIT  ·  n={a['n']} posts with views  ·  {span}  ·  median views {med}"
            + ("  ·  " + ", ".join(scope) if scope else ""))
    width = max(len(head), 86)
    P("\n" + head)
    P("=" * width)

    if a["n"] == 0:
        P("  No posts with views in the ledger yet. Nothing to audit.")
        P("  Add numbers with `ledger.py update P0001 --views ...` or import a Meta export.")
        if a["n_trials"]:
            P(f"  ({a['n_trials']} trial reels have views, but trials do not set the baseline.)")
        P()
        return

    if a["confidence"] == "too_few":
        P(f"  n={a['n']}. Under {TRUST_MIN} posts the patterns below cannot be trusted yet.")
        P("  One lucky post moves every mean on this page. Read the numbers, not the story.")
    elif a["confidence"] == "early":
        P(f"  n={a['n']}. Early signal. Treat the group means as hints until you pass {VISIBLE_MIN}.")
    else:
        P(f"  n={a['n']}. Enough posts that patterns are visible. Still check each group's n.")
    notes = []
    if a["n_trials"]:
        notes.append(f"{a['n_trials']} trial reels kept out of the median (listed at the end)")
    if a.get("n_stories_excluded"):
        notes.append(f"{a['n_stories_excluded']} stories left out, audit them with --format story")
    if a["n_without_views"]:
        notes.append(f"{a['n_without_views']} logged posts have no views yet")
    for n in notes:
        P(f"  {n}.")
    P("  Rates are per reach. nonf = share of reach from non-followers.")

    P()
    P("ALL POSTS")
    P(COLS)
    for p in a["posts"]:
        P(post_line(p, formulas))

    P()
    P(f"TOP {len(a['top'])} BY OUTLIER MULTIPLE")
    for p in a["top"]:
        P(post_line(p, formulas))
        if p["first_line"]:
            P(f"          \"{clip(p['first_line'])}\"")
    if a["bottom"]:
        P()
        P(f"BOTTOM {len(a['bottom'])}")
        for p in a["bottom"]:
            P(post_line(p, formulas))
            if p["first_line"]:
                P(f"          \"{clip(p['first_line'])}\"")

    rows = []
    labels = {"skip_rate": ("skip rate", 1, 0), "nonfollower_pct": ("non-follower reach", 1, 0),
              "sends_per_reach": ("sends per reach", 100, 2),
              "saves_per_reach": ("saves per reach", 100, 2),
              "follows_per_reach": ("follows per reach", 100, 2)}
    for field, (label, scale, places) in labels.items():
        c = a["compare"].get(field)
        if c:
            rows.append(f"  {label:<20} top {f_pct(c['top'], scale, places):>7}   "
                        f"bottom {f_pct(c['bottom'], scale, places):>7}   "
                        f"(n {c['n_top']} vs {c['n_bottom']})")
    c = a["compare"].get("avg_watch_s")
    if c:
        rows.append(f"  {'avg watch':<20} top {c['top']:>6.1f}s   bottom {c['bottom']:>6.1f}s   "
                    f"(n {c['n_top']} vs {c['n_bottom']})")
    if rows:
        P()
        P(f"TOP {len(a['top'])} vs BOTTOM {len(a['bottom'])} (means)")
        for r in rows:
            P(r)
        if a["compare"].get("skip_rate"):
            P("  Skip rate is the closest thing insights give you to the hook's grade.")

    titles = {"hook_formula": "BY HOOK FORMULA", "format": "BY FORMAT",
              "length": "BY LENGTH", "theme": "BY THEME"}
    for key, title in titles.items():
        gs = a["groups"].get(key) or []
        if len(gs) < 2 and not (gs and gs[0]["group"] not in ("(not logged)", "unknown")):
            continue
        P()
        P(f"{title}  (mean outlier multiple)")
        for g in gs:
            thin = "  thin" if g["thin"] else ""
            P(f"  {g['group'][:30]:<30} {g['mean_outlier']:>5.1f}x   n={g['n']:<3} "
              f"sends {f_pct(g['mean_sends_per_reach'], 100, 2):>6}{thin}")

    pr = a["profile"]
    P()
    P("PROFILE CHECK")
    nf_min = f"{PROFILE_NONFOLLOWER_MIN:.0f}%"
    fpr_max = f"{PROFILE_FOLLOWS_PER_REACH_MAX * 100:.1f}%"
    if pr["travelled_posts"] == 0:
        P(f"  No post has both non-follower % and follows logged with reach. Cannot tell")
        P("  a hook problem from a profile problem yet. Log non-follower % and follows.")
    else:
        P(f"  {pr['travelled_posts']} posts reached mostly non-followers (>= {nf_min}). "
          f"Pooled follows per reach: {f_pct(pr['pooled_follows_per_reach'], 100, 2)}.")
        if pr["flag"]:
            P(f"  PROFILE PROBLEM. The reels travel and the profile does not convert "
              f"(under {fpr_max}).")
            P("  Stop rewriting hooks. Go to /ig-profile.")
        elif pr["travelled_posts"] < PROFILE_MIN_POSTS:
            P(f"  Too few travelling posts to call it (need {PROFILE_MIN_POSTS}).")
        else:
            P(f"  Converting fine (at or above {fpr_max}). If views are low, it is the hook.")
        if pr["posts_flagged"]:
            P("  Posts that travelled and converted under " + fpr_max + ": "
              + ", ".join(pr["posts_flagged"]))

    if a["trials"]:
        P()
        P("TRIAL REELS  (non-followers only, not in the median)")
        P(COLS)
        for p in a["trials"]:
            test = f"  {p['test_id']}{p['variant']}" if p["test_id"] else ""
            P(post_line(p, formulas) + test)
        P("  Multiple is against the main median, so read it loosely.")

    P("-" * width)
    if a["confidence"] == "too_few":
        P(f"  n={a['n']}. Keep logging. At {TRUST_MIN} this starts to mean something, "
          f"at {VISIBLE_MIN} you can act on it.")
    else:
        P(f"  n={a['n']}. Hand the hook formula and theme groups with n>={GROUP_MIN} "
          "to /ig-plan.")
    P()


def main(argv=None):
    ap = argparse.ArgumentParser(description="Audit the ledger: outlier multiples and rates.")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--format", choices=ledger.FORMATS)
    ap.add_argument("--since", help="YYYY-MM-DD, only posts on or after this date")
    args = ap.parse_args(argv)
    since = None
    if args.since:
        since = ledger.parse_date(args.since)
        if not since:
            print(f"error: --since must be YYYY-MM-DD, got {args.since!r}", file=sys.stderr)
            return 2
    formulas = load_formulas()
    a = analyse(ledger.load_rows(), args.format, since, formulas)
    if args.json:
        print(json.dumps(a, indent=2, ensure_ascii=False))
    else:
        render(a, formulas)
    return 0


if __name__ == "__main__":
    sys.exit(main())
