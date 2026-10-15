#!/usr/bin/env python3
"""
schedule.py - turn the weekly plan from /ig-plan into posting reminders.

It reads plan.md (the file /ig-plan writes) and works out the week's events:

  post      one per posting slot, at the posting time, 30 minutes
  prep      the day before each reel, 6pm, 60 minutes: "Film Tuesday's reel"
  engage    20 minutes a day, ending before that day's post
  stories   one reminder a day, from the STORIES line

What this does NOT do: post anything, or touch a calendar. It prints events.
Claude feeds them to the Google Calendar connector after the user says yes.
If there is no connector, `ics` writes a file the user double-clicks.

Every event carries a stable key, like ig-2026-W42-tue-reel. The key goes at
the end of the description as [ig:KEY] and into the .ics UID, so running it
again updates the same events instead of making copies.

Usage
  python3 schedule.py parse [PLAN.md] [--week-of YYYY-MM-DD] [--tz Europe/London] [--json]
  python3 schedule.py events [PLAN.md] [...] --json
  python3 schedule.py ics [PLAN.md] [...] [--out week.ics]
  python3 schedule.py checklist [PLAN.md] [...]
"""

import argparse
import datetime
import json
import os
import re
import sys
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

UTC = datetime.timezone.utc
RULE = "=" * 64
THIN = "-" * 64

DAYS = ["MON", "TUE", "WED", "THU", "FRI", "SAT", "SUN"]
DAY_NAMES = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday",
             "Saturday", "Sunday"]
MONTHS = ["JAN", "FEB", "MAR", "APR", "MAY", "JUN",
          "JUL", "AUG", "SEP", "OCT", "NOV", "DEC"]

POST_MIN = 30            # posting slot length
PREP_MIN = 60            # filming block length
STORY_MIN = 15           # story reminder length
ENGAGE_MIN = 20          # default engagement round
ENGAGE_LEAD = 30         # engagement starts this long before the post
REMIND_MIN = 30          # popup / VALARM lead time
KINDS = ("post", "prep", "engage", "stories")
NOTHING_POSTS = "Reminder only. Nothing posts automatically. You post it by hand."

# Which skills to run, by format. Shown in each event description.
SKILLS = {
    "REEL": "Write it with /ig-reel, cut it with /ig-edit, caption it with /ig-caption.",
    "CAROUSEL": ("Write the slides with /ig-carousel, make the files with /ig-render, "
                 "caption it with /ig-caption."),
    "STORY": "Write the frames with /ig-story, make the images with /ig-render.",
    "STORIES": "Write the frames with /ig-story, make the images with /ig-render.",
    "PHOTO": "Caption it with /ig-caption.",
}
DEFAULT_SKILLS = "Caption it with /ig-caption."


class PlanError(Exception):
    """Something the user has to fix. Printed without a traceback."""


# ---------------------------------------------------------------- data dir

def data_dir():
    """$IG_DATA_DIR, else the active account under $IG_HOME, else $IG_HOME."""
    env = os.environ.get("IG_DATA_DIR")
    if env:
        return os.path.expanduser(env)
    home = os.path.expanduser(os.environ.get("IG_HOME") or "~/.claude/instagram")
    try:
        with open(os.path.join(home, "active-account"), encoding="utf-8") as f:
            handle = f.read().strip().lstrip("@")
    except OSError:
        handle = ""
    if handle and "/" not in handle and "\\" not in handle and handle not in (".", ".."):
        acct = os.path.join(home, "accounts", handle)
        if os.path.isdir(acct):
            return acct
    return home


# ---------------------------------------------------------------- time zone

def system_tz(localtime="/etc/localtime"):
    """IANA name from the /etc/localtime symlink, then $TZ, else None."""
    try:
        target = os.path.realpath(localtime)
        if "zoneinfo/" in target:
            name = target.split("zoneinfo/", 1)[1]
            ZoneInfo(name)
            return name
    except (OSError, ZoneInfoNotFoundError, ValueError):
        pass
    env = (os.environ.get("TZ") or "").lstrip(":")
    if env:
        try:
            ZoneInfo(env)
            return env
        except (ZoneInfoNotFoundError, ValueError):
            pass
    return None


