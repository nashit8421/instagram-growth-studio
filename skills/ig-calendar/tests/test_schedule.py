"""Tests for schedule.py. Stdlib only.

Run from the skill folder:  python3 -m unittest discover -s tests
Every test points IG_DATA_DIR / IG_HOME at a fresh temp dir. The real
~/.claude/instagram is never touched.
"""

import contextlib
import datetime
import io
import json
import os
import re
import shutil
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
SKILL = os.path.dirname(HERE)
FIXTURE = os.path.join(HERE, "fixtures", "plan_example.md")
sys.path.insert(0, SKILL)

import schedule  # noqa: E402

with open(FIXTURE, encoding="utf-8") as _f:
    PLAN = _f.read()

LONDON = "Europe/London"


class TempEnv(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="ig-calendar-test-")
        self._old = {k: os.environ.get(k) for k in ("IG_DATA_DIR", "IG_HOME")}
        os.environ["IG_DATA_DIR"] = self.tmp
        os.environ["IG_HOME"] = os.path.join(self.tmp, "home")

    def tearDown(self):
        for k, v in self._old.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        shutil.rmtree(self.tmp, ignore_errors=True)

    def write_plan(self, text=PLAN, name="plan.md"):
        path = os.path.join(self.tmp, name)
        with open(path, "w", encoding="utf-8") as f:
            f.write(text)
        return path

    def run_cli(self, *argv):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = schedule.main(list(argv), out=out, err=err)
        return code, out.getvalue(), err.getvalue()


def build(**kw):
    kw.setdefault("tz_name", LONDON)
    kw.setdefault("today", datetime.date(2025, 9, 10))
    return schedule.build(PLAN, **kw)


def by_key(result):
    return {e["key"]: e for e in result["events"]}


