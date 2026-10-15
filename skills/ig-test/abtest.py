#!/usr/bin/env python3
"""
abtest.py - run a real A/B test of two hooks for the same reel, using
Instagram Trial Reels, and say honestly whether one of them won.

Why this exists: hookscore.py catches bad hooks well and cannot pick between
two decent ones (AUC 0.56, a coin flip is 0.50). Nothing that reads text can.
The audience can. Trial Reels show a reel only to people who do not follow
you, so two trials of the same video with different hooks is a split test
with strangers as the panel.

What this does NOT do: post anything. You post both trials by hand. This
script keeps the books in the shared ledger (posts.csv in the active account's
data folder, see /ig-account) and does the arithmetic.

The noise check is a two-proportion z-test. On a few hundred views, a 2 point
gap in skip rate is usually noise, and the report says so. One test is one
data point. Several tests are a pattern.

Usage
  python3 abtest.py new --a "hook line A" --b "hook line B" [--formula-a N]
                        [--formula-b N] [--theme T] [--length S]
  python3 abtest.py record T001 A --views 1200 --shares 14 --skip-rate 38.5
  python3 abtest.py report T001 [--json]
  python3 abtest.py list [--json]
"""

import argparse
import datetime
import importlib.util
import json
import math
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))

try:                                              # the shared ledger, ig-ledger
    sys.path.insert(0, os.path.join(HERE, "..", "ig-ledger"))
    import ledger                                 # noqa: E402
except Exception:                                 # ig-test copied on its own
    ledger = None

# hookscore.py lives in ig-reel. Sibling folder first, then the installed pack.
HOOKSCORE_DIRS = [
    os.path.join(HERE, "..", "ig-reel"),
    os.path.expanduser("~/.claude/skills/ig-reel"),
]

MIN_VIEWS = 300          # below this per variant, nothing is called
Z_CRIT = 1.96            # two-sided, 95%
VARIANTS = ("A", "B")
METRIC_FIELDS = {        # cli flag dest -> ledger column
    "views": "views", "shares": "shares", "likes": "likes", "comments": "comments",
    "saves": "saves", "follows": "follows", "skip_rate": "skip_rate",
    "avg_watch": "avg_watch_s",
}


# ---------------------------------------------------------------- helpers

def load_hookscore(dirs=None):
    """Return hookscore.run, or None if ig-reel is not installed."""
    for d in (HOOKSCORE_DIRS if dirs is None else dirs):
        path = os.path.join(d, "hookscore.py")
        if not os.path.isfile(path):
            continue
        try:
            spec = importlib.util.spec_from_file_location("_ig_hookscore", path)
            mod = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(mod)
            return mod.run
        except Exception:
            continue
    return None


def need_ledger():
    if ledger is None:
        print("ig-ledger not found. abtest.py needs ../ig-ledger/ledger.py "
              "to keep its records.", file=sys.stderr)
        sys.exit(2)
    return ledger


def count(text):
    """'12,400' -> 12400, '1.2k' -> 1200. Counts are whole numbers."""
    t = str(text).strip().lower().replace(",", "").replace("_", "")
    mult = 1
    if t.endswith("k"):
        t, mult = t[:-1], 1000
    elif t.endswith("m"):
        t, mult = t[:-1], 1000000
    try:
        n = float(t) * mult
    except ValueError:
        raise argparse.ArgumentTypeError(f"not a number: {text!r}")
    if n < 0:
        raise argparse.ArgumentTypeError(f"cannot be negative: {text!r}")
    return int(round(n))


def percent(text):
    t = str(text).strip().rstrip("%")
    try:
        f = float(t)
    except ValueError:
        raise argparse.ArgumentTypeError(f"not a percentage: {text!r}")
    if not 0 <= f <= 100:
        raise argparse.ArgumentTypeError(f"skip rate is 0 to 100, got {text!r}")
    return f