def resolve_tz(name):
    """Return (tzname, ZoneInfo, warning or None)."""
    warning = None
    if not name:
        name = system_tz()
        if not name:
            name = "UTC"
            warning = "Could not read the system time zone. Using UTC. Pass --tz."
    try:
        return name, ZoneInfo(name), warning
    except (ZoneInfoNotFoundError, ValueError):
        raise PlanError(f"Unknown time zone {name!r}. Use an IANA name like Europe/London.")


def local_dt(day, hm, tz):
    """Wall-clock time on a date in tz. A time inside a spring-forward gap
    is moved forward to a real time."""
    naive = datetime.datetime.combine(day, datetime.time(hm[0], hm[1]))
    aware = naive.replace(tzinfo=tz)
    return aware.astimezone(UTC).astimezone(tz)


def plus(dt, minutes, tz):
    """Add real minutes (not wall-clock minutes), result in tz."""
    return (dt.astimezone(UTC) + datetime.timedelta(minutes=minutes)).astimezone(tz)


def parse_clock(text):
    """'7:30pm', '7pm', '7:30 PM', '19:30' -> (19, 30)."""
    t = text.strip().lower().replace(".", "")
    m = re.fullmatch(r"(\d{1,2})(?::(\d{2}))?\s*(am|pm)?", t)
    if not m:
        raise ValueError(f"not a time: {text!r}")
    h, mi, ap = int(m.group(1)), int(m.group(2) or 0), m.group(3)
    if ap:
        if not 1 <= h <= 12:
            raise ValueError(f"not a time: {text!r}")
        h = h % 12 + (12 if ap == "pm" else 0)
    elif m.group(2) is None:
        raise ValueError(f"not a time: {text!r}")
    if not (0 <= h <= 23 and 0 <= mi <= 59):
        raise ValueError(f"not a time: {text!r}")
    return h, mi


def clock_arg(text):
    try:
        return parse_clock(text)
    except ValueError as e:
        raise argparse.ArgumentTypeError(str(e))


def fmt_clock(dt):
    h = dt.hour % 12 or 12
    return f"{h}:{dt.minute:02d}{'am' if dt.hour < 12 else 'pm'}"


# ---------------------------------------------------------------- parsing

TIME_RE = r"\d{1,2}(?::\d{2})?\s*(?:am|pm)|\d{1,2}:\d{2}"
DAY_LINE = re.compile(r"^\s*(MON|TUE|WED|THU|FRI|SAT|SUN)[A-Z]*\b\s*(.*)$", re.I)
SLOT_LINE = re.compile(rf"^({TIME_RE})\s+(.*)$", re.I)
WEEK_LINE = re.compile(r"^\s*WEEK\s+OF\s+([A-Z]{3})[A-Z]*\.?\s+(\d{1,2})(?:\s*,?\s*(\d{4}))?",
                       re.I)
SEP = re.compile(r"\s+[-\u2013\u2014]\s+")
DAY_WORD = re.compile(r"\b(mon|tue|wed|thu|fri|sat|sun)[a-z]*\b", re.I)


def parse_slot(day, text):
    """'7:30pm  REEL  PROOF  #5  Time Collapse   - 5hr proposal to 20 min'."""
    m = SLOT_LINE.match(text)
    clock = parse_clock(m.group(1))
    rest = m.group(2).strip()
    trial = bool(re.search(r"\btrial\b", rest, re.I))
    rest = re.sub(r"\(\s*trial\s*\)|\btrial\b", " ", rest, flags=re.I).strip()
    parts = SEP.split(rest, maxsplit=1)
    head, angle = parts[0].strip(), (parts[1].strip() if len(parts) > 1 else "")
    tokens = head.split()
    fmt = tokens.pop(0).upper() if tokens else "POST"
    ptype = ""
    if tokens and not tokens[0].startswith("#"):
        ptype = tokens.pop(0).upper()
    hook_text = " ".join(tokens)
    formula, hook = None, hook_text
    hm = re.match(r"#(\d+)\s*(.*)$", hook_text)
    if hm:
        formula, hook = int(hm.group(1)), hm.group(2).strip()
    return {
        "day": day, "time": f"{clock[0]:02d}:{clock[1]:02d}", "format": fmt,
        "type": ptype, "formula": formula, "hook": hook, "angle": angle,
        "trial": trial,
    }


