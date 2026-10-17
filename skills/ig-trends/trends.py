#!/usr/bin/env python3
"""
trends.py - log what is trending, let old trends die, and blend region-wide
trends with the user's niche into ranked "bridge" ideas.

The judgement is Claude's and the user's. This file does the parts that
should come out the same every time: how fast a trend is moving, how much of
it is left, whether it is safe to touch, and the order of the board.

Nobody can promise a reel goes viral. This ranks bets. It does not make them.

Storage is a plain CSV at $DATA/trends.csv. The board is written to
$DATA/trends.md so /ig-plan and /ig-reel can read it.

$DATA is: $IG_DATA_DIR if set. Else, if $IG_HOME/active-account names a
handle and $IG_HOME/accounts/<handle>/ exists, that folder. Else $IG_HOME.
$IG_HOME defaults to ~/IGStudio.

Usage
  python3 trends.py add --source google --region IN --kind topic \\
      --name "ITR filing deadline" --rank 3 --growth "+400%" --first-seen 2026-10-13
  python3 trends.py add --scope niche --source instagram --region IN --kind format \\
      --name "clause read-aloud with red pen" --niche-match 3
  python3 trends.py blend --niche "freelance contracts" --top 10
  python3 trends.py blend --niche "freelance contracts" --json
  python3 trends.py list [--region IN] [--json]
  python3 trends.py prune [--dry-run]
"""

import argparse
import csv
import datetime as dt
import json
import math
import os
import re
import sys
import tempfile

COLUMNS = ["id", "added", "scope", "source", "region", "kind", "name", "rank",
           "growth", "first_seen", "niche_match", "safety", "url", "notes"]
SOURCES = ("google", "tiktok", "youtube", "instagram", "news", "x")
KINDS = ("topic", "hashtag", "song", "format", "meme")
SCOPES = ("region", "niche")
SAFETY = ("auto", "ok", "flag", "exclude")

# Days until a trend has lost half its pull, and days until it is dead.
# Memes and news topics burn out in 3 to 7 days. Songs ride 2 to 4 weeks.
# Formats outlast both because they are a shape, not a moment.
HALF_LIFE = {"meme": 4, "topic": 4, "hashtag": 7, "song": 18, "format": 30}
LIFESPAN = {"meme": 10, "topic": 10, "hashtag": 21, "song": 35, "format": 75}

# Reels are the default output. How naturally each kind becomes one.
FORMAT_FIT = {"song": 3, "meme": 3, "format": 3, "hashtag": 2, "topic": 2}

# A starting formula id from ig-reel/hooks.json per kind. /ig-reel can change it.
FORMULA = {
    "topic": (22, "Contrarian Flip"),
    "meme": (21, "Mid-Sentence Start"),
    "song": (13, "Before And After, On Screen"),
    "format": (9, "The Steal"),
    "hashtag": (3, "Nobody Tells You"),
}

# Brand safety. "exclude" words mean someone got hurt: never ride it.
# "flag" words mean politics, religion or a fight: only with a clear reason.
EXCLUDE_WORDS = [
    "death", "dead", "dies", "died", "killed", "kills", "murder", "rape",
    "suicide", "crash", "accident", "attack", "terror", "terrorist", "bomb",
    "blast", "shooting", "shot dead", "stampede", "earthquake", "flood",
    "cyclone", "landslide", "tsunami", "wildfire", "disaster", "tragedy",
    "victims", "funeral", "rip", "passed away", "missing child", "hostage",
    "war", "massacre", "collapse", "derail", "derailment", "outbreak",
]
FLAG_WORDS = [
    "election", "vote", "votes", "poll result", "minister", "parliament",
    "president", "prime minister", "pm", "party", "bjp", "congress", "aap",
    "modi", "rahul gandhi", "trump", "biden", "harris", "senate", "protest",
    "riot", "strike", "bandh", "religion", "religious", "temple", "mosque",
    "church", "hindu", "muslim", "christian", "sikh", "caste", "communal",
    "court", "verdict", "arrest", "arrested", "scam", "lawsuit", "ban",
    "boycott", "controversy", "border", "army", "military", "israel", "gaza",
    "ukraine", "russia", "pakistan", "china", "visa", "immigration",
]

