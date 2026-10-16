#!/usr/bin/env python3
"""
swipe.py - rank reels you collected by how far they beat their own account,
name the hook formula each one used, and write the swipe file.

The point of this script is one correction: raw views are not evidence. A
2,000,000-follower account doing 400,000 views had a quiet day. A 4,000-
follower account doing 400,000 views found something. This ranks on the
multiple over the account's own baseline, which is the only version of
"went viral" that tells you anything you can copy.

Input is a tab-separated file you fill in while you browse, one reel per row,
with a header line naming the columns:

    account   followers   median   views    hook
    @someone  48000       11000    412000   nobody tells you your first 30 flop

`median` is that account's typical recent views and is the better baseline.
If you only have `followers`, leave median out and the script says so.
`hook` is the first line of the reel, spoken or on screen, in their words.

Optional columns, kept as they are and passed on to viral.json so a planned
post can copy the reel: url, on_screen, length (seconds), structure (the beats
in one line), sound, cta, caption (its first line), lang, source
(instagram/youtube), posted (YYYY-MM-DD).

Or, from kweo: pass the files ig-kweo-reader's "reels" job wrote, one per
account. The script works out each account's median itself. Instagram's web
pages show likes but not views on other people's reels, so when most of an
account's reels have no view count, that account is ranked on likes against
its own median likes, and every row says which (`metric`).

Usage
  python3 swipe.py captured.tsv
  python3 swipe.py captured.tsv --out "$(python3 ~/.claude/skills/ig-account/account.py path)/swipe.md"
  python3 swipe.py captured.tsv --json
  python3 swipe.py --reader reader-*.json --out "$DATA/swipe.md"

--out writes swipe.md and, next to it, viral.json: every reel with an id
(V01 is the biggest outlier). IG Studio's planned posts point at those ids.
"""

import argparse
import datetime as dt
import json
import os
import re
import statistics
import sys
import unicodedata

HERE = os.path.dirname(os.path.abspath(__file__))
HOOKS = os.path.join(HERE, "..", "ig-reel", "hooks.json")


def _mark_class():
    """Every combining mark in the BMP, as the inside of a regex class.

    Devanagari vowel signs, Arabic harakat and decomposed accents are
    category M, which \\w does not match. Without them a Hindi word breaks
    into pieces at every vowel sign. ZWNJ and ZWJ sit inside words in Urdu,
    Persian and the Indic scripts, so they count as part of a word too.
    """
    ranges, start, prev = [], None, None
    for cp in range(0x0300, 0x10000):
        if unicodedata.category(chr(cp))[0] == "M":
            start = cp if start is None else start
            prev = cp
        elif start is not None:
            ranges.append((start, prev))
            start = None
    return "".join(re.escape(chr(a)) + ("-" + re.escape(chr(b)) if b > a else "")
                   for a, b in ranges) + "\u200c\u200d"


MARKS = _mark_class()
# Same word rule as hookscore.py: any script, marks kept inside the word.
WORD_RE = re.compile(r"(?:[^\W_]|[$%'’\-" + MARKS + r"])+")

try:                                              # optional: score the hooks too
    sys.path.insert(0, os.path.join(HERE, "..", "ig-reel"))
    from hookscore import run as score_hook       # noqa: E402
except Exception:                                 # ig-viral copied on its own
    score_hook = None


def load_formulas(path):
    try:
        d = json.load(open(path, encoding="utf-8"))
    except Exception:
        return None
    by_id = {h["id"]: h for h in d["hooks"]}
    order = d.get("classify_order") or sorted(by_id)
    return [(by_id[i]["id"], by_id[i]["name"],
             re.compile(by_id[i]["match"], re.IGNORECASE)) for i in order if i in by_id]


def classify(hook, formulas):
    if not formulas:
        return None, "unclassified"
    for fid, name, pattern in formulas:
        if pattern.search(hook):
            return fid, name
    return None, "unclassified"


