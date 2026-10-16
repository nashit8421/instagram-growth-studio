#!/usr/bin/env python3
"""week.json: the week as ready-to-make post kits. IG Studio's home screen reads it.

    python3 week.py monday [--today 2026-10-16]   # the Monday to plan (Mon-Wed: this week, else next)
    python3 week.py schema                        # the shape, as a filled example
    python3 week.py check FILE [--fix] [--json]   # validate; --fix strips em dashes and invisible chars
    python3 week.py plan-md FILE [--out PATH]     # write plan.md from it (default: next to FILE)

Each post is a kit: the hook, the script, how to film it (the director's notes),
the caption, the sound, and the cover. The user films and posts; nothing here
posts anything. Stdlib only.
"""

import argparse
import datetime as dt
import json
import os
import re
import sys

DAYS = ["MON", "TUE", "WED", "THU", "FRI", "SAT", "SUN"]
FORMATS = ("reel", "carousel", "story", "photo")
TYPES = ("proof", "teach", "opinion", "story", "offer", "trend")
MAX_HASHTAGS = 5          # Instagram's cap; the pack aims for 3
CAPTION_LIMIT = 2200
ID_RE = re.compile(r"^(mon|tue|wed|thu|fri|sat|sun)(-[2-9])?$")
TIME_RE = re.compile(r"^([01]\d|2[0-3]):([0-5]\d)$")
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
INVISIBLE = re.compile("[​-‏⁠﻿­]")
EM_DASH = re.compile(r"\s*—\s*")

EXAMPLE = {
    "version": 1,
    "week_of": "2026-10-19",
    "made_at": "2026-10-16T20:30:00",
    "account": "yourhandle",
    "tz": "Asia/Kolkata",
    "headline": "5 reels this week. The one lever: post every slot.",
    "bottleneck": {"key": "consistency", "line": "0.2 posts a week now; the target is 4."},
    "assumptions": ["Early evening India time for posts.", "Trends from web search; kweo was not connected."],
    "posts": [{
        "id": "mon", "day": "MON", "date": "2026-10-19", "time": "19:30",
        "format": "reel", "type": "proof", "trial": False,
        "title": "One line, three emotions",
        "why": "Range beats plain lip-syncs on this account; the song peaks this week.",
        "length_s": 20,
        "hook": {"spoken": "Ek line, teen emotions.", "on_screen": "Kaunsa wala real tha?",
                 "formula": 18, "formula_name": "Cold Open Demo", "score": 81},
        "script": [
            {"t": "0-2s", "say": "Ek line, teen emotions.", "on_screen": "Kaunsa wala real tha?", "shot": 1},
            {"t": "2-8s", "say": "(the line, shy)", "on_screen": "1. shy", "shot": 2},
        ],
        "direction": {
            "concept": "The same line acted three ways, hard cuts between them.",
            "mood": "dramatic",
            "setup": {"location": "plain wall, window light", "light": "face the window, no overhead light",
                      "framing": "phone at eye level, chest up, eyes on the top third",
                      "wardrobe": "one solid colour", "props": "none"},
            "shots": [{"n": 1, "frame": "close-up", "action": "look straight in the lens, half smile",
                       "line": "Ek line, teen emotions.", "seconds": 2}],
            "delivery": ["Start talking on frame one, no intro.", "Hold each emotion a beat before the cut."],
            "takes": "Three takes of each emotion; keep the one where your eyes change first.",
            "avoid": ["Text in the bottom fifth: Instagram's buttons cover it."],
        },
        "caption": {"text": "Ek line, teen emotions. Kaunsa wala real tha? 1, 2 ya 3?",
                    "hashtags": ["#actorlife", "#hindiacting", "#acting"]},
        "sound": {"name": "Koi Kaise Mohabbat Chhupaye", "why": "near its peak this week",
                  "how": "Add it in Instagram's audio picker at 15% under your voice."},
        "cover": {"text": "1 line. 3 emotions.", "frame": "the heartbroken take, eyes up"},
        "film_on": "2026-10-17",
    }],
    "stories": [{"day": "MON", "frames": ["Behind the scenes of today's shoot", "Poll: which take?"],
                 "sticker": "poll: 1 / 2 / 3"}],
    "engage": {"minutes": 20, "when": "before each post",   # when: no minutes in it, they are above
               "kinds": [{"kind": "reach", "count": 5, "who": "bigger creators your audience follows"},
                         {"kind": "peers", "count": 3, "who": "same size, same field"},
                         {"kind": "buyers", "count": 2, "who": "brands or casting pages"}],
               "accounts": []},
    "todo": [{"date": "2026-10-17", "task": "Film Monday's and Tuesday's reels", "post": "mon", "kind": "film"}],
}