ID_RE = re.compile(r"^T(\d+)$")
WORD_RE = re.compile(r"[^\W_]+", re.UNICODE)
STOP = {"the", "and", "for", "with", "from", "that", "this", "your", "you",
        "what", "how", "why", "are", "was", "who", "new", "2025", "2026"}


# ---------------------------------------------------------------- storage

def ig_home():
    return os.path.expanduser(os.environ.get("IG_HOME") or "~/IGStudio")


def data_dir():
    """IG_DATA_DIR, else the active account's folder if it exists, else IG_HOME."""
    env = os.environ.get("IG_DATA_DIR")
    if env:
        return os.path.expanduser(env)
    home = ig_home()
    try:
        with open(os.path.join(home, "active-account"), encoding="utf-8") as f:
            handle = f.read().strip().lstrip("@")
    except OSError:
        handle = ""
    if handle and "/" not in handle and handle not in (".", ".."):
        acct = os.path.join(home, "accounts", handle)
        if os.path.isdir(acct):
            return acct
    return home


def csv_path():
    return os.path.join(data_dir(), "trends.csv")


def board_path():
    return os.path.join(data_dir(), "trends.md")


def load_rows():
    path = csv_path()
    if not os.path.exists(path):
        return []
    with open(path, encoding="utf-8-sig", newline="") as f:
        return [{c: (r.get(c) or "").strip() for c in COLUMNS} for r in csv.DictReader(f)]


def save_rows(rows):
    path = csv_path()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=".trends.", suffix=".csv", dir=os.path.dirname(path))
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


def write_text(path, text):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=".trends.", suffix=".md", dir=os.path.dirname(path))
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write(text)
    os.replace(tmp, path)


def next_id(rows):
    n = 0
    for r in rows:
        m = ID_RE.match(r.get("id", ""))
        if m:
            n = max(n, int(m.group(1)))
    return f"T{n + 1:04d}"


# ---------------------------------------------------------------- values

def today_from(s=None):
    s = s or os.environ.get("IG_TODAY")
    return dt.date.fromisoformat(s) if s else dt.date.today()


def parse_date(s):
    try:
        return dt.date.fromisoformat(str(s).strip()[:10])
    except (TypeError, ValueError):
        return None


def parse_growth(v):
    """'+250%' -> 250.0, 'Breakout' -> 5000.0, '-30%' -> -30.0, '2x' -> 100.0."""
    if v is None:
        return None
    s = str(v).strip().lower().replace(",", "")
    if not s:
        return None
    if "breakout" in s:
        return 5000.0
    m = re.match(r"^([+-]?\d+(?:\.\d+)?)\s*x$", s)
    if m:
        return (float(m.group(1)) - 1) * 100
    m = re.match(r"^([+-]?\d+(?:\.\d+)?)\s*([km]?)\s*%?$", s)
    if not m:
        return None
    n = float(m.group(1)) * {"": 1, "k": 1000, "m": 1000000}[m.group(2)]
    return n


def parse_int(v):
    try:
        return int(str(v).strip().lstrip("#"))
    except (TypeError, ValueError):
        return None


def age_days(row, today):
    d = parse_date(row.get("first_seen")) or parse_date(row.get("added"))
    return max(0, (today - d).days) if d else 0


def _has(text, word):
    return re.search(r"(?<![^\W_])" + re.escape(word) + r"(?![^\W_])", text) is not None