class TestParseExample(unittest.TestCase):
    def test_slots_exact(self):
        r = build()
        self.assertEqual(r["week_of"], "2025-09-15")
        self.assertEqual(r["week_source"], "header")
        slots = [{k: s[k] for k in ("day", "time", "format", "type", "formula", "hook",
                                    "angle", "trial")} for s in r["slots"]]
        self.assertEqual(slots, [
            {"day": "TUE", "time": "19:30", "format": "REEL", "type": "PROOF",
             "formula": 5, "hook": "Time Collapse", "angle": "5hr proposal to 20 min",
             "trial": False},
            {"day": "THU", "time": "19:00", "format": "CAROUSEL", "type": "TEACH",
             "formula": None, "hook": "Job B caption",
             "angle": "the 4-slide clause breakdown", "trial": False},
            {"day": "FRI", "time": "19:30", "format": "REEL", "type": "OPINION",
             "formula": 2, "hook": "Negative Command",
             "angle": "stop doing discovery calls", "trial": False},
            {"day": "SUN", "time": "18:00", "format": "REEL", "type": "STORY",
             "formula": 21, "hook": "Mid-Sentence", "angle": "the refund email",
             "trial": False},
        ])

    def test_event_counts_and_keys(self):
        r = build()
        kinds = [e["kind"] for e in r["events"]]
        self.assertEqual(kinds.count("post"), 4)
        self.assertEqual(kinds.count("prep"), 3)      # reels only
        self.assertEqual(kinds.count("engage"), 6)    # not on the SAT rest day
        self.assertEqual(kinds.count("stories"), 7)   # every day
        keys = set(by_key(r))
        for k in ("ig-2025-W38-tue-reel", "ig-2025-W38-thu-carousel",
                  "ig-2025-W38-fri-reel", "ig-2025-W38-sun-reel",
                  "ig-2025-W38-tue-reel-prep", "ig-2025-W38-mon-engage",
                  "ig-2025-W38-wed-engage", "ig-2025-W38-thu-stories"):
            self.assertIn(k, keys)
        self.assertNotIn("ig-2025-W38-sat-engage", keys)
        self.assertNotIn("ig-2025-W38-thu-carousel-prep", keys)
        self.assertEqual(len(keys), len(r["events"]))

    def test_post_event(self):
        e = by_key(build())["ig-2025-W38-tue-reel"]
        self.assertEqual(e["summary"], "IG: REEL · PROOF · Time Collapse")
        self.assertEqual(e["start"], "2025-09-16T19:30:00+01:00")
        self.assertEqual(e["end"], "2025-09-16T20:00:00+01:00")
        self.assertEqual(e["reminders_minutes"], 30)
        d = e["description"]
        self.assertIn("Angle: 5hr proposal to 20 min", d)
        self.assertIn("#5 Time Collapse", d)
        for skill in ("/ig-reel", "/ig-edit", "/ig-caption"):
            self.assertIn(skill, d)
        self.assertIn("Nothing posts automatically", d)
        self.assertTrue(d.endswith("[ig:ig-2025-W38-tue-reel]"))
        c = e["connector"]
        self.assertEqual(c["startTime"], "2025-09-16T19:30:00")
        self.assertEqual(c["timeZone"], LONDON)
        self.assertEqual(c["overrideReminders"], [{"method": "popup", "minutes": 30}])

    def test_carousel_skills(self):
        d = by_key(build())["ig-2025-W38-thu-carousel"]["description"]
        self.assertIn("/ig-render", d)
        self.assertIn("/ig-carousel", d)
        self.assertIn("Hook: Job B caption", d)

    def test_prep_day_before_6pm_60min(self):
        e = by_key(build())["ig-2025-W38-tue-reel-prep"]
        self.assertEqual(e["summary"], "IG prep: Film Tuesday's reel")
        self.assertEqual(e["start"], "2025-09-15T18:00:00+01:00")
        self.assertEqual(e["end"], "2025-09-15T19:00:00+01:00")

    def test_engage_before_post_and_default(self):
        ev = by_key(build())
        self.assertEqual(ev["ig-2025-W38-tue-engage"]["start"], "2025-09-16T19:00:00+01:00")
        self.assertEqual(ev["ig-2025-W38-tue-engage"]["end"], "2025-09-16T19:20:00+01:00")
        self.assertEqual(ev["ig-2025-W38-mon-engage"]["start"], "2025-09-15T19:00:00+01:00")
        self.assertIn("/ig-comment", ev["ig-2025-W38-mon-engage"]["description"])

    def test_stories_day_note(self):
        ev = by_key(build())
        self.assertIn("question box", ev["ig-2025-W38-thu-stories"]["description"])
        self.assertIn("question box", ev["ig-2025-W38-thu-stories"]["summary"])
        self.assertNotIn("question box", ev["ig-2025-W38-mon-stories"]["description"])
        self.assertIn("3 to 5 frames", ev["ig-2025-W38-mon-stories"]["description"])

    def test_sorted(self):
        starts = [datetime.datetime.fromisoformat(e["start"]) for e in build()["events"]]
        self.assertEqual(starts, sorted(starts))

    def test_skip(self):
        r = build(skip={"stories", "prep"})
        self.assertEqual({e["kind"] for e in r["events"]}, {"post", "engage"})

    def test_trial_and_variants(self):
        text = ("WEEK OF OCT 19 2026\n"
                "TUE  7pm  REEL  TEACH  #3 Contrarian  - one thing (trial)\n"
                "TUE  21:00  REEL  OPINION  - late one\n"
                "WED  8:15am  CAROUSEL  OFFER  - what I sell\n")
        r = schedule.build(text, tz_name=LONDON, today=datetime.date(2026, 10, 15))
        s = r["slots"]
        self.assertTrue(s[0]["trial"])
        self.assertEqual(s[0]["time"], "19:00")
        self.assertEqual(s[1]["time"], "21:00")
        self.assertEqual(s[1]["hook"], "")
        self.assertEqual(s[1]["angle"], "late one")
        self.assertEqual(s[0]["key"], "ig-2026-W43-tue-reel")
        self.assertEqual(s[1]["key"], "ig-2026-W43-tue-reel-2")
        self.assertIn("Trial Reel", by_key(r)["ig-2026-W43-tue-reel"]["description"])
        self.assertEqual(r["stories"], None)