def seconds(text):
    try:
        f = float(str(text).strip().rstrip("s"))
    except ValueError:
        raise argparse.ArgumentTypeError(f"not seconds: {text!r}")
    if f < 0:
        raise argparse.ArgumentTypeError(f"cannot be negative: {text!r}")
    return f


def num(v):
    """Ledger cell -> float, or None when empty or junk."""
    if v is None or str(v).strip() == "":
        return None
    try:
        return float(str(v).replace(",", "").strip().rstrip("%"))
    except ValueError:
        return None


def fmt_num(v):
    return "" if v is None else (f"{v:g}" if isinstance(v, float) else str(v))


def norm_test_id(t):
    t = t.strip().upper()
    if t.isdigit():
        t = "T%03d" % int(t)
    return t


def test_rows(rows, test_id):
    """{'A': row, 'B': row} for one test. Missing variants are absent."""
    out = {}
    for r in rows:
        if (r.get("test_id") or "").upper() == test_id:
            v = (r.get("variant") or "").upper()
            if v in VARIANTS and v not in out:
                out[v] = r
    return out


def next_test_id(rows):
    nums = []
    for r in rows:
        m = re.fullmatch(r"T(\d+)", (r.get("test_id") or "").strip().upper())
        if m:
            nums.append(int(m.group(1)))
    return "T%03d" % (max(nums, default=0) + 1)


# ------------------------------------------------------------- statistics

def two_prop_z(x1, n1, x2, n2):
    """Pooled two-proportion z statistic for x1/n1 vs x2/n2. Positive means
    the first proportion is higher. 0.0 when there is no variance to test."""
    if n1 <= 0 or n2 <= 0:
        return 0.0
    p1, p2 = x1 / n1, x2 / n2
    p = (x1 + x2) / (n1 + n2)
    se = math.sqrt(p * (1 - p) * (1 / n1 + 1 / n2))
    if se == 0:
        return 0.0
    return (p1 - p2) / se


def count_z(c1, c2):
    """Rough z for two raw counts (Poisson approximation). Used for views,
    which have no denominator. Weaker evidence than the proportions."""
    if c1 + c2 <= 0:
        return 0.0
    return (c1 - c2) / math.sqrt(c1 + c2)


def p_two_sided(z):
    return math.erfc(abs(z) / math.sqrt(2))


def variant_stats(row):
    s = {k: num(row.get(col)) for k, col in METRIC_FIELDS.items()}
    v = s["views"]
    s["held"] = None
    s["hold_rate"] = None
    s["share_rate"] = None
    if v:
        if s["skip_rate"] is not None:
            s["held"] = v * (1 - s["skip_rate"] / 100)
            s["hold_rate"] = 1 - s["skip_rate"] / 100
        if s["shares"] is not None:
            s["share_rate"] = s["shares"] / v
    return s