def safety_of(row):
    """(level, words). level: ok | flag | exclude. A manual setting wins."""
    manual = (row.get("safety") or "auto").lower()
    text = f"{row.get('name', '')} {row.get('notes', '')}".lower()
    ex = [w for w in EXCLUDE_WORDS if _has(text, w)]
    fl = [w for w in FLAG_WORDS if _has(text, w)]
    if manual in ("ok", "flag", "exclude"):
        return manual, ex + fl
    if ex:
        return "exclude", ex
    if fl:
        return "flag", fl
    if row.get("source") == "news":
        return "flag", ["news story, check what it is about"]
    return "ok", []


def momentum(row, today):
    """0-100. Rank and growth say how hot it was. Age and kind say how much is left."""
    kind = row.get("kind") or "topic"
    rank = parse_int(row.get("rank"))
    growth = parse_growth(row.get("growth"))
    rank_s = 1 / (1 + (rank - 1) / 10) if rank and rank > 0 else 0.5
    if growth is None:
        growth_s = 0.4
    elif growth <= 0:
        growth_s = 0.1
    else:
        growth_s = min(1.0, math.log1p(growth / 100) / math.log1p(20))
    age = age_days(row, today)
    hl = HALF_LIFE.get(kind, 7)
    decay = 0.5 ** (age / hl)
    score = round(100 * (0.5 * rank_s + 0.5 * growth_s) * decay)
    if growth is not None and growth < 0:
        phase = "fading"
    elif age <= 0.5 * hl:
        phase = "rising"
    elif age <= 1.5 * hl:
        phase = "peaking"
    else:
        phase = "fading"
    days_left = max(0, LIFESPAN.get(kind, 14) - age)
    return {"momentum": score, "phase": phase, "age": age, "days_left": days_left,
            "half_life": hl}


def expired(row, today):
    return age_days(row, today) > LIFESPAN.get(row.get("kind") or "topic", 14)


def words(text):
    return {w for w in WORD_RE.findall((text or "").lower()) if len(w) >= 4 and w not in STOP}


def niche_fit(row, niche_words):
    """0-3. The user's or Claude's number if given. Else a word-overlap guess."""
    n = parse_int(row.get("niche_match"))
    if n is not None:
        return max(0, min(3, n)), "set"
    overlap = words(f"{row.get('name')} {row.get('notes')}") & niche_words
    return (2 if overlap else 1), "guess"


def read_proof(path):
    """Non-empty bullets under '## Proof I can use' in voice.md."""
    try:
        with open(path, encoding="utf-8") as f:
            text = f.read()
    except OSError:
        return []
    out, inside = [], False
    for line in text.splitlines():
        if line.startswith("## "):
            inside = line.strip().lower().startswith("## proof i can use")
            continue
        if inside:
            m = re.match(r"^\s*[-*]\s+(.+?)\s*$", line)
            if m and m.group(1).strip():
                out.append(m.group(1).strip())
    return out


def pick_proof(proofs, *texts):
    if not proofs:
        return None
    want = set()
    for t in texts:
        want |= words(t)
    best = max(proofs, key=lambda p: len(words(p) & want))
    return best if words(best) & want else proofs[0]


# ---------------------------------------------------------------- blend