class TestWeekAndTime(unittest.TestCase):
    def test_header_year_nearest(self):
        r = build(today=datetime.date(2026, 10, 15))
        # SEP 15 2026 is a Tuesday: the week is the one that holds it.
        self.assertEqual(r["week_of"], "2026-09-14")
        self.assertTrue(any("already over" in w for w in r["warnings"]))

    def test_header_across_new_year(self):
        text = "WEEK OF JAN 4\nMON  7pm  REEL  PROOF  - x\n"
        r = schedule.build(text, tz_name=LONDON, today=datetime.date(2026, 12, 28))
        self.assertEqual(r["week_of"], "2027-01-04")

    def test_no_header_next_monday(self):
        text = "TUE  7:30pm  REEL  PROOF  #5 Time Collapse - x\n"
        r = schedule.build(text, tz_name=LONDON, today=datetime.date(2026, 10, 15))
        self.assertEqual(r["week_of"], "2026-10-19")
        self.assertEqual(r["week_source"], "next Monday")

    def test_week_of_overrides_and_snaps(self):
        r = build(week_of=datetime.date(2026, 10, 21))
        self.assertEqual(r["week_of"], "2026-10-19")
        self.assertTrue(any("not a Monday" in w for w in r["warnings"]))

    def test_dst_boundary_london(self):
        # Clocks go back at 2am on Sun 25 Oct 2026.
        ev = by_key(build(week_of=datetime.date(2026, 10, 19)))
        self.assertEqual(ev["ig-2026-W43-tue-reel"]["start"], "2026-10-20T19:30:00+01:00")
        self.assertEqual(ev["ig-2026-W43-sun-reel"]["start"], "2026-10-25T18:00:00+00:00")
        self.assertEqual(ev["ig-2026-W43-sun-engage"]["start"], "2026-10-25T17:30:00+00:00")
        self.assertEqual(schedule.ics_time(ev["ig-2026-W43-tue-reel"]["start"]),
                         "20261020T183000Z")
        self.assertEqual(schedule.ics_time(ev["ig-2026-W43-sun-reel"]["start"]),
                         "20261025T180000Z")

    def test_dst_boundary_new_york_and_gap(self):
        text = "SUN  2:30am  REEL  PROOF  - spring gap\nSAT  1:30am  REEL  TEACH  - x\n"
        # 2026-03-08: 2am does not exist in New York.
        r = schedule.build(text, tz_name="America/New_York",
                           week_of=datetime.date(2026, 3, 2), today=datetime.date(2026, 3, 1))
        ev = by_key(r)
        sun = ev["ig-2026-W10-sun-reel"]
        self.assertEqual(sun["start"], "2026-03-08T03:30:00-04:00")
        self.assertEqual(ev["ig-2026-W10-sat-reel"]["start"], "2026-03-07T01:30:00-05:00")
        # Prep for Sunday: Saturday 6pm EST.
        self.assertEqual(ev["ig-2026-W10-sun-reel-prep"]["start"], "2026-03-07T18:00:00-05:00")

    def test_other_zone(self):
        ev = by_key(build(tz_name="Asia/Kolkata"))
        self.assertEqual(ev["ig-2025-W38-tue-reel"]["start"], "2025-09-16T19:30:00+05:30")

    def test_bad_tz(self):
        with self.assertRaises(schedule.PlanError):
            build(tz_name="Mars/Olympus")

    def test_clock(self):
        self.assertEqual(schedule.parse_clock("7:30pm"), (19, 30))
        self.assertEqual(schedule.parse_clock("12am"), (0, 0))
        self.assertEqual(schedule.parse_clock("12:15 PM"), (12, 15))
        self.assertEqual(schedule.parse_clock("06:05"), (6, 5))
        for bad in ("7", "13pm", "25:00", "x"):
            with self.assertRaises(ValueError):
                schedule.parse_clock(bad)

    def test_system_tz_from_symlink(self):
        tmp = tempfile.mkdtemp(prefix="ig-calendar-tz-")
        try:
            target = os.path.join(tmp, "zoneinfo", "Europe", "London")
            os.makedirs(os.path.dirname(target))
            open(target, "w").close()
            link = os.path.join(tmp, "localtime")
            os.symlink(target, link)
            self.assertEqual(schedule.system_tz(link), "Europe/London")
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


class TestStableKeys(unittest.TestCase):
    def test_same_input_same_keys(self):
        a = [e["key"] for e in build()["events"]]
        b = [e["key"] for e in build()["events"]]
        self.assertEqual(a, b)

    def test_keys_ignore_time_and_angle_edits(self):
        edited = PLAN.replace("7:30pm  REEL      PROOF", "8:00pm  REEL      PROOF") \
                     .replace("5hr proposal to 20 min", "a different angle")
        r = schedule.build(edited, tz_name=LONDON, today=datetime.date(2025, 9, 10))
        self.assertEqual({e["key"] for e in r["events"]}, set(by_key(build())))
        self.assertEqual(by_key(r)["ig-2025-W38-tue-reel"]["start"],
                         "2025-09-16T20:00:00+01:00")

    def test_keys_change_with_week(self):
        k = set(by_key(build(week_of=datetime.date(2026, 10, 19))))
        self.assertIn("ig-2026-W43-tue-reel", k)
        self.assertFalse(k & set(by_key(build())))

    def test_key_shape(self):
        for e in build()["events"]:
            self.assertRegex(e["key"], r"^ig-\d{4}-W\d{2}-(mon|tue|wed|thu|fri|sat|sun)-[a-z0-9-]+$")
            self.assertTrue(e["description"].endswith(f"[ig:{e['key']}]"))
            self.assertEqual(e["uid"], f"{e['key']}@ig-calendar")