def read_rows(path):
    raw = sys.stdin.read() if path == "-" else open(path, encoding="utf-8").read()
    lines = [l for l in raw.splitlines() if l.strip() and not l.lstrip().startswith("#")]
    if not lines:
        return []
    head = [c.strip().lower() for c in lines[0].split("\t")]
    if "views" in head and "hook" in head:
        cols, body = head, lines[1:]
    else:
        cols, body = ["account", "followers", "views", "hook"], lines
    rows = []
    for line in body:
        cells = line.split("\t")
        if len(cells) < len(cols):
            cells += [""] * (len(cols) - len(cells))
        r = dict(zip(cols, [c.strip() for c in cells]))
        try:
            r["views"] = int(re.sub(r"[^\d]", "", r.get("views", "")) or 0)
        except ValueError:
            continue
        for k in ("followers", "median"):
            digits = re.sub(r"[^\d]", "", r.get(k, "") or "")
            r[k] = int(digits) if digits else None
        r["metric"], r["count"] = "views", r["views"]
        if r["views"] and r.get("hook"):
            rows.append(r)
    return rows


def count(x):
    """12345, "12,345", "16.2K", "1.1M" -> int; anything else -> None. Never a guess."""
    if isinstance(x, bool):
        return None
    if isinstance(x, (int, float)):
        return int(x) if x >= 0 else None
    m = re.fullmatch(r"\s*([\d,]+(?:\.\d+)?)\s*([KkMm]?)\s*", str(x or ""))
    if not m:
        return None
    n = float(m.group(1).replace(",", ""))
    return int(round(n * {"": 1, "k": 1e3, "m": 1e6}[m.group(2).lower()]))


def first_line(caption):
    """A caption's opening words, without hashtags and mentions: the hook when the spoken one is unknown."""
    for line in str(caption or "").splitlines():
        text = re.sub(r"[#@][^\s#@]+", "", line).strip(" .·•-")
        text = re.sub(r"\s{2,}", " ", text)
        if text:
            return text[:160]
    return ""


def read_reader(paths):
    """Rows from ig-kweo-reader "reels" jobs, one JSON file per account.

    The median is the middle of that account's own reels (3 or more needed).
    Views when most reels show them, else likes. A reel without the number is
    left out; nothing is filled in.
    """
    rows, notes = [], []
    for path in paths:
        try:
            d = json.load(open(path, encoding="utf-8"))
        except (OSError, ValueError) as e:
            notes.append(f"{path}: unreadable ({e})")
            continue
        if not isinstance(d, dict):
            continue
        reels = [r for r in d.get("reels") or d.get("posts") or [] if isinstance(r, dict)]
        # the handle at the top, or on the reels (readers do not always put it in the same place)
        handle = str(d.get("handle") or next((r.get("account") or r.get("handle") for r in reels
                                                if r.get("account") or r.get("handle")), "")).strip().lstrip("@")
        with_views = [r for r in reels if count(r.get("views")) is not None]
        metric = "views" if reels and len(with_views) * 2 >= len(reels) else "likes"
        vals = [count(r.get(metric)) for r in reels if count(r.get(metric)) is not None]
        median = int(statistics.median(vals)) if len(vals) >= 3 else None
        if median is None:
            notes.append(f"@{handle}: fewer than 3 reels with {metric}, no median")
        for r in reels:
            n = count(r.get(metric))
            hook = str(r.get("hook") or "").strip() or first_line(r.get("first_line")) or first_line(r.get("caption"))
            if n is None or not hook:
                continue
            row = {"account": "@" + handle if handle else "", "followers": count(d.get("followers")),
                   "median": median, "metric": metric, "count": n, "views": count(r.get("views")),
                   "likes": count(r.get("likes")), "comments": count(r.get("comments")), "hook": hook,
                   "url": r.get("url") or "", "caption": first_line(r.get("caption")),
                   "on_screen": r.get("on_screen") or "", "sound": r.get("sound") or r.get("audio") or "",
                   "length": r.get("length_s") or "", "posted": r.get("date") or "", "source": "instagram"}
            rows.append(row)
    return rows, notes


