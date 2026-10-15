#!/usr/bin/env python3
"""Fill a TEMP IG_HOME with sample data using the real skill scripts.

    python3 tests/seed_demo.py /tmp/some-empty-dir [--bare]

Refuses to touch ~/.claude/instagram. --bare makes an account with nothing
in it (to see the first-run wizard).
"""
import datetime as dt
import json
import os
import subprocess
import sys

SKILLS = os.path.expanduser(os.environ.get("IG_SKILLS_DIR") or "~/.claude/skills")


def run(home, *args, stdin=None):
    env = dict(os.environ, IG_HOME=home, PYTHONDONTWRITEBYTECODE="1")
    env.pop("IG_DATA_DIR", None)
    r = subprocess.run([sys.executable, "-I", os.path.join(SKILLS, args[0])] + list(args[1:]),
                       input=stdin, capture_output=True, text=True, env=env)
    if r.returncode not in (0, 1):
        raise SystemExit(f"{args}: {r.stderr or r.stdout}")
    return r.stdout


def seed(home, bare=False):
    home = os.path.abspath(home)
    real = os.path.realpath(os.path.expanduser("~/.claude/instagram"))
    if os.path.realpath(home).startswith(real):
        raise SystemExit("refusing to seed the real ~/.claude/instagram")
    os.makedirs(home, exist_ok=True)
    run(home, "ig-account/account.py", "new", "demo.creator")
    run(home, "ig-account/account.py", "use", "demo.creator")
    data = os.path.join(home, "accounts", "demo.creator")
    if bare:
        return data
    today = dt.date.today()
    run(home, "ig/state.py", "set", "--region", "IN", "--niche", "contracts and pricing for freelance designers",
        "--account-type", "creator", "--language", "en", "--goal", "10k followers")
    with open(os.path.join(data, "voice.md"), "w", encoding="utf-8") as f:
        f.write("# Voice\n\n- **Who I talk to:** freelance designers, 2-5 years in\n- **How I sound:** blunt, warm, short sentences\n"
                "- **Words I never use:** hustle, game-changer, delve\n- **Signature move:** a number in the first line\n")
    n = 1180
    for i in range(8, 0, -1):
        d = today - dt.timedelta(days=7 * i)
        n += [35, 48, 41, 60, 52, 75, 50, 65][8 - i]
        run(home, "ig-grow/grow.py", "checkin", f"--followers={n}", f"--date={d.isoformat()}", "--json")
    run(home, "ig-grow/grow.py", "checkin", f"--followers={n + 45}", "--json")
    posts = [
        (20, "reel", 3, "pricing", "Nobody tells you your first 30 clients are practice", 27, dict(views=12400, reach=9870, shares=88, saves=140, follows=41, skip_rate=31, nonfollower_pct=62)),
        (17, "carousel", "", "contracts", "The $18,000 clause", "", dict(views=5200, reach=4100, shares=40, saves=310, follows=22)),
        (14, "reel", 5, "proposals", "5 hours to 20 minutes: my proposal template", 22, dict(views=31800, reach=26000, shares=420, saves=610, follows=180, skip_rate=24, nonfollower_pct=78)),
        (11, "reel", 2, "clients", "Stop doing free discovery calls", 19, dict(views=6100, reach=5300, shares=21, saves=45, follows=9, skip_rate=44)),
        (8, "photo", "", "behind the scenes", "My desk on invoice day", "", dict(views=2100, reach=1900, saves=12, follows=2)),
        (6, "reel", 21, "refunds", "The refund email I almost sent", 31, dict(views=9800, reach=8200, shares=65, saves=90, follows=30, skip_rate=35)),
        (4, "carousel", "", "pricing", "4 ways to raise your rate without losing the client", "", dict(views=4400, reach=3800, shares=35, saves=260, follows=15)),
        (2, "reel", 9, "contracts", "POV: the client says just one small change", 16, dict(views=7300, reach=6400, shares=50, saves=70, follows=18)),
        (1, "reel", 3, "pricing", "Nobody tells you how to say your price out loud", 24, None),
    ]
    for days, fmt, formula, theme, line, length, metrics in posts:
        args = ["ig-ledger/ledger.py", "add", f"--format={fmt}", f"--date={(today - dt.timedelta(days=days)).isoformat()}",
                f"--theme={theme}", f"--first-line={line}"]
        if formula != "":
            args.append(f"--hook-formula={formula}")
        if length != "":
            args.append(f"--length={length}")
        pid = run(home, *args).strip().split()[-1]
        if metrics:
            run(home, "ig-ledger/ledger.py", "update", pid, *[f"--{k.replace('_', '-')}={v}" for k, v in metrics.items()])
        else:
            posted = (dt.datetime.now() - dt.timedelta(hours=26)).strftime("%Y-%m-%d %H:%M")
            at = (dt.datetime.now() - dt.timedelta(hours=25)).strftime("%Y-%m-%d %H:%M")
            run(home, "ig-perf/perf.py", "check", pid, "--views=900", "--reach=780", "--shares=6", f"--posted-at={posted}",
                f"--at={at}", "--hours=1", "--quiet", "--json")
    for args in (["--source=google", "--region=IN", "--kind=topic", "--name=Diwali sale prep", "--growth=+300%"],
                 ["--source=instagram", "--region=IN", "--kind=format", "--name=POV office meme", "--scope=niche", "--niche-match=2"],
                 ["--source=tiktok", "--region=IN", "--kind=song", "--name=Espresso sped up", "--growth=3x"],
                 ["--source=news", "--region=IN", "--kind=topic", "--name=New GST rules for freelancers", "--niche-match=3"]):
        run(home, "ig-trends/trends.py", "add", *args, "--json")
    run(home, "ig-trends/trends.py", "blend", "--niche=contracts and pricing for freelance designers", "--region=IN", "--json")
    for args in (["--name=Espresso", "--artist=Sabrina Carpenter", "--source=instagram", "--region=IN", "--reels-count=12K", "--trend=rising", "--bpm=104", "--mood=upbeat", "--business-ok=no"],
                 ["--name=Lofi study beat 3", "--source=instagram", "--region=IN", "--trend=peaking", "--mood=lofi", "--business-ok=yes", "--reels-count=4,100"],
                 ["--name=Kesariya (slowed)", "--artist=Arijit Singh", "--source=instagram", "--region=IN", "--trend=rising", "--mood=emotional", "--reels-count=88K"]):
        run(home, "ig-audio/audio.py", "add", *args)
    monday = today - dt.timedelta(days=today.weekday())
    with open(os.path.join(data, "plan.md"), "w", encoding="utf-8") as f:
        f.write(f"""WEEK OF {monday.strftime('%b %d').upper()}

MON  engage only  (20 min, list below)
TUE  7:30pm  REEL      PROOF    #5  Time Collapse   - 5hr proposal to 20 min
WED  stories only + engage
THU  7:00pm  CAROUSEL  TEACH    Job B caption       - the 4-slide clause breakdown
FRI  7:30pm  REEL      OPINION  #2  Negative Command - stop doing discovery calls
SAT  -
SUN  6:00pm  REEL      STORY    #21 Mid-Sentence    - the refund email

STORIES  every day, 3 to 5 frames, question box on Thursday.

ENGAGE  (5 reach / 3 peers / 2 buyers)
  @design.business   reach
  @freelance.notes   peer
""")
    run(home, "ig-test/abtest.py", "new", "--a=Nobody tells you how to price", "--b=I charged $400 for a $4,000 job",
        "--formula-a=3", "--theme=pricing", "--length=20", "--json")
    # an account scan, if ig-scan is installed
    if os.path.exists(os.path.join(SKILLS, "ig-scan", "scan.py")):
        cap = {"handle": "demo.creator", "name": "Mara | Contracts for designers",
               "bio": "Contracts and pricing for freelance designers. Free clause pack below.",
               "website": "https://example.com", "followers": n + 45, "following": 310, "posts_count": 212,
               "account_type": "creator", "category": "Education", "source": "kweo", "posts": []}
        caps = ["I lost $18,000 because of one missing line in my contract. Comment CONTRACT.",
                "Stop sending proposals before the discovery call. Here is why.",
                "3 clauses every designer needs. Save this.",
                "POV: the client says 'just one small change'.",
                "How I priced my first $5k project."]
        for i in range(18):
            t = ["reel", "carousel", "reel", "photo"][i % 4]
            cap["posts"].append({"date": (today - dt.timedelta(days=3 * i + 2)).isoformat(), "type": t, "caption": caps[i % 5],
                                 "likes": 120 + (i * 97) % 800, "comments": 5 + (i * 13) % 70,
                                 "views": 3000 + (i * 4111) % 36000 if t == "reel" else None,
                                 "url": f"https://www.instagram.com/p/DEMO{i}/"})
        os.makedirs(os.path.join(data, "scan"), exist_ok=True)
        p = os.path.join(data, "scan", "captured-demo.json")
        with open(p, "w", encoding="utf-8") as f:
            json.dump(cap, f)
        run(home, "ig-scan/scan.py", "ingest", "--captured", p)
        run(home, "ig-scan/scan.py", "analyze", "--json")
    return data


if __name__ == "__main__":
    if len(sys.argv) < 2:
        raise SystemExit(__doc__)
    print(seed(sys.argv[1], bare="--bare" in sys.argv))