def unfold(ics):
    return ics.replace("\r\n ", "")


class TestICS(unittest.TestCase):
    STAMP = datetime.datetime(2026, 10, 15, 9, 0, tzinfo=datetime.timezone.utc)

    def ics(self, **kw):
        return schedule.to_ics(build(**kw), stamp=self.STAMP)

    def test_crlf_and_structure(self):
        s = self.ics()
        self.assertTrue(s.startswith("BEGIN:VCALENDAR\r\nVERSION:2.0\r\n"))
        self.assertTrue(s.endswith("END:VCALENDAR\r\n"))
        self.assertNotIn("\n", s.replace("\r\n", ""))
        self.assertNotIn("\r", s.replace("\r\n", ""))
        self.assertEqual(s.count("BEGIN:VEVENT"), 20)
        self.assertEqual(s.count("END:VEVENT"), 20)
        self.assertEqual(s.count("BEGIN:VALARM"), 20)
        self.assertEqual(s.count("TRIGGER:-PT30M"), 20)
        self.assertIn("PRODID:", s)

    def test_line_length_octets(self):
        s = self.ics()
        for line in s.split("\r\n"):
            self.assertLessEqual(len(line.encode("utf-8")), 75, line)

    def test_fold_utf8_safe(self):
        line = "SUMMARY:" + "·é" * 80
        folded = schedule.ics_fold(line)
        for part in folded.split("\r\n"):
            self.assertLessEqual(len(part.encode("utf-8")), 75)
            part.encode("utf-8").decode("utf-8")
        self.assertEqual(folded.replace("\r\n ", ""), line)
        self.assertEqual(schedule.ics_fold("SHORT:x"), "SHORT:x")

    def test_escaping(self):
        self.assertEqual(schedule.ics_escape("a,b;c\\d\ne"), "a\\,b\\;c\\\\d\\ne")
        text = PLAN.replace("5hr proposal to 20 min", "price; scope, and a\\slash")
        r = schedule.build(text, tz_name=LONDON, today=datetime.date(2025, 9, 10))
        s = unfold(schedule.to_ics(r, stamp=self.STAMP))
        self.assertIn("Angle: price\\; scope\\, and a\\\\slash\\n", s)
        for line in s.split("\r\n"):
            if line.startswith(("SUMMARY:", "DESCRIPTION:")):
                body = line.split(":", 1)[1]
                self.assertIsNone(re.search(r"(?<!\\)(?:\\\\)*[,;]", body.replace("\\,", "")
                                            .replace("\\;", "")), line)

    def test_utc_times(self):
        s = unfold(self.ics())
        block = s.split("UID:ig-2025-W38-tue-reel@ig-calendar")[1].split("END:VEVENT")[0]
        self.assertIn("DTSTART:20250916T183000Z", block)
        self.assertIn("DTEND:20250916T190000Z", block)
        self.assertIn("SUMMARY:IG: REEL · PROOF · Time Collapse", block)

    def test_stable_uids(self):
        a = re.findall(r"UID:(.+)\r\n", self.ics())
        b = re.findall(r"UID:(.+)\r\n", schedule.to_ics(build()))
        self.assertEqual(a, b)
        self.assertEqual(len(a), len(set(a)))
        self.assertIn("ig-2025-W38-tue-reel@ig-calendar", a)

    def test_sequence_grows(self):
        later = self.STAMP + datetime.timedelta(days=1)
        r = build()
        s1 = int(re.search(r"SEQUENCE:(\d+)", schedule.to_ics(r, stamp=self.STAMP)).group(1))
        s2 = int(re.search(r"SEQUENCE:(\d+)", schedule.to_ics(r, stamp=later)).group(1))
        self.assertGreater(s2, s1)