def analyse(test_id, rows):
    """The whole comparison as a dict. No printing here."""
    pair = test_rows(rows, test_id)
    res = {"test_id": test_id, "variants": {}, "metrics": [], "verdict": None,
           "winner": None, "decided_on": None, "reasons": [], "status": None}
    for v in VARIANTS:
        if v not in pair:
            res["status"] = "missing"
            res["reasons"].append(f"variant {v} is not in the ledger")
            return res
        r = pair[v]
        res["variants"][v] = {"id": r.get("id"), "hook": r.get("first_line", ""),
                              "formula": r.get("hook_formula", ""),
                              **variant_stats(r)}
    a, b = res["variants"]["A"], res["variants"]["B"]
    if not a["views"] or not b["views"]:
        res["status"] = "waiting"
        res["verdict"] = None
        res["reasons"].append("waiting for numbers: record views for both variants")
        return res
    res["status"] = "ready"

    va, vb = a["views"], b["views"]

    # 1. primary: held past 3s (= 1 - skip rate). Higher hold wins.
    if a["skip_rate"] is not None and b["skip_rate"] is not None:
        z = two_prop_z(a["held"], va, b["held"], vb)
        res["metrics"].append({"name": "held past 3s", "key": "hold", "a": a["hold_rate"],
                               "b": b["hold_rate"], "z": z, "p": p_two_sided(z),
                               "role": "primary"})
    # 2. shares per view
    if a["shares"] is not None and b["shares"] is not None and (a["shares"] or b["shares"]):
        z = two_prop_z(a["shares"], va, b["shares"], vb)
        res["metrics"].append({"name": "shares per view", "key": "shares",
                               "a": a["share_rate"], "b": b["share_rate"], "z": z,
                               "p": p_two_sided(z),
                               "role": "primary" if not res["metrics"] else "secondary"})
    # 3. views (rough: Instagram decides the trial audience size, not you)
    z = count_z(va, vb)
    res["metrics"].append({"name": "views", "key": "views", "a": va, "b": vb, "z": z,
                           "p": p_two_sided(z),
                           "role": "primary" if not res["metrics"] else "tiebreak"})

    for m in res["metrics"]:
        m["significant"] = abs(m["z"]) >= Z_CRIT
        m["leader"] = "A" if m["z"] > 0 else ("B" if m["z"] < 0 else None)

    small = [v for v in VARIANTS if res["variants"][v]["views"] < MIN_VIEWS]
    if small:
        res["verdict"] = "TOO CLOSE"
        res["reasons"].append(
            f"variant {' and '.join(small)} has under {MIN_VIEWS} views. "
            "Too few strangers saw it to call anything")
        return res

    decider = next((m for m in res["metrics"] if m["significant"]), None)
    if decider is None:
        res["verdict"] = "TOO CLOSE"
        res["reasons"].append(f"no metric clears |z| >= {Z_CRIT}. "
                              "The gap is the size noise makes on its own")
        return res

    res["winner"] = decider["leader"]
    res["verdict"] = f"WINNER {decider['leader']}"
    res["decided_on"] = decider["name"]
    if decider["role"] != "primary":
        res["reasons"].append(f"{res['metrics'][0]['name']} was too close, so this was "
                              f"decided on {decider['name']}, which is weaker evidence")
    for m in res["metrics"]:
        if m is not decider and m["significant"] and m["leader"] != decider["leader"]:
            res["reasons"].append(f"{m['name']} clearly favours {m['leader']}. "
                                  "Mixed signal, treat this win as soft")
    return res


# -------------------------------------------------------------- rendering

RULE = "=" * 70
THIN = "-" * 70


def cell(x, spec="g", suffix=""):
    return "-" if x is None else format(x, spec) + suffix