def parse_plan_text(text):
    """Plan text -> dict of header, days, slots, stories, engage. No dates yet."""
    plan = {"header": None, "header_date": None, "days": {}, "slots": [],
            "stories": None, "engage": None, "unparsed": []}
    lines = text.splitlines()
    i = 0
    while i < len(lines):
        raw = lines[i]
        line = raw.strip()
        i += 1
        if not line or line.startswith("```"):
            continue
        w = WEEK_LINE.match(line)
        if w and plan["header"] is None:
            mon = w.group(1).upper()
            if mon in MONTHS:
                plan["header"] = line
                plan["header_date"] = (MONTHS.index(mon) + 1, int(w.group(2)),
                                       int(w.group(3)) if w.group(3) else None)
            continue
        up = line.upper()
        if up.startswith("STORIES"):
            plan["stories"] = line[len("STORIES"):].strip()
            continue
        if up.startswith("ENGAGE"):
            accounts = []
            while i < len(lines):
                nxt = lines[i]
                if nxt.strip() and not nxt[:1].isspace():
                    break
                i += 1
                s = nxt.strip()
                if s and s.strip(". ") and s != "...":
                    accounts.append(s)
            plan["engage"] = {"note": line[len("ENGAGE"):].strip(), "accounts": accounts}
            continue
        d = DAY_LINE.match(line)
        if d:
            day = d.group(1).upper()
            rest = d.group(2).strip()
            entry = plan["days"].setdefault(day, {"rest": False, "notes": [],
                                                  "engage_min": None})
            if rest in ("-", "\u2013", "\u2014", ""):
                entry["rest"] = True
                continue
            if SLOT_LINE.match(rest):
                try:
                    plan["slots"].append(parse_slot(day, rest))
                except ValueError:
                    plan["unparsed"].append(line)
                continue
            entry["notes"].append(rest)
            mm = re.search(r"(\d+)\s*min", rest, re.I)
            if mm and "engage" in rest.lower():
                entry["engage_min"] = int(mm.group(1))
            continue
    return plan


def stories_by_day(text):
    """STORIES line -> (general note, {DAY: [day notes]}, [days])."""
    if text is None:
        return "", {}, []
    clauses = [c.strip() for c in re.split(r"[,;]|\.\s", text.strip().rstrip(".")) if c.strip()]
    general, per_day = [], {}
    for c in clauses:
        on = re.search(r"\bon\s+((?:mon|tue|wed|thu|fri|sat|sun)[a-z]*)\b", c, re.I)
        if on:
            day = on.group(1)[:3].upper()
            note = (c[:on.start()] + c[on.end():]).strip(" .")
            per_day.setdefault(day, []).append(note or c)
        elif not re.fullmatch(r"(every\s*day|daily)", c, re.I):
            general.append(c)
    low = text.lower()
    if "every day" in low or "everyday" in low or "daily" in low:
        days = list(DAYS)
    else:
        named = [m.group(1)[:3].upper() for m in DAY_WORD.finditer(text)]
        days = [d for d in DAYS if d in named] or list(DAYS)
    return ", ".join(general), per_day, days


# ---------------------------------------------------------------- the week

def monday_of(day):
    return day - datetime.timedelta(days=day.weekday())


def infer_week(header_date, today):
    """(month, day, year or None) -> the Monday of that week. Without a year,
    take the year that puts the date closest to today."""
    month, dom, year = header_date
    if year:
        candidates = [year]
    else:
        candidates = [today.year - 1, today.year, today.year + 1]
    best = None
    for y in candidates:
        try:
            d = datetime.date(y, month, dom)
        except ValueError:
            continue
        if best is None or abs((d - today).days) < abs((best - today).days):
            best = d
    if best is None:
        raise PlanError(f"The plan header has a date that does not exist: {month}/{dom}.")
    return monday_of(best)


def week_key(week_of):
    y, w, _ = week_of.isocalendar()
    return f"{y}-W{w:02d}"