# ---------------------------------------------------------------- dates

def monday_for(today):
    """The week to plan: this week if it is Mon-Wed, otherwise next week."""
    start = today - dt.timedelta(days=today.weekday())
    return start if today.weekday() <= 2 else start + dt.timedelta(days=7)


def _date(s):
    if not isinstance(s, str) or not DATE_RE.match(s):
        return None
    try:
        return dt.date.fromisoformat(s)
    except ValueError:
        return None


# ---------------------------------------------------------------- text hygiene

def _clean(s):
    out = INVISIBLE.sub("", s)
    out = EM_DASH.sub(" - ", out)
    return out


def _walk_text(node, fn, path=""):
    """Apply fn to every string; returns the new node and the paths that changed."""
    changed = []
    if isinstance(node, str):
        new = fn(node)
        return new, ([path] if new != node else [])
    if isinstance(node, list):
        out = []
        for i, x in enumerate(node):
            v, c = _walk_text(x, fn, f"{path}[{i}]")
            out.append(v)
            changed += c
        return out, changed
    if isinstance(node, dict):
        out = {}
        for k, x in node.items():
            v, c = _walk_text(x, fn, f"{path}.{k}" if path else k)
            out[k] = v
            changed += c
        return out, changed
    return node, changed


# ---------------------------------------------------------------- validation

def _s(x):
    return isinstance(x, str) and x.strip() != ""