def blend(rows, niche, today, region=None, angles=None, proofs=None, top=10):
    niche_words = words(niche)
    live = [r for r in rows if not expired(r, today)
            and (not region or r.get("region", "").upper() == region.upper())]
    region_rows = [r for r in live if (r.get("scope") or "region") == "region"]
    niche_rows = [r for r in live if r.get("scope") == "niche"]

    angle_list = [{"name": a, "momentum": 50, "row": None} for a in (angles or [])]
    for r in niche_rows:
        m = momentum(r, today)
        angle_list.append({"name": r["name"], "momentum": m["momentum"], "row": r})
    if not angle_list:
        angle_list = [{"name": niche, "momentum": 50, "row": None}]

    bridges, excluded = [], []
    for r in region_rows:
        m = momentum(r, today)
        level, hits = safety_of(r)
        if level == "exclude":
            excluded.append({"id": r["id"], "name": r["name"], "words": hits})
            continue
        fit, fit_src = niche_fit(r, niche_words)
        kind = r.get("kind") or "topic"
        ffit = FORMAT_FIT.get(kind, 2)
        for a in angle_list:
            proof = pick_proof(proofs or [], r["name"], a["name"], niche)
            score = (0.40 * m["momentum"]
                     + 0.30 * fit / 3 * 100
                     + 0.10 * a["momentum"]
                     + 0.10 * (100 if proof else 40)
                     + 0.10 * ffit / 3 * 100)
            if level == "flag":
                score *= 0.7
            if m["phase"] == "fading":
                score *= 0.8
            fid, fname = FORMULA[kind] if kind in FORMULA else FORMULA["topic"]
            if a["row"] is not None and a["row"].get("kind") == "format":
                fid, fname = FORMULA["format"]
            bridges.append({
                "score": round(score),
                "trend_id": r["id"], "trend": r["name"], "kind": kind,
                "source": r.get("source", ""), "region": r.get("region", ""),
                "momentum": m["momentum"], "phase": m["phase"], "age": m["age"],
                "days_left": m["days_left"], "half_life": m["half_life"],
                "niche_fit": fit, "niche_fit_source": fit_src,
                "angle": a["name"], "angle_id": a["row"]["id"] if a["row"] else None,
                "proof": proof, "format_fit": ffit,
                "safety": level, "safety_words": hits,
                "formula_id": fid, "formula": fname,
                "sound": r["name"] if kind == "song" else None,
                "ship_by": ship_by(today, m),
            })
    bridges.sort(key=lambda b: (-b["score"], -b["momentum"], b["trend"]))
    # Two angles per trend at most, so one hot trend cannot fill the board.
    seen, board = {}, []
    for b in bridges:
        if seen.get(b["trend_id"], 0) >= 2:
            continue
        seen[b["trend_id"]] = seen.get(b["trend_id"], 0) + 1
        board.append(b)
        if len(board) >= top:
            break
    return {"niche": niche, "region": region or "all", "date": today.isoformat(),
            "trends_live": len(live), "region_trends": len(region_rows),
            "angles": len(angle_list), "proofs": len(proofs or []),
            "board": board, "excluded": excluded}


def ship_by(today, m):
    # Ship before the trend passes one half-life, or within 2 days if it already has.
    if not m["days_left"]:
        return "too late"
    left = m["half_life"] - m["age"]
    if left < 1:
        left = 2
    left = min(left, m["days_left"])
    return (today + dt.timedelta(days=left)).isoformat()


# ---------------------------------------------------------------- output

def render(b, out=None):
    out = out or sys.stdout
    head = (f"VIRALITY BLAST  ·  {b['niche']}  ·  region {b['region']}  ·  {b['date']}  ·  "
            f"{b['region_trends']} trends x {b['angles']} angles")
    print("\n" + head, file=out)
    print("=" * max(len(head), 78), file=out)
    if not b["board"]:
        print("  Nothing to blend. Add region trends with `trends.py add` first.", file=out)
    for i, x in enumerate(b["board"], 1):
        safe = "" if x["safety"] == "ok" else f"  [FLAG: {', '.join(x['safety_words'][:3])}]"
        fit = f"{x['niche_fit']}/3{'?' if x['niche_fit_source'] == 'guess' else ''}"
        print(f" {i:>2}. {x['score']:>3}  {x['trend'][:40]}  ({x['kind']}, {x['source']})"
              f"{safe}", file=out)
        print(f"        momentum {x['momentum']:>3} {x['phase']:<8} day {x['age']}, "
              f"ship by {x['ship_by']}   niche fit {fit}   format fit {x['format_fit']}/3",
              file=out)
        print(f"        bridge: {x['trend']}  ->  {x['angle']}", file=out)
        print(f"        hook formula #{x['formula_id']} {x['formula']}   "
              f"proof: {x['proof'] or '{{your number}}'}", file=out)
        print(f"        sound: {x['sound'] or '{{pick with /ig-audio}}'}", file=out)
    if b["excluded"]:
        print("-" * 78, file=out)
        print("LEFT OUT, NOT SAFE TO RIDE", file=out)
        for e in b["excluded"]:
            print(f"  {e['name'][:50]}  ({', '.join(e['words'][:3])})", file=out)
    print("-" * 78, file=out)
    print("  A ? on niche fit is a word-match guess. Set it with --niche-match.", file=out)
    print("  This ranks bets. Nobody can promise a reel goes viral.\n", file=out)