def render_report(res, out=sys.stdout):
    print(f"\nA/B TEST {res['test_id']}", file=out)
    print(RULE, file=out)
    if res["status"] == "missing":
        for r in res["reasons"]:
            print(f"  {r}", file=out)
        print("", file=out)
        return
    for v in VARIANTS:
        d = res["variants"][v]
        hook = d["hook"] if len(d["hook"]) <= 60 else d["hook"][:57] + "..."
        tag = f"  ({d['formula']})" if d["formula"] else ""
        print(f"  {v}  \"{hook}\"{tag}", file=out)
    if res["status"] == "waiting":
        print(THIN, file=out)
        print("  Waiting for numbers. After 24 hours, record both:", file=out)
        print(f"    python3 abtest.py record {res['test_id']} A --views N --shares N "
              "--skip-rate F", file=out)
        print("", file=out)
        return

    a, b = res["variants"]["A"], res["variants"]["B"]
    print(THIN, file=out)
    print(f"  {'':<18}{'A':>12}{'B':>12}", file=out)
    print(f"  {'views':<18}{fmt_num(int(a['views'])):>12}{fmt_num(int(b['views'])):>12}",
          file=out)
    print(f"  {'skip rate':<18}{cell(a['skip_rate'], '.1f', '%'):>12}"
          f"{cell(b['skip_rate'], '.1f', '%'):>12}", file=out)
    ra = None if a["share_rate"] is None else a["share_rate"] * 1000
    rb = None if b["share_rate"] is None else b["share_rate"] * 1000
    print(f"  {'shares per 1k':<18}{cell(ra, '.1f'):>12}{cell(rb, '.1f'):>12}", file=out)
    for label, key in (("likes", "likes"), ("comments", "comments"), ("saves", "saves"),
                       ("follows", "follows"), ("avg watch s", "avg_watch")):
        if a[key] is None and b[key] is None:
            continue
        print(f"  {label:<18}{cell(a[key]):>12}{cell(b[key]):>12}", file=out)

    print(THIN, file=out)
    print("  NOISE CHECK  (two-sided, |z| >= 1.96 is the bar)", file=out)
    for m in res["metrics"]:
        mark = "clear" if m["significant"] else "noise"
        lead = f"leans {m['leader']}" if m["leader"] else "dead even"
        print(f"  {m['role']:<10}{m['name']:<17} z = {m['z']:+5.2f}   p = {m['p']:.3f}"
              f"   {mark}, {lead}", file=out)
    if res["metrics"] and res["metrics"][-1]["key"] == "views":
        print("  (views is a rough count test. Instagram sizes the trial audience, "
              "not the hook alone.)", file=out)

    print(RULE, file=out)
    print(f"  VERDICT  {res['verdict']}"
          + (f"   on {res['decided_on']}" if res["decided_on"] else ""), file=out)
    for r in res["reasons"]:
        print(f"  - {r}.", file=out)
    print("", file=out)
    if res["winner"]:
        w, l = res["winner"], "B" if res["winner"] == "A" else "A"
        print(f"  Share {w} to your followers from the trial reel's menu.", file=out)
        print(f"  Leave {l} as it is. Its hook is logged as a learning, not a failure.",
              file=out)
        print(f"  Ledger notes updated: {w} 'won {res['test_id']}', "
              f"{l} 'lost {res['test_id']}'.", file=out)
    else:
        print("  Neither hook proved itself. Share the one you like better, or the one", file=out)
        print("  with more views, and do not read anything into it. If both are still", file=out)
        print("  climbing, wait another 24 hours and record again.", file=out)
    print("\n  One test is one data point. After several, /ig-audit shows which", file=out)
    print("  formulas win for this account. The final call is yours.\n", file=out)


# --------------------------------------------------------------- commands

def cmd_new(args, out=sys.stdout):
    lg = need_ledger()
    rows = lg.load_rows()
    tid = next_test_id(rows)
    today = datetime.date.today().isoformat()
    score = load_hookscore()

    hooks = {"A": (args.a.strip(), args.formula_a), "B": (args.b.strip(), args.formula_b)}
    if not hooks["A"][0] or not hooks["B"][0]:
        print("both hooks need text", file=sys.stderr)
        sys.exit(2)
    if hooks["A"][0].lower() == hooks["B"][0].lower():
        print("A and B are the same line. That is not a test.", file=sys.stderr)
        sys.exit(2)

    scores, ids = {}, {}
    for v in VARIANTS:
        line, formula = hooks[v]
        if score:
            _, overall, verdict, flags = score(line)
            scores[v] = {"score": round(overall, 1), "verdict": verdict, "flags": flags}
        ids[v] = lg.add_row(date=today, format="reel", theme=args.theme or "",
                            hook_formula=formula or "", first_line=line,
                            length_s=fmt_num(args.length) if args.length is not None else "",
                            trial="yes", test_id=tid, variant=v)

    if args.json:
        print(json.dumps({"test_id": tid, "rows": ids, "hooks": {v: hooks[v][0] for v in VARIANTS},
                          "scores": scores or None}, indent=2, ensure_ascii=False), file=out)
        return

    print(f"\nNEW A/B TEST {tid}", file=out)
    print(RULE, file=out)
    for v in VARIANTS:
        line, formula = hooks[v]
        tag = f"  formula {formula}" if formula else ""
        print(f"  {v}  {ids[v]}  \"{line}\"{tag}", file=out)
        if v in scores:
            s = scores[v]
            print(f"       hookscore {s['score']:.0f}  {s['verdict']}", file=out)
            for f in s["flags"]:
                print(f"       dealbreaker: {f}", file=out)
    if scores:
        weak = [v for v in VARIANTS if scores[v]["verdict"] == "WEAK"]
        if weak:
            print(f"\n  {' and '.join(weak)} scored WEAK. Fix it before you spend a trial on it.",
                  file=out)
        print("\n  hookscore cannot pick between two decent hooks. That is why you are", file=out)
        print("  testing. Ignore the gap between the scores.", file=out)
    else:
        print("\n  (hookscore.py not found, hooks not scored. Install ig-reel to get it.)",
              file=out)

    print(THIN, file=out)
    print("  CHECKLIST, before you post", file=out)
    print("  [ ] Same video after the hook. Only the first line changes.", file=out)
    print("  [ ] Post both as Trial Reels: tap 'Trial' on the share screen.", file=out)
    print("      Needs a professional account (creator or business).", file=out)
    print("  [ ] Post both within the same hour, at your normal time of day.", file=out)
    print("  [ ] Same caption, same audio, same cover. Or the test is about those.", file=out)
    print("  [ ] Do not share either to followers yet. Turn off auto-share if offered.",
          file=out)
    print("  [ ] Come back after 24 hours. Open each trial's insights and run:", file=out)
    print(f"        python3 abtest.py record {tid} A --views N --shares N --skip-rate F", file=out)
    print(f"        python3 abtest.py record {tid} B --views N --shares N --skip-rate F", file=out)
    print(f"        python3 abtest.py report {tid}", file=out)
    print("\n  Nothing has been posted. You post both by hand.\n", file=out)