def check(week, today=None):
    """Return (errors, warnings). Errors make the kit unusable; warnings are style."""
    errors, warnings = [], []
    if not isinstance(week, dict):
        return ["week.json must be an object."], []
    monday = _date(week.get("week_of"))
    if monday is None:
        errors.append("week_of must be a date like 2026-10-19.")
    elif monday.weekday() != 0:
        errors.append(f"week_of {week.get('week_of')} is not a Monday.")
    if not _s(week.get("headline")):
        errors.append("headline is missing: one line on what this week is about.")
    posts = week.get("posts")
    if not isinstance(posts, list) or not posts:
        errors.append("posts must be a non-empty list.")
        posts = []
    if len(posts) > 14:
        errors.append("more than 14 posts in one week.")
    seen = set()
    for i, p in enumerate(posts):
        where = f"posts[{i}]"
        if not isinstance(p, dict):
            errors.append(f"{where} is not an object.")
            continue
        pid = p.get("id")
        where = f"post {pid}" if _s(pid) else where
        if not isinstance(pid, str) or not ID_RE.match(pid):
            errors.append(f"{where}: id must be mon..sun, or mon-2 for a second post that day.")
        elif pid in seen:
            errors.append(f"{where}: duplicate id.")
        else:
            seen.add(pid)
        day = str(p.get("day") or "").upper()
        if day not in DAYS:
            errors.append(f"{where}: day must be one of {', '.join(DAYS)}.")
        elif isinstance(pid, str) and ID_RE.match(pid) and pid[:3].upper() != day:
            errors.append(f"{where}: id and day disagree ({pid} vs {day}).")
        d = _date(p.get("date"))
        if d is None:
            errors.append(f"{where}: date must be YYYY-MM-DD.")
        elif monday is not None:
            if not monday <= d <= monday + dt.timedelta(days=6):
                errors.append(f"{where}: {d} is outside the week of {monday}.")
            elif day in DAYS and DAYS[d.weekday()] != day:
                errors.append(f"{where}: {d} is a {DAYS[d.weekday()]}, not {day}.")
        if not TIME_RE.match(str(p.get("time") or "")):
            errors.append(f"{where}: time must be 24h HH:MM, like 19:30.")
        fmt = p.get("format")
        if fmt not in FORMATS:
            errors.append(f"{where}: format must be one of {', '.join(FORMATS)}.")
        if p.get("type") not in TYPES:
            errors.append(f"{where}: type must be one of {', '.join(TYPES)}.")
        if not _s(p.get("title")):
            errors.append(f"{where}: title is missing.")
        hook = p.get("hook") if isinstance(p.get("hook"), dict) else {}
        if not (_s(hook.get("spoken")) or _s(hook.get("on_screen"))):
            errors.append(f"{where}: the hook needs a spoken line or on-screen text.")
        if fmt == "reel":
            script = p.get("script")
            if not isinstance(script, list) or not script:
                errors.append(f"{where}: a reel needs a script (a list of beats).")
            else:
                for j, b in enumerate(script):
                    if not isinstance(b, dict) or not (_s(b.get("say")) or _s(b.get("on_screen"))):
                        errors.append(f"{where}: script beat {j + 1} needs say or on_screen.")
            dirn = p.get("direction") if isinstance(p.get("direction"), dict) else {}
            shots = dirn.get("shots")
            if not isinstance(shots, list) or not shots:
                errors.append(f"{where}: a reel needs direction.shots, the director's shot list.")
            elif any(not isinstance(s, dict) or not _s(s.get("action")) for s in shots):
                errors.append(f"{where}: every shot needs an action.")
            if not isinstance(dirn.get("setup"), dict):
                warnings.append(f"{where}: direction.setup (location, light, framing) is missing.")
        if fmt == "carousel":
            slides = p.get("slides")
            if not isinstance(slides, list) or len(slides) < 2:
                errors.append(f"{where}: a carousel needs at least 2 slides.")
        cap = p.get("caption") if isinstance(p.get("caption"), dict) else {}
        if not _s(cap.get("text")):
            errors.append(f"{where}: caption.text is missing.")
        elif len(cap["text"]) > CAPTION_LIMIT:
            errors.append(f"{where}: caption is {len(cap['text'])} characters; Instagram allows {CAPTION_LIMIT}.")
        tags = cap.get("hashtags") or []
        if not isinstance(tags, list) or any(not isinstance(t, str) or not re.fullmatch(r"#[^\s#]+", t) for t in tags):
            errors.append(f"{where}: hashtags must be a list like [\"#acting\"].")
        elif len(tags) > MAX_HASHTAGS:
            errors.append(f"{where}: {len(tags)} hashtags; use 3, never more than {MAX_HASHTAGS}.")
        elif len(tags) > 3:
            warnings.append(f"{where}: {len(tags)} hashtags; the pack uses 3.")
        if fmt in ("reel", "story") and not isinstance(p.get("sound"), dict):
            warnings.append(f"{where}: no sound picked.")
    for k in ("stories", "todo", "assumptions"):
        if k in week and not isinstance(week[k], list):
            errors.append(f"{k} must be a list.")
    for j, t in enumerate(week.get("todo") or []):
        if not isinstance(t, dict) or not _s(t.get("task")) or _date(t.get("date")) is None:
            errors.append(f"todo[{j}] needs a task and a date.")
    _, dirty = _walk_text(week, lambda s: _clean(s))
    if dirty:
        errors.append(f"{len(dirty)} text fields have em dashes or invisible characters (run with --fix): "
                      + ", ".join(dirty[:5]) + ("…" if len(dirty) > 5 else ""))
    return errors, warnings


def fix(week):
    new, changed = _walk_text(week, _clean)
    return new, len(changed)


# ---------------------------------------------------------------- plan.md

def _ampm(hhmm):
    m = TIME_RE.match(str(hhmm or ""))
    if not m:
        return ""
    h, mm = int(m.group(1)), m.group(2)
    suffix = "am" if h < 12 else "pm"
    h = h % 12 or 12
    return f"{h}{'' if mm == '00' else ':' + mm}{suffix}"