def to_markdown(b):
    lines = ["# Virality blast", "",
             f"Niche: {b['niche']}. Region: {b['region']}. Built {b['date']}.",
             f"{b['region_trends']} live region trends, {b['angles']} niche angles.",
             "Ranked bets, not promises. Ship before the date or skip it.", ""]
    for i, x in enumerate(b["board"], 1):
        lines += [f"## {i}. {x['trend']} -> {x['angle']}  (score {x['score']})",
                  f"- trend: {x['kind']} from {x['source']}, {x['region']}, "
                  f"momentum {x['momentum']} {x['phase']}, day {x['age']}",
                  f"- ship by: {x['ship_by']}",
                  f"- niche fit: {x['niche_fit']}/3 ({x['niche_fit_source']}), "
                  f"format fit {x['format_fit']}/3",
                  f"- hook formula: #{x['formula_id']} {x['formula']}",
                  f"- proof: {x['proof'] or '{{your number}}'}",
                  f"- sound: {x['sound'] or '{{pick with /ig-audio}}'}",
                  f"- safety: {x['safety']}"
                  + (f" ({', '.join(x['safety_words'])})" if x["safety_words"] else ""),
                  ""]
    if b["excluded"]:
        lines += ["## Left out, not safe to ride", ""]
        lines += [f"- {e['name']} ({', '.join(e['words'])})" for e in b["excluded"]]
        lines.append("")
    return "\n".join(lines)


# ---------------------------------------------------------------- commands

def cmd_add(a):
    rows = load_rows()
    today = today_from(a.today)
    if a.first_seen and not parse_date(a.first_seen):
        sys.exit("--first-seen must be YYYY-MM-DD")
    if a.growth and parse_growth(a.growth) is None:
        sys.exit(f"--growth not understood: {a.growth!r}. Try +250%, 3x or Breakout.")
    row = {"id": next_id(rows), "added": today.isoformat(), "scope": a.scope,
           "source": a.source, "region": a.region.upper(), "kind": a.kind,
           "name": a.name.strip(), "rank": a.rank if a.rank is not None else "",
           "growth": a.growth or "", "first_seen": a.first_seen or today.isoformat(),
           "niche_match": a.niche_match if a.niche_match is not None else "",
           "safety": a.safety, "url": a.url or "", "notes": a.notes or ""}
    rows.append(row)
    save_rows(rows)
    level, hits = safety_of(row)
    if a.json:
        print(json.dumps({**row, "safety_level": level, "safety_words": hits}, ensure_ascii=False))
        return
    print(f"added {row['id']}  {row['kind']}  {row['name']}  ({row['source']}, {row['region']})")
    if level != "ok":
        print(f"  safety: {level.upper()} ({', '.join(hits)})")