def load_plan(path):
    if not path:
        path = os.path.join(data_dir(), "plan.md")
    path = os.path.expanduser(path)
    if not os.path.isfile(path):
        raise PlanError(f"No plan found at {path}. Run /ig-plan first, or pass the "
                        f"path to plan.md.")
    with open(path, encoding="utf-8") as f:
        text = f.read()
    return path, text


def build(text, week_of=None, tz_name=None, today=None, skip=(), path=None,
          post_min=POST_MIN, prep_at=(18, 0), engage_at=(19, 0), stories_at=(12, 30),
          remind=REMIND_MIN):
    """Plan text -> the full result: week, slots, events, warnings."""
    today = today or datetime.date.today()
    plan = parse_plan_text(text)
    if not plan["slots"] and not plan["days"]:
        raise PlanError("No day lines found in the plan. Expected lines like "
                        "'TUE  7:30pm  REEL  PROOF  #5  Time Collapse  - angle'.")
    tz_name, tz, tz_warn = resolve_tz(tz_name)
    warnings = [tz_warn] if tz_warn else []
    for u in plan["unparsed"]:
        warnings.append(f"Could not read this line, skipped: {u}")

    if week_of is None:
        if plan["header_date"]:
            week_of = infer_week(plan["header_date"], today)
            source = "header"
        else:
            week_of = monday_of(today) + datetime.timedelta(days=7)
            source = "next Monday"
    else:
        source = "--week-of"
        if week_of.weekday() != 0:
            warnings.append(f"{week_of} is not a Monday. Using the Monday of that week, "
                            f"{monday_of(week_of)}.")
            week_of = monday_of(week_of)
    if week_of + datetime.timedelta(days=6) < today:
        warnings.append(f"The week of {week_of} is already over. Pass --week-of "
                        f"YYYY-MM-DD for the week you mean.")
    wk = week_key(week_of)

    def date_of(day):
        return week_of + datetime.timedelta(days=DAYS.index(day))

    def tag(key):
        return f"[ig:{key}]"

    events = []

    def add(kind, key, summary, desc_lines, start, minutes):
        end = plus(start, minutes, tz)
        desc = "\n".join(desc_lines + [NOTHING_POSTS, tag(key)])
        events.append({
            "key": key, "kind": kind, "summary": summary, "description": desc,
            "start": start.isoformat(timespec="seconds"),
            "end": end.isoformat(timespec="seconds"),
            "time_zone": tz_name, "reminders_minutes": remind,
            "uid": f"{key}@ig-calendar",
            "connector": {
                "summary": summary, "description": desc,
                "startTime": start.replace(tzinfo=None).isoformat(timespec="seconds"),
                "endTime": end.replace(tzinfo=None).isoformat(timespec="seconds"),
                "timeZone": tz_name,
                "overrideReminders": [{"method": "popup", "minutes": remind}],
            },
            "_start": start,
        })

    # posting slots and their prep
    seen = {}
    slots = sorted(plan["slots"], key=lambda s: (DAYS.index(s["day"]), s["time"]))
    first_post = {}
    for s in slots:
        base = f"ig-{wk}-{s['day'].lower()}-{s['format'].lower()}"
        seen[base] = seen.get(base, 0) + 1
        key = base if seen[base] == 1 else f"{base}-{seen[base]}"
        s["key"] = key
        day = date_of(s["day"])
        hh, mm = map(int, s["time"].split(":"))
        start = local_dt(day, (hh, mm), tz)
        s["date"] = day.isoformat()
        first_post.setdefault(s["day"], start)
        dayname = DAY_NAMES[DAYS.index(s["day"])]
        name = s["hook"] or s["angle"] or dayname
        bits = [s["format"]] + ([s["type"]] if s["type"] else []) + [name]
        summary = "IG: " + " \u00b7 ".join(bits) + (" (trial)" if s["trial"] else "")
        fmt_line = " \u00b7 ".join([s["format"]] + ([s["type"]] if s["type"] else []))
        hook_line = (f"Hook formula: #{s['formula']} {s['hook']} (ig-reel/hooks.json)"
                     if s["formula"] is not None else
                     (f"Hook: {s['hook']}" if s["hook"] else "Hook: not set"))
        lines = [f"{fmt_line}, {dayname} {fmt_clock(start)}"]
        if s["angle"]:
            lines.append(f"Angle: {s['angle']}")
        lines.append(hook_line)
        if s["trial"]:
            lines.append("Post it as a Trial Reel (non-followers first). Set up a hook "
                         "test with /ig-test.")
        lines.append("Run: " + SKILLS.get(s["format"], DEFAULT_SKILLS))
        lines.append("Engage for 20 minutes before you post, not after.")
        lines.append("Once it is up, log it with /ig-ledger.")
        if "post" not in skip:
            add("post", key, summary, lines, start, post_min)

        if s["format"] == "REEL" and "prep" not in skip:
            pday = day - datetime.timedelta(days=1)
            pstart = local_dt(pday, prep_at, tz)
            plines = [f"Film {dayname}'s reel."]
            what = ", ".join(x for x in [s["type"].title() if s["type"] else "",
                                         s["angle"]] if x)
            if what:
                plines.append(f"Reel: {what}")
            plines.append(hook_line)
            plines.append("No script yet? Run /ig-reel first. Then film. Cut it with /ig-edit.")
            plines.append(f"Posting slot: {dayname} {day.strftime('%d %b')}, "
                          f"{fmt_clock(start)}.")
            add("prep", f"{key}-prep", f"IG prep: Film {dayname}'s reel", plines,
                pstart, PREP_MIN)

    # engagement rounds
    eng = plan["engage"] or {"note": "", "accounts": []}
    if "engage" not in skip:
        for day in DAYS:
            entry = plan["days"].get(day)
            if entry is None or entry["rest"]:
                if day not in first_post:
                    continue
            minutes = (entry or {}).get("engage_min") or ENGAGE_MIN
            if day in first_post:
                start = plus(first_post[day], -ENGAGE_LEAD, tz)
            else:
                start = local_dt(date_of(day), engage_at, tz)
            lines = [f"{minutes} minutes of comments on other people's posts."]
            if day in first_post:
                lines.append(f"Before today's post at {fmt_clock(first_post[day])}.")
            if eng["note"]:
                lines.append(f"Split: {eng['note'].strip('() ')}")
            if eng["accounts"]:
                lines.append("List:")
                lines.extend(f"  {a}" for a in eng["accounts"])
            lines.append("Run: /ig-comment to write the comments.")
            add("engage", f"ig-{wk}-{day.lower()}-engage", f"IG: engage {minutes} min",
                lines, start, minutes)

    # stories
    if plan["stories"] is not None and "stories" not in skip:
        general, per_day, sdays = stories_by_day(plan["stories"])
        for day in sdays:
            lines = [f"Stories: {general}." if general else "Stories today."]
            for note in per_day.get(day, []):
                lines.append(f"Today: {note}.")
            lines.append("Run: " + SKILLS["STORIES"])
            summary = "IG: stories" + (" + " + per_day[day][0] if per_day.get(day) else "")
            add("stories", f"ig-{wk}-{day.lower()}-stories", summary, lines,
                local_dt(date_of(day), stories_at, tz), STORY_MIN)

    events.sort(key=lambda e: (e["_start"].astimezone(UTC), KINDS.index(e["kind"])))
    for e in events:
        e.pop("_start")
    if not plan["slots"]:
        warnings.append("No posting slots in the plan. Only engagement and story "
                        "reminders were made.")
    return {
        "plan": path, "week_of": week_of.isoformat(), "week_source": source,
        "iso_week": wk, "time_zone": tz_name, "slots": slots,
        "stories": plan["stories"], "engage": plan["engage"],
        "events": events, "warnings": warnings,
    }


