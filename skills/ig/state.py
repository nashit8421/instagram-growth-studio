#!/usr/bin/env python3
"""
state.py - where is this account, and what should happen next?

The single entry point (/ig) runs this first. It reads the active account's
data folder and prints an ordered list of next steps, each tied to a skill.
Nothing here posts, follows, likes or messages anyone. It only reads files
and runs two read-only checks (ig-perf due, ig-kweo check).

  python3 state.py                 # status + next steps
  python3 state.py --json
  python3 state.py set --region IN --niche "freelance contracts" \
        --account-type creator --language en --goal "10k followers"
  python3 state.py profile         # print profile.json

Stdlib only. Data folder: IG_DATA_DIR, else the active account
(ig-account), else ~/IGStudio.
"""

import argparse
import datetime as dt
import json
import os
import re
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
SKILLS = os.path.dirname(HERE)

PROFILE_FIELDS = ("region", "niche", "account_type", "language", "goal")
REQUIRED_PROFILE = ("region", "niche", "account_type")
ACCOUNT_TYPES = ("creator", "business")

WEEKLY_REVIEW_DAYS = 7     # a follower check-in older than this means the weekly review is due
TRENDS_STALE_DAYS = 7      # memes and topics turn over in days; refresh weekly
PLAN_STALE_DAYS = 7        # a plan covers one week
VOICE_MIN_FIELDS = 3       # filled "- **Field:** value" lines before voice.md counts as real
SCAN_STALE_DAYS = 30       # an account profile older than this gets a rescan step

DAYS = ("MON", "TUE", "WED", "THU", "FRI", "SAT", "SUN")


# ---------------------------------------------------------------- paths

def _skill(*parts):
    """Prefer the sibling install, fall back to ~/.claude/skills."""
    for base in (SKILLS, os.path.expanduser("~/.claude/skills")):
        p = os.path.join(base, *parts)
        if os.path.exists(p):
            return p
    return os.path.join(SKILLS, *parts)


def ig_home():
    return os.path.expanduser(os.environ.get("IG_HOME") or "~/IGStudio")


def active_handle(home=None):
    home = home or ig_home()
    try:
        with open(os.path.join(home, "active-account"), encoding="utf-8") as f:
            h = f.read().strip().lstrip("@").strip().lower()
    except OSError:
        return None
    if h and re.fullmatch(r"[a-z0-9._]{1,30}", h) and ".." not in h \
            and os.path.isdir(os.path.join(home, "accounts", h)):
        return h
    return None


def data_dir():
    env = os.environ.get("IG_DATA_DIR")
    if env:
        return os.path.expanduser(env)
    home = ig_home()
    h = active_handle(home)
    return os.path.join(home, "accounts", h) if h else home


def _path(name):
    return os.path.join(data_dir(), name)


def _age_days(path, today):
    try:
        m = dt.date.fromtimestamp(os.path.getmtime(path))
    except OSError:
        return None
    return (today - m).days


# ---------------------------------------------------------------- readers