def cmd_list(a):
    today = today_from(a.today)
    rows = [r for r in load_rows()
            if not a.region or r["region"].upper() == a.region.upper()]
    out = []
    for r in rows:
        m = momentum(r, today)
        out.append({**r, **m, "safety_level": safety_of(r)[0], "expired": expired(r, today)})
    if a.json:
        print(json.dumps(out, indent=2, ensure_ascii=False))
        return
    if not out:
        print("no trends logged yet. Use `trends.py add`.")
        return
    for r in out:
        tag = "expired" if r["expired"] else r["phase"]
        print(f"  {r['id']}  {r['scope']:<6} {r['region']:<3} {r['source']:<9} "
              f"{r['kind']:<7} mom {r['momentum']:>3} {tag:<8} {r['name'][:44]}"
              + ("" if r["safety_level"] == "ok" else f"  [{r['safety_level']}]"))


def cmd_prune(a):
    today = today_from(a.today)
    rows = load_rows()
    keep = [r for r in rows if not expired(r, today)]
    gone = [r for r in rows if expired(r, today)]
    if not a.dry_run and gone:
        save_rows(keep)
    if a.json:
        print(json.dumps({"removed": [r["id"] for r in gone], "kept": len(keep),
                          "dry_run": a.dry_run}))
        return
    verb = "would drop" if a.dry_run else "dropped"
    print(f"{verb} {len(gone)} expired, {len(keep)} left")
    for r in gone:
        print(f"  {r['id']}  {r['kind']:<7} day {age_days(r, today)}  {r['name'][:50]}")


def cmd_blend(a):
    today = today_from(a.today)
    voice = os.path.expanduser(a.voice) if a.voice else os.path.join(data_dir(), "voice.md")
    proofs = read_proof(voice)
    angles = [x.strip() for x in (a.angle or []) if x.strip()]
    b = blend(load_rows(), a.niche, today, region=a.region, angles=angles,
              proofs=proofs, top=a.top)
    if a.json:
        print(json.dumps(b, indent=2, ensure_ascii=False))
    else:
        render(b)
    if not a.no_write:
        write_text(board_path(), to_markdown(b))
        print(f"wrote {board_path()}", file=sys.stderr)


def build_parser():
    ap = argparse.ArgumentParser(description="Log trends and blend them with a niche.")
    ap.add_argument("--today", help=argparse.SUPPRESS)
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("add", help="log one trend")
    p.add_argument("--source", required=True, choices=SOURCES)
    p.add_argument("--region", required=True, help="country code, e.g. IN, US, GB")
    p.add_argument("--kind", required=True, choices=KINDS)
    p.add_argument("--name", required=True)
    p.add_argument("--scope", default="region", choices=SCOPES,
                   help="region = trending everywhere, niche = trending in the niche")
    p.add_argument("--rank", type=int)
    p.add_argument("--growth", help="+250%%, 3x, Breakout")
    p.add_argument("--first-seen", help="YYYY-MM-DD, defaults to today")
    p.add_argument("--niche-match", type=int, choices=range(0, 4), metavar="0-3")
    p.add_argument("--safety", default="auto", choices=SAFETY)
    p.add_argument("--url")
    p.add_argument("--notes")
    p.add_argument("--json", action="store_true")
    p.set_defaults(fn=cmd_add)

    p = sub.add_parser("blend", help="rank region x niche bridge ideas")
    p.add_argument("--niche", required=True)
    p.add_argument("--region")
    p.add_argument("--angle", action="append", help="a niche angle, repeatable")
    p.add_argument("--top", type=int, default=10)
    p.add_argument("--voice", help="path to voice.md, default $DATA/voice.md")
    p.add_argument("--no-write", action="store_true", help="do not write trends.md")
    p.add_argument("--json", action="store_true")
    p.set_defaults(fn=cmd_blend)

    p = sub.add_parser("list", help="show logged trends")
    p.add_argument("--region")
    p.add_argument("--json", action="store_true")
    p.set_defaults(fn=cmd_list)

    p = sub.add_parser("prune", help="drop expired trends")
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--json", action="store_true")
    p.set_defaults(fn=cmd_prune)
    return ap


def main(argv=None):
    a = build_parser().parse_args(argv)
    a.fn(a)
    return 0


if __name__ == "__main__":
    sys.exit(main())