# ---------------------------------------------------------------- iCalendar

def ics_escape(text):
    return (text.replace("\\", "\\\\").replace(";", "\\;").replace(",", "\\,")
            .replace("\r\n", "\\n").replace("\n", "\\n"))


def ics_fold(line):
    """Fold to 75 octets per line, never splitting a UTF-8 character."""
    out, cur, size, limit = [], [], 0, 75
    for ch in line:
        n = len(ch.encode("utf-8"))
        if size + n > limit:
            out.append("".join(cur))
            cur, size, limit = [" "], 1, 75
        cur.append(ch)
        size += n
    out.append("".join(cur))
    return "\r\n".join(out)


def ics_time(iso):
    dt = datetime.datetime.fromisoformat(iso).astimezone(UTC)
    return dt.strftime("%Y%m%dT%H%M%SZ")


def to_ics(result, stamp=None):
    stamp = (stamp or datetime.datetime.now(UTC)).astimezone(UTC)
    st = stamp.strftime("%Y%m%dT%H%M%SZ")
    # Later exports carry a higher SEQUENCE, so a re-import replaces the old copy.
    seq = int((stamp - datetime.datetime(2024, 1, 1, tzinfo=UTC)).total_seconds() // 60)
    lines = [
        "BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:-//insta_skills//ig-calendar//EN",
        "CALSCALE:GREGORIAN", "METHOD:PUBLISH",
        f"X-WR-CALNAME:{ics_escape('Instagram ' + result['iso_week'])}",
    ]
    for e in result["events"]:
        lines += [
            "BEGIN:VEVENT", f"UID:{e['uid']}", f"DTSTAMP:{st}", f"LAST-MODIFIED:{st}",
            f"SEQUENCE:{max(seq, 0)}",
            f"DTSTART:{ics_time(e['start'])}", f"DTEND:{ics_time(e['end'])}",
            f"SUMMARY:{ics_escape(e['summary'])}",
            f"DESCRIPTION:{ics_escape(e['description'])}",
            "CATEGORIES:Instagram", "STATUS:CONFIRMED",
            "BEGIN:VALARM", "ACTION:DISPLAY",
            f"DESCRIPTION:{ics_escape(e['summary'])}",
            f"TRIGGER:-PT{int(e['reminders_minutes'])}M", "END:VALARM",
            "END:VEVENT",
        ]
    lines.append("END:VCALENDAR")
    return "".join(ics_fold(l) + "\r\n" for l in lines)


# ---------------------------------------------------------------- reports

def _local(e):
    return datetime.datetime.fromisoformat(e["start"])


def print_events(result, out):
    for e in result["events"]:
        dt = _local(e)
        print(f"  {dt.strftime('%a %d %b')}  {fmt_clock(dt):>7}  {e['kind']:<9}"
              f"{e['summary']}", file=out)
        print(f"  {'':<20}{'':<9}key {e['key']}", file=out)


def print_warnings(result, out):
    for w in result["warnings"]:
        print(f"  ! {w}", file=out)


def report_parse(result, out):
    wo = datetime.date.fromisoformat(result["week_of"])
    print(f"\nIG CALENDAR  week of {wo.strftime('%a %d %b %Y')}  ({result['iso_week']})",
          file=out)
    print(RULE, file=out)
    print(f"  plan       {result['plan']}", file=out)
    print(f"  week from  {result['week_source']}", file=out)
    print(f"  time zone  {result['time_zone']}", file=out)
    print_warnings(result, out)
    print(THIN, file=out)
    print(f"  SLOTS  ({len(result['slots'])})", file=out)
    for s in result["slots"]:
        hook = (f"#{s['formula']} {s['hook']}" if s["formula"] is not None else s["hook"])
        print(f"  {s['day']}  {s['time']}  {s['format']:<9}{s['type']:<9}{hook}"
              + (f"  - {s['angle']}" if s["angle"] else "")
              + ("  (trial)" if s["trial"] else ""), file=out)
    print(THIN, file=out)
    counts = {k: sum(1 for e in result["events"] if e["kind"] == k) for k in KINDS}
    print(f"  EVENTS  ({len(result['events'])}: "
          + ", ".join(f"{v} {k}" for k, v in counts.items()) + ")", file=out)
    print_events(result, out)
    print(RULE, file=out)
    print("  Nothing is in any calendar yet. Nothing posts automatically.", file=out)


def report_checklist(result, out):
    wo = datetime.date.fromisoformat(result["week_of"])
    print(f"\nIG WEEK OF {wo.strftime('%a %d %b %Y').upper()}  ({result['time_zone']})",
          file=out)
    print(NOTHING_POSTS, file=out)
    print_warnings(result, out)
    current = None
    for e in result["events"]:
        dt = _local(e)
        if dt.date() != current:
            current = dt.date()
            print(f"\n{dt.strftime('%a %d %b').upper()}", file=out)
        label = e["summary"].removeprefix("IG prep: ").removeprefix("IG: ")
        extra = ""
        if e["kind"] == "post":
            angle = next((l[7:] for l in e["description"].splitlines()
                          if l.startswith("Angle: ")), "")
            extra = f"  - {angle}" if angle else ""
        print(f"  [ ] {fmt_clock(dt):>7}  {e['kind']:<9}{label}{extra}", file=out)
    print("", file=out)


# ---------------------------------------------------------------- CLI

def date_arg(text):
    try:
        return datetime.date.fromisoformat(text)
    except ValueError:
        raise argparse.ArgumentTypeError(f"not a date (YYYY-MM-DD): {text!r}")


def _common(p):
    p.add_argument("plan", nargs="?", help="plan.md (default: plan.md in the data dir)")
    p.add_argument("--week-of", type=date_arg, help="Monday of the week, YYYY-MM-DD")
    p.add_argument("--tz", help="IANA time zone, e.g. Europe/London (default: system)")
    p.add_argument("--skip", action="append", choices=KINDS, default=[],
                   help="leave out a kind of event (repeatable)")
    p.add_argument("--prep-at", type=clock_arg, default=(18, 0),
                   help="filming reminder time, the day before a reel (default 6pm)")
    p.add_argument("--engage-at", type=clock_arg, default=(19, 0),
                   help="engagement time on days with no post (default 7pm)")
    p.add_argument("--stories-at", type=clock_arg, default=(12, 30),
                   help="story reminder time (default 12:30pm)")
    p.add_argument("--remind", type=int, default=REMIND_MIN,
                   help="minutes before each event for the alert (default 30)")
    p.add_argument("--json", action="store_true", help="machine-readable output")
    p.add_argument("--today", type=date_arg, help=argparse.SUPPRESS)


def main(argv=None, out=None, err=None):
    out = out or sys.stdout
    err = err or sys.stderr
    ap = argparse.ArgumentParser(description="Turn plan.md into posting reminders. "
                                             "Nothing is ever posted.")
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name, hlp in [("parse", "read the plan and show the events"),
                      ("events", "the event list for the Calendar connector"),
                      ("ics", "write an .ics file to import"),
                      ("checklist", "the week as a checklist")]:
        p = sub.add_parser(name, help=hlp)
        _common(p)
        if name == "ics":
            p.add_argument("--out", help="where to write (default: data dir/ig-week-YYYY-Www.ics)")
    a = ap.parse_args(argv)

    try:
        path, text = load_plan(a.plan)
        result = build(text, week_of=a.week_of, tz_name=a.tz, today=a.today,
                       skip=set(a.skip), path=path, prep_at=a.prep_at,
                       engage_at=a.engage_at, stories_at=a.stories_at, remind=a.remind)
    except PlanError as e:
        print(f"error: {e}", file=err)
        return 2

    if a.cmd == "parse":
        if a.json:
            print(json.dumps(result, indent=2, ensure_ascii=False), file=out)
        else:
            report_parse(result, out)
    elif a.cmd == "events":
        if a.json:
            print(json.dumps(result["events"], indent=2, ensure_ascii=False), file=out)
        else:
            print_warnings(result, out)
            print_events(result, out)
    elif a.cmd == "ics":
        dest = a.out or os.path.join(data_dir(), f"ig-week-{result['iso_week']}.ics")
        dest = os.path.abspath(os.path.expanduser(dest))
        os.makedirs(os.path.dirname(dest), exist_ok=True)
        with open(dest, "w", encoding="utf-8", newline="") as f:
            f.write(to_ics(result))
        if a.json:
            print(json.dumps({"path": dest, "events": len(result["events"]),
                              "warnings": result["warnings"]}), file=out)
        else:
            print_warnings(result, out)
            print(f"Wrote {len(result['events'])} events to {dest}", file=out)
            print("Double-click it to add them to Apple Calendar, or import it in "
                  "Google Calendar (Settings, Import and export).", file=out)
    elif a.cmd == "checklist":
        if a.json:
            print(json.dumps(result["events"], indent=2, ensure_ascii=False), file=out)
        else:
            report_checklist(result, out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