def load_profile():
    try:
        with open(_path("profile.json"), encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def save_profile(updates):
    os.makedirs(data_dir(), exist_ok=True)
    prof = load_profile()
    prof.update({k: v for k, v in updates.items() if v is not None})
    tmp = _path("profile.json.tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(prof, f, indent=2, ensure_ascii=False)
        f.write("\n")
    os.replace(tmp, _path("profile.json"))
    return prof


def voice_status():
    """missing | template | filled"""
    try:
        with open(_path("voice.md"), encoding="utf-8") as f:
            text = f.read()
    except OSError:
        return "missing"
    filled = 0
    for line in text.splitlines():
        m = re.match(r"\s*-\s*\*\*[^*]+:\*\*\s*(.*)$", line)
        if m and m.group(1).strip() and not m.group(1).strip().startswith("("):
            filled += 1
    # A voice.md written by Claude from the user's reels may not use the
    # template's field lines at all; treat substantial free text as filled.
    words = len(re.findall(r"\w+", text))
    if filled >= VOICE_MIN_FIELDS or ("Copy this to" not in text and words > 120):
        return "filled"
    return "template"


def scan_summary(today):
    """What /ig-scan learned, from account.json in the data folder. None if never scanned."""
    p = _path("account.json")
    try:
        with open(p, encoding="utf-8") as f:
            a = json.load(f)
    except (OSError, ValueError):
        return None
    if not isinstance(a, dict):
        return None
    scanned = None
    try:
        scanned = dt.date.fromisoformat(str(a.get("scanned_at") or "")[:10])
    except ValueError:
        pass
    age = (today - scanned).days if scanned else _age_days(p, today)
    size = a.get("size") if isinstance(a.get("size"), dict) else {}
    niche = a.get("niche_guess") if isinstance(a.get("niche_guess"), dict) else {}
    return {"handle": a.get("handle"), "scanned": scanned.isoformat() if scanned else None,
            "age_days": age, "size_tier": size.get("tier"), "followers": size.get("followers"),
            "niche_guess": niche.get("label"), "posts": a.get("n_feed"),
            "has_read": os.path.exists(_path("account.md"))}


def last_checkin():
    try:
        with open(_path("followers.csv"), encoding="utf-8") as f:
            rows = [l.strip() for l in f if l.strip()]
    except OSError:
        return None, None
    best = None
    for line in rows[1:]:
        parts = line.split(",")
        try:
            d = dt.date.fromisoformat(parts[0])
            n = int(float(parts[1]))
        except (ValueError, IndexError):
            continue
        if best is None or d >= best[0]:
            best = (d, n)
    return best if best else (None, None)


def ledger_summary(today):
    try:
        with open(_path("posts.csv"), encoding="utf-8-sig") as f:
            lines = [l for l in f.read().splitlines() if l.strip()]
    except OSError:
        return {"posts": 0, "last_post": None, "posts_last_7d": 0}
    import csv
    rows = list(csv.DictReader(lines))
    dates = []
    for r in rows:
        try:
            dates.append(dt.date.fromisoformat((r.get("date") or "")[:10]))
        except ValueError:
            pass
    last = max(dates) if dates else None
    recent = sum(1 for d in dates if 0 <= (today - d).days < 7)
    return {"posts": len(rows), "last_post": last.isoformat() if last else None,
            "posts_last_7d": recent}


def todays_slot(today):
    """The plan.md line for today's weekday, if the plan is current."""
    p = _path("plan.md")
    age = _age_days(p, today)
    if age is None or age > PLAN_STALE_DAYS:
        return None
    try:
        with open(p, encoding="utf-8") as f:
            lines = f.read().splitlines()
    except OSError:
        return None
    day = DAYS[today.weekday()]
    for line in lines:
        m = re.match(rf"\s*{day}\b\s+(.*)$", line, re.IGNORECASE)
        if m:
            text = re.sub(r"\s{2,}", "  ", m.group(1).strip())
            if not text or text == "-":
                return {"day": day, "text": "-", "format": None, "rest": True}
            fmt = None
            for f_ in ("REEL", "CAROUSEL", "STORY", "PHOTO"):
                if re.search(rf"\b{f_}\b", text, re.IGNORECASE):
                    fmt = f_.lower()
                    break
            return {"day": day, "text": text, "format": fmt, "rest": False}
    return None


def _run_json(args, timeout=20):
    try:
        r = subprocess.run([sys.executable, "-I"] + args, capture_output=True,
                           text=True, timeout=timeout, env=_child_env())
        return json.loads(r.stdout) if r.stdout.strip() else None
    except (OSError, ValueError, subprocess.SubprocessError):
        return None


def _child_env():
    env = dict(os.environ)
    env["IG_DATA_DIR"] = data_dir()     # children see the same account
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    return env


def perf_due():
    script = _skill("ig-perf", "perf.py")
    if not os.path.exists(script):
        return []
    out = _run_json([script, "due", "--json"])
    return out if isinstance(out, list) else []


def kweo_status():
    script = _skill("ig-kweo", "kweo_check.py")
    if not os.path.exists(script):
        return {"ready": False, "next": "ig-kweo is not installed."}
    out = _run_json([script, "--json"], timeout=15)
    return out if isinstance(out, dict) else {"ready": False, "next": "kweo check failed to run."}


# ---------------------------------------------------------------- the decision

def build_state(today=None, checks=True):
    today = today or dt.date.today()
    prof = load_profile()
    voice = voice_status()
    ck_date, ck_n = last_checkin()
    led = ledger_summary(today)
    trends_age = _age_days(_path("trends.md"), today)
    plan_age = _age_days(_path("plan.md"), today)
    slot = todays_slot(today)
    due = perf_due() if checks else []
    kweo = kweo_status() if checks else {"ready": None}
    scan = scan_summary(today)

    steps = []

    def add(key, skill, why, ask=None, blocking=False):
        steps.append({"key": key, "skill": skill, "why": why, "ask": ask, "blocking": blocking})

    # 1. setup, in the order the rest depends on. The scan comes first: it
    #    can prefill the profile and draft voice.md from real captions.
    if scan is None:
        add("scan", "/ig-scan", "Every recommendation should start from the real account: its niche, "
            "size, what it posts and what works. No account profile yet.",
            ask="Which Instagram account are we growing? Your handle, and how should I read it: "
                "kweo browser (default, you stay logged in there), your data export, screenshots, "
                "or an official API token?",
            blocking=True)
    missing = [f for f in REQUIRED_PROFILE if not prof.get(f)]
    if missing:
        if scan:
            add("profile", "/ig", "Every skill needs to know where you post, about what, and your account type. "
                "Fill it from `scan.py prefill` and Claude's read, save it, and say what was assumed.")
        else:
            add("profile", "/ig", "Every skill needs to know where you post, about what, and your account type.",
                ask="Which country or region is your audience in, what is your niche in a few words, "
                    "and is your Instagram a creator or business account? (Optional: language, goal.)",
                blocking=True)
    if voice != "filled":
        why = "Scripts have to sound like you. voice.md is " + (
            "missing." if voice == "missing" else "still the empty template.")
        if scan:
            add("voice", "/ig-reel", why + " Draft it from the scanned captions and save it.")
        else:
            add("voice", "/ig-reel", why,
                ask="Paste three of your own captions or reel transcripts (or answer the voice.md questions).",
                blocking=True)
    if ck_date is None:
        if scan and isinstance(scan.get("followers"), int):
            add("baseline", "/ig-grow", "Growth is measured from a starting point. "
                f"Check in the scanned {scan['followers']:,} followers.")
        else:
            add("baseline", "/ig-grow", "Growth is measured from a starting point.",
                ask="How many followers do you have right now?", blocking=True)
    if led["posts"] == 0 and not missing and voice == "filled":
        add("profile_score", "/ig-profile", "Your profile converts viewers into followers. Fix it before pushing reach.",
            ask="Send a screenshot of the top of your profile and the first two grid rows.")

    # 2. things with a clock on them
    if scan is not None and scan["age_days"] is not None and scan["age_days"] > SCAN_STALE_DAYS:
        add("rescan", "/ig-scan", f"The account profile is {scan['age_days']} days old. "
            "Rescan so the advice uses the last month of posts.")
    if due:
        ids = ", ".join(f"{d.get('post_id')} ({d.get('checkpoint')})" for d in due)
        add("perf", "/ig-perf", f"Checks due now: {ids}.",
            ask="Open each reel, tap View insights, and screenshot or read off the numbers.")
    if ck_date is not None and (today - ck_date).days >= WEEKLY_REVIEW_DAYS:
        add("weekly_review", "/ig-grow", f"Last follower check-in was {(today - ck_date).days} days ago. "
            "Time for the weekly review.", ask="How many followers do you have today?")
    if not missing and (trends_age is None or trends_age > TRENDS_STALE_DAYS):
        add("trends", "/ig-trends", "No trend board yet." if trends_age is None
            else f"Trend board is {trends_age} days old.")
    if plan_age is None or plan_age > PLAN_STALE_DAYS:
        add("plan", "/ig-plan", ("No plan for this week." if plan_age is None
            else f"Plan is {plan_age} days old.") + " Build it from the account; use any moments the user mentioned.")
        add("calendar", "/ig-calendar", "Turn the plan into reminders (asks before adding anything).")

    # 3. today's work
    if slot and not slot["rest"]:
        route = {"reel": "/ig-reel -> /ig-audio -> (you film) -> /ig-edit -> /ig-caption",
                 "carousel": "/ig-carousel -> /ig-render -> /ig-caption",
                 "story": "/ig-story -> /ig-render",
                 "photo": "/ig-caption"}.get(slot["format"], "/ig-reel")
        add("create_today", route, f"Today ({slot['day']}): {slot['text']}")
    add("engage", "/ig-comment", "20 minutes of real comments on the accounts in your plan, by hand.")

    return {
        "date": today.isoformat(),
        "account": active_handle() or "(single account)",
        "data_dir": data_dir(),
        "profile": prof,
        "voice": voice,
        "followers": {"last_checkin": ck_date.isoformat() if ck_date else None, "count": ck_n},
        "ledger": led,
        "trends_age_days": trends_age,
        "plan_age_days": plan_age,
        "today": slot,
        "perf_due": due,
        "kweo": {"ready": kweo.get("ready"), "next": kweo.get("next")},
        "scan": scan,
        "stage": "setup" if any(s["blocking"] for s in steps) else "run",
        "next": steps,
    }


def render(st, out=None):
    out = out or sys.stdout
    p = lambda *a: print(*a, file=out)  # noqa: E731
    prof = st["profile"]
    p("")
    p(f"IG  ·  @{st['account'].lstrip('@')}  ·  {st['date']}  ·  stage: {st['stage'].upper()}")
    p("=" * 72)
    p(f"  niche      {prof.get('niche') or '-'}   region {prof.get('region') or '-'}   "
      f"account {prof.get('account_type') or '-'}")
    sc = st.get("scan")
    if sc:
        p(f"  scan       {sc.get('size_tier') or '-'}, niche guess {sc.get('niche_guess') or '-'}, "
          f"scanned {sc.get('scanned') or '-'}")
    else:
        p("  scan       not yet (/ig-scan)")
    p(f"  voice      {st['voice']}")
    f = st["followers"]
    p(f"  followers  {f['count'] if f['count'] is not None else '-'}"
      f"{'  (checked ' + f['last_checkin'] + ')' if f['last_checkin'] else ''}")
    led = st["ledger"]
    p(f"  posts      {led['posts']} logged, {led['posts_last_7d']} in the last 7 days")
    p(f"  browsing   {'kweo ready' if st['kweo']['ready'] else 'kweo not connected (web search fallback)'}")
    p("-" * 72)
    p("NEXT")
    for i, s in enumerate(st["next"], 1):
        p(f"  {i}. {s['skill']}")
        p(f"     {s['why']}")
        if s["ask"]:
            p(f"     ask: {s['ask']}")
    p("")
    p("  Nothing is posted by any of this. You post.")
    p("")


# ---------------------------------------------------------------- cli

def main(argv=None):
    ap = argparse.ArgumentParser(description="Where this account is, and what to do next.")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--today", help=argparse.SUPPRESS)
    ap.add_argument("--no-checks", action="store_true", help="skip the perf and kweo checks")
    sub = ap.add_subparsers(dest="cmd")
    s = sub.add_parser("set", help="save region, niche, account type, language, goal")
    s.add_argument("--region")
    s.add_argument("--niche")
    s.add_argument("--account-type", choices=ACCOUNT_TYPES)
    s.add_argument("--language")
    s.add_argument("--goal")
    sub.add_parser("profile", help="print profile.json")
    args = ap.parse_args(argv)

    if args.cmd == "set":
        updates = {"region": args.region.upper() if args.region and len(args.region) <= 3 else args.region,
                   "niche": args.niche, "account_type": args.account_type,
                   "language": args.language, "goal": args.goal}
        if all(v is None for v in updates.values()):
            ap.error("give at least one of --region --niche --account-type --language --goal")
        print(json.dumps(save_profile(updates), indent=2, ensure_ascii=False))
        return 0
    if args.cmd == "profile":
        print(json.dumps(load_profile(), indent=2, ensure_ascii=False))
        return 0

    today = dt.date.fromisoformat(args.today) if args.today else None
    st = build_state(today, checks=not args.no_checks)
    if args.json:
        print(json.dumps(st, indent=2, ensure_ascii=False))
    else:
        render(st)
    return 0


if __name__ == "__main__":
    sys.exit(main())