def cmd_record(args, out=sys.stdout):
    lg = need_ledger()
    tid = norm_test_id(args.test_id)
    variant = args.variant.strip().upper()
    if variant not in VARIANTS:
        print("variant is A or B", file=sys.stderr)
        sys.exit(2)
    pair = test_rows(lg.load_rows(), tid)
    if variant not in pair:
        print(f"no variant {variant} for {tid} in the ledger. Run abtest.py list.",
              file=sys.stderr)
        sys.exit(2)
    fields = {}
    for dest, col in METRIC_FIELDS.items():
        val = getattr(args, dest)
        if val is not None:
            # The trailing % tells the ledger 0.5 means 0.5%, not a fraction.
            fields[col] = fmt_num(val) + ("%" if col == "skip_rate" else "")
    lg.update_row(pair[variant]["id"], **fields)
    if args.json:
        print(json.dumps({"test_id": tid, "variant": variant, "id": pair[variant]["id"],
                          "updated": fields}, indent=2), file=out)
        return
    shown = ", ".join(f"{k} {v}" for k, v in fields.items())
    print(f"{tid} {variant} ({pair[variant]['id']}): {shown}", file=out)
    other = "B" if variant == "A" else "A"
    if other in pair and not num(pair[other].get("views")):
        print(f"Now record {other}, then run: python3 abtest.py report {tid}", file=out)
    else:
        print(f"Run: python3 abtest.py report {tid}", file=out)


def write_notes(lg, res):
    """Tag the winner and loser rows. Replaces any earlier tag for this test."""
    if not res["winner"]:
        return
    tid = res["test_id"]
    for v in VARIANTS:
        rid = res["variants"][v]["id"]
        row = next(r for r in lg.load_rows() if r["id"] == rid)
        old = row.get("notes") or ""
        kept = re.sub(r"\s*;?\s*\b(?:won|lost) " + re.escape(tid) + r"\b", "", old).strip(" ;")
        tag = f"{'won' if v == res['winner'] else 'lost'} {tid}"
        lg.update_row(rid, notes=f"{kept}; {tag}" if kept else tag)