def analyse(rows, formulas):
    used_median = any(r.get("median") for r in rows)
    for r in rows:
        r.setdefault("metric", "views")
        r.setdefault("count", r.get("views"))
        # Followers are a baseline for views only; likes need the account's own median.
        base = r.get("median") or (r.get("followers") if r["metric"] == "views" else None) or 0
        r["baseline"] = base
        r["outlier"] = round(r["count"] / base, 2) if base else None
        r["formula_id"], r["formula"] = classify(r["hook"], formulas)
        r["words"] = len(WORD_RE.findall(r["hook"]))
        if score_hook:
            _, overall, verdict, _ = score_hook(r["hook"])
            r["hook_score"], r["hook_verdict"] = round(overall, 1), verdict
        else:
            r["hook_score"], r["hook_verdict"] = None, None
    ranked = sorted(rows, key=lambda r: -(r["outlier"] or 0))
    for i, r in enumerate(ranked, 1):
        r["id"] = f"V{i:02d}"
    third = max(1, len(ranked) // 3)
    top, bottom = ranked[:third], ranked[-third:]

    def med(items, key):
        vals = [i[key] for i in items if i.get(key) is not None]
        return round(statistics.median(vals), 1) if vals else None

    counts = {}
    for r in top:
        counts[r["formula"]] = counts.get(r["formula"], 0) + 1
    return {
        "baseline": "account median" if used_median else "follower count",
        "n": len(ranked),
        "accounts": len({r.get("account", "") for r in ranked}),
        "reels": ranked,
        "top_formulas": sorted(counts.items(), key=lambda kv: -kv[1]),
        "top_hook_score": med(top, "hook_score"),
        "bottom_hook_score": med(bottom, "hook_score"),
        "top_words": med(top, "words"),
        "bottom_words": med(bottom, "words"),
        "unclassified": sum(1 for r in ranked if r["formula"] == "unclassified"),
    }


def render(a, out=sys.stdout):
    head = (f"SWIPE FILE  ·  {a['n']} reels  ·  {a['accounts']} accounts  ·  "
            f"baseline: {a['baseline']}")
    print("\n" + head, file=out)
    print("=" * max(len(head), 78), file=out)
    for r in a["reels"]:
        mult = f"{r['outlier']:.1f}x" if r["outlier"] else "   ?"
        score = f"{r['hook_score']:.0f}" if r["hook_score"] is not None else " -"
        fid = f"#{r['formula_id']:<2}" if r["formula_id"] else "-  "
        print(f"  {r['id']} {mult:>7}  hook {score:>3}  {fid} {r['formula'][:22]:<22} "
              f"{r.get('account', '')[:16]:<16} {r['count']:>9,} {r['metric']}", file=out)
        print(f"           \"{r['hook'][:96]}\"", file=out)
    print("-" * max(len(head), 78), file=out)
    print("WHAT IS WORKING IN THIS BATCH", file=out)
    if a["top_formulas"]:
        print("  top third by outlier:  "
              + ", ".join(f"{n} x{c}" for n, c in a["top_formulas"][:4]), file=out)
    if a["top_hook_score"] is not None:
        print(f"  median hook score:     top {a['top_hook_score']:.0f}  "
              f"vs bottom {a['bottom_hook_score']:.0f}", file=out)
    print(f"  median hook length:    top {a['top_words']} words  "
          f"vs bottom {a['bottom_words']} words", file=out)
    print(f"  unclassified:          {a['unclassified']} of {a['n']}. Read those by hand, "
          "they are where a formula you do not have yet is hiding.", file=out)
    print("\n  A hand-collected batch is evidence, not proof. Twelve reels shows you "
          "nothing;\n  forty across six accounts shows you something. Collect more before "
          "you believe it.\n", file=out)


def to_markdown(a):
    lines = ["# Swipe file", "",
             f"{a['n']} reels across {a['accounts']} accounts. "
             f"Ranked by multiple over {a['baseline']}.", ""]
    for r in a["reels"]:
        mult = f"{r['outlier']:.1f}x" if r["outlier"] else "?"
        lines += [f"## {r['id']}  {mult}  {r['formula']}  ({r.get('account', '')})",
                  f"- {r['metric']}: {r['count']:,}  baseline: {r['baseline']:,}",
                  f"- hook score: {r['hook_score']}  words: {r['words']}",
                  f"- hook: \"{r['hook']}\""]
        for k in ("on_screen", "length", "structure", "sound", "cta", "url"):
            if r.get(k):
                lines.append(f"- {k.replace('_', ' ')}: {r[k]}")
        lines.append("")
    return "\n".join(lines) + "\n"


KEEP = ("url", "on_screen", "structure", "sound", "cta", "caption", "lang", "source", "posted")


def to_viral(a, today=None):
    """viral.json: what a planned post copies. Every number here was captured, none made up."""
    reels = []
    for r in a["reels"]:
        row = {"id": r["id"], "account": r.get("account") or "", "followers": r.get("followers"),
               "median": r.get("median"), "metric": r["metric"], "views": r.get("views"),
               "likes": count(r.get("likes")), "comments": count(r.get("comments")), "multiple": r["outlier"],
               "hook": r["hook"], "formula_id": r["formula_id"], "formula": r["formula"],
               "hook_score": r["hook_score"], "words": r["words"]}
        digits = re.sub(r"[^\d.]", "", str(r.get("length") or ""))
        row["length_s"] = round(float(digits)) if re.fullmatch(r"\d+(\.\d+)?", digits) else None
        for k in KEEP:
            if r.get(k):
                row[k] = r[k]
        reels.append(row)
    return {"version": 1, "made": (today or dt.date.today()).isoformat(), "baseline": a["baseline"],
            "n": a["n"], "accounts": a["accounts"],
            "top_formulas": [{"formula": n, "count": c} for n, c in a["top_formulas"]],
            "reels": reels}


def main():
    ap = argparse.ArgumentParser(description="Rank collected reels by outlier multiple.")
    ap.add_argument("input", nargs="?", default="-", help="TSV file, or - for stdin")
    ap.add_argument("--reader", nargs="+", metavar="JSON",
                    help="ig-kweo-reader 'reels' outputs, one per account, instead of a TSV")
    ap.add_argument("--hooks", default=HOOKS, help="path to ig-reel/hooks.json")
    ap.add_argument("--out", help="also write the swipe file as markdown here")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    notes = []
    if args.reader:
        rows, notes = read_reader(args.reader)
    else:
        rows = read_rows(args.input)
    for n in notes:
        print("note:", n, file=sys.stderr)
    if not rows:
        print("no usable rows. Need a tab-separated file with at least views and hook.",
              file=sys.stderr)
        sys.exit(2)
    formulas = load_formulas(args.hooks)
    a = analyse(rows, formulas)
    if not formulas:
        print("note: hooks.json not found, formulas not named. Pass --hooks.", file=sys.stderr)
    if score_hook is None:
        print("note: hookscore.py not importable, hook scores skipped.", file=sys.stderr)

    if args.json:
        print(json.dumps(a, indent=2, ensure_ascii=False))
    else:
        render(a)
    if args.out:
        path = os.path.abspath(os.path.expanduser(args.out))
        os.makedirs(os.path.dirname(path), exist_ok=True)
        open(path, "w", encoding="utf-8").write(to_markdown(a))
        print(f"wrote {path}", file=sys.stderr)
        vpath = os.path.join(os.path.dirname(path), "viral.json")
        with open(vpath, "w", encoding="utf-8") as f:
            json.dump(to_viral(a), f, ensure_ascii=False, indent=2)
            f.write("\n")
        print(f"wrote {vpath}", file=sys.stderr)


if __name__ == "__main__":
    main()