class TestCLI(TempEnv):
    def test_missing_plan(self):
        code, out, err = self.run_cli("parse", "--tz", LONDON)
        self.assertEqual(code, 2)
        self.assertIn("No plan found", err)
        self.assertIn("/ig-plan", err)
        self.assertIn(os.path.join(self.tmp, "plan.md"), err)

    def test_missing_explicit_path(self):
        code, _, err = self.run_cli("events", os.path.join(self.tmp, "nope.md"), "--json")
        self.assertEqual(code, 2)
        self.assertIn("nope.md", err)

    def test_empty_plan(self):
        p = self.write_plan("just some notes\n")
        code, _, err = self.run_cli("parse", p, "--tz", LONDON)
        self.assertEqual(code, 2)
        self.assertIn("No day lines", err)

    def test_default_plan_in_data_dir(self):
        self.write_plan()
        code, out, _ = self.run_cli("events", "--json", "--tz", LONDON, "--today", "2025-09-10")
        self.assertEqual(code, 0)
        ev = json.loads(out)
        self.assertEqual(len(ev), 20)
        for e in ev:
            for f in ("summary", "description", "start", "end", "reminders_minutes", "key"):
                self.assertIn(f, e)

    def test_parse_text_and_json(self):
        p = self.write_plan()
        code, out, _ = self.run_cli("parse", p, "--tz", LONDON, "--today", "2025-09-10")
        self.assertEqual(code, 0)
        self.assertIn("ig-2025-W38-tue-reel", out)
        self.assertIn("Nothing posts automatically", out)
        code, out, _ = self.run_cli("parse", p, "--tz", LONDON, "--today", "2025-09-10",
                                    "--json")
        d = json.loads(out)
        self.assertEqual(d["week_of"], "2025-09-15")
        self.assertEqual(len(d["slots"]), 4)

    def test_ics_writes_file(self):
        p = self.write_plan()
        dest = os.path.join(self.tmp, "out", "week.ics")
        code, out, _ = self.run_cli("ics", p, "--out", dest, "--tz", LONDON,
                                    "--week-of", "2026-10-19")
        self.assertEqual(code, 0)
        with open(dest, "rb") as f:
            raw = f.read()
        self.assertTrue(raw.startswith(b"BEGIN:VCALENDAR\r\n"))
        self.assertIn(b"UID:ig-2026-W43-tue-reel@ig-calendar\r\n", raw)
        self.assertIn("Double-click", out)

    def test_ics_default_path(self):
        self.write_plan()
        code, out, _ = self.run_cli("ics", "--tz", LONDON, "--week-of", "2026-10-19", "--json")
        self.assertEqual(code, 0)
        d = json.loads(out)
        self.assertEqual(d["path"], os.path.join(self.tmp, "ig-week-2026-W43.ics"))
        self.assertTrue(os.path.isfile(d["path"]))

    def test_checklist(self):
        p = self.write_plan()
        code, out, _ = self.run_cli("checklist", p, "--tz", LONDON, "--week-of", "2026-10-19")
        self.assertEqual(code, 0)
        self.assertIn("TUE 20 OCT", out)
        self.assertIn("[ ]  7:30pm  post", out)
        self.assertIn("Film Tuesday's reel", out)

    def test_bad_args(self):
        p = self.write_plan()
        with self.assertRaises(SystemExit):
            self.run_cli("parse", p, "--week-of", "15/09/2025")
        code, _, err = self.run_cli("parse", p, "--tz", "Nowhere/Land")
        self.assertEqual(code, 2)
        self.assertIn("Unknown time zone", err)


class TestDataDir(TempEnv):
    def test_env_wins(self):
        self.assertEqual(schedule.data_dir(), self.tmp)

    def test_active_account(self):
        os.environ.pop("IG_DATA_DIR")
        home = os.environ["IG_HOME"]
        self.assertEqual(schedule.data_dir(), home)
        os.makedirs(os.path.join(home, "accounts", "studio"))
        with open(os.path.join(home, "active-account"), "w") as f:
            f.write("@studio\n")
        self.assertEqual(schedule.data_dir(), os.path.join(home, "accounts", "studio"))

    def test_active_account_missing_dir(self):
        os.environ.pop("IG_DATA_DIR")
        home = os.environ["IG_HOME"]
        os.makedirs(home)
        with open(os.path.join(home, "active-account"), "w") as f:
            f.write("ghost")
        self.assertEqual(schedule.data_dir(), home)

    def test_active_account_traversal(self):
        os.environ.pop("IG_DATA_DIR")
        home = os.environ["IG_HOME"]
        os.makedirs(os.path.join(home, "accounts"))
        with open(os.path.join(home, "active-account"), "w") as f:
            f.write("../..")
        self.assertEqual(schedule.data_dir(), home)


if __name__ == "__main__":
    unittest.main()