def plan_md(week):
    monday = _date(week["week_of"])
    lines = [f"WEEK OF {monday.strftime('%b').upper()} {monday.day} {monday.year}", ""]
    if week.get("headline"):
        lines += [week["headline"], ""]
    by_day = {}
    for p in week.get("posts") or []:
        by_day.setdefault(str(p.get("day")).upper(), []).append(p)
    for day in DAYS:
        posts = sorted(by_day.get(day, []), key=lambda p: p.get("time") or "")
        if not posts:
            lines.append(f"{day}  stories only + engage")
            continue
        for p in posts:
            hook = p.get("hook") or {}
            formula = f"#{hook['formula']} {hook.get('formula_name') or ''}".strip() if hook.get("formula") else ""
            trial = " (trial)" if p.get("trial") else ""
            lines.append(f"{day}  {_ampm(p.get('time')):<7} {str(p.get('format')).upper():<9} "
                         f"{str(p.get('type')).upper():<8} {formula}{trial} - {p.get('title')}")
    stories = week.get("stories") or []
    if stories:
        lines += ["", "STORIES"]
        for s in stories:
            frames = "; ".join(s.get("frames") or [])
            lines.append(f"  {s.get('day', '')}  {frames}" + (f"  [{s['sticker']}]" if s.get("sticker") else ""))
    eng = week.get("engage") or {}
    if eng:
        when = str(eng.get("when") or "before each post")
        lead = when if re.search(r"\bmin", when) else f"{eng.get('minutes', 20)} min {when}"
        lines += ["", f"ENGAGE  {lead}, by hand"]
        for k in eng.get("kinds") or []:
            lines.append(f"  {k.get('kind')}: {k.get('count', '')} {k.get('who', '')}".rstrip())
        if eng.get("accounts"):
            lines.append("  accounts: " + ", ".join(eng["accounts"]))
    todo = week.get("todo") or []
    if todo:
        lines += ["", "WHAT YOU NEED TO DO"]
        for t in sorted(todo, key=lambda t: t.get("date") or ""):
            d = _date(t.get("date"))
            when = f"{DAYS[d.weekday()].title()} {d.strftime('%b')} {d.day}" if d else ""
            lines.append(f"  [ ] {when:<11} {t.get('task')}")
    lines += ["", "Made by IG Studio from week.json. Nothing is posted for you."]
    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------- cli

def _load(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def _save(path, week):
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(week, f, ensure_ascii=False, indent=2)
        f.write("\n")
    os.replace(tmp, path)


def main(argv=None):
    ap = argparse.ArgumentParser(description="week.json: the week as post kits.")
    sub = ap.add_subparsers(dest="cmd", required=True)
    m = sub.add_parser("monday")
    m.add_argument("--today")
    sub.add_parser("schema")
    c = sub.add_parser("check")
    c.add_argument("file")
    c.add_argument("--fix", action="store_true")
    c.add_argument("--json", action="store_true")
    p = sub.add_parser("plan-md")
    p.add_argument("file")
    p.add_argument("--out")
    args = ap.parse_args(argv)

    if args.cmd == "monday":
        today = dt.date.fromisoformat(args.today) if args.today else dt.date.today()
        print(monday_for(today).isoformat())
        return 0
    if args.cmd == "schema":
        print(json.dumps(EXAMPLE, ensure_ascii=False, indent=2))
        return 0
    try:
        week = _load(args.file)
    except (OSError, ValueError) as e:
        msg = f"Cannot read {args.file}: {e}"
        print(json.dumps({"ok": False, "errors": [msg], "warnings": []}) if getattr(args, "json", False) else msg)
        return 1
    if args.cmd == "check":
        fixed = 0
        if args.fix:
            week, fixed = fix(week)
            if fixed:
                _save(args.file, week)
        errors, warnings = check(week)
        res = {"ok": not errors, "errors": errors, "warnings": warnings, "fixed": fixed,
               "posts": len(week.get("posts") or []) if isinstance(week, dict) else 0}
        if args.json:
            print(json.dumps(res, ensure_ascii=False, indent=2))
        else:
            print("OK" if not errors else "NOT OK")
            for e in errors:
                print("  error:", e)
            for w in warnings:
                print("  warn: ", w)
            if fixed:
                print(f"  fixed {fixed} text fields")
        return 0 if not errors else 1
    if args.cmd == "plan-md":
        errors, _ = check(week)
        if errors:
            print("week.json is not valid yet; run check first:\n  " + "\n  ".join(errors), file=sys.stderr)
            return 1
        out = args.out or os.path.join(os.path.dirname(os.path.abspath(args.file)), "plan.md")
        with open(out, "w", encoding="utf-8") as f:
            f.write(plan_md(week))
        print(out)
        return 0
    return 2


if __name__ == "__main__":
    sys.exit(main())