def cmd_report(args, out=sys.stdout):
    lg = need_ledger()
    tid = norm_test_id(args.test_id)
    res = analyse(tid, lg.load_rows())
    if res["status"] == "missing" and not res["variants"]:
        print(f"no test {tid} in the ledger. Run abtest.py list.", file=sys.stderr)
        sys.exit(2)
    write_notes(lg, res)
    if args.json:
        print(json.dumps(res, indent=2, ensure_ascii=False), file=out)
        return
    render_report(res, out)


def test_status(pair, test_id):
    if any(v not in pair for v in VARIANTS):
        return "incomplete"
    tag = re.compile(r"\b(?:won|lost) " + re.escape(test_id) + r"\b")
    if any(tag.search(pair[v].get("notes") or "") for v in VARIANTS):
        return "decided"
    if all(num(pair[v].get("views")) for v in VARIANTS):
        return "ready"
    return "waiting for numbers"


def cmd_list(args, out=sys.stdout):
    lg = need_ledger()
    rows = lg.load_rows()
    ids = []
    for r in rows:
        t = (r.get("test_id") or "").strip().upper()
        if t and t not in ids:
            ids.append(t)
    items = []
    for t in ids:
        pair = test_rows(rows, t)
        winner = next((v for v in VARIANTS if v in pair and
                       re.search(r"\bwon " + re.escape(t) + r"\b", pair[v].get("notes") or "")),
                      None)
        items.append({"test_id": t, "status": test_status(pair, t), "winner": winner,
                      "date": next((pair[v].get("date") for v in VARIANTS if v in pair), ""),
                      "hooks": {v: pair[v].get("first_line", "") for v in VARIANTS if v in pair}})
    if args.json:
        print(json.dumps(items, indent=2, ensure_ascii=False), file=out)
        return
    print("\nA/B TESTS", file=out)
    print(RULE, file=out)
    if not items:
        print("  none yet. Start one: python3 abtest.py new --a \"...\" --b \"...\"\n", file=out)
        return
    for it in items:
        status = it["status"] + (f", {it['winner']} won" if it["winner"] else "")
        print(f"  {it['test_id']}  {it['date'] or '':<10}  {status}", file=out)
        for v, h in it["hooks"].items():
            h = h if len(h) <= 56 else h[:53] + "..."
            print(f"        {v}  \"{h}\"", file=out)
    print("", file=out)


# ------------------------------------------------------------------- main

def build_parser():
    ap = argparse.ArgumentParser(description="A/B test two hooks with Instagram Trial Reels.")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("new", help="start a test and log both variants")
    p.add_argument("--a", required=True, help="hook line A")
    p.add_argument("--b", required=True, help="hook line B")
    p.add_argument("--formula-a", help="hooks.json formula id or name for A")
    p.add_argument("--formula-b", help="hooks.json formula id or name for B")
    p.add_argument("--theme")
    p.add_argument("--length", type=seconds, help="reel length in seconds")
    p.add_argument("--json", action="store_true")

    p = sub.add_parser("record", help="enter one variant's 24h numbers")
    p.add_argument("test_id")
    p.add_argument("variant")
    p.add_argument("--views", type=count, required=True)
    p.add_argument("--shares", type=count)
    p.add_argument("--likes", type=count)
    p.add_argument("--comments", type=count)
    p.add_argument("--saves", type=count)
    p.add_argument("--follows", type=count)
    p.add_argument("--skip-rate", type=percent, help="0-100, % who skipped in the first 3s")
    p.add_argument("--avg-watch", type=seconds, help="average watch time, seconds")
    p.add_argument("--json", action="store_true")

    p = sub.add_parser("report", help="compare A and B and call it, or not")
    p.add_argument("test_id")
    p.add_argument("--json", action="store_true")

    p = sub.add_parser("list", help="every test and where it stands")
    p.add_argument("--json", action="store_true")
    return ap


def main(argv=None, out=sys.stdout):
    args = build_parser().parse_args(argv)
    {"new": cmd_new, "record": cmd_record, "report": cmd_report,
     "list": cmd_list}[args.cmd](args, out)


if __name__ == "__main__":
    main()
