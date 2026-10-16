"""Tests for week.py. Stdlib only.

Run from the skill folder:  python3 -m unittest discover -s tests
"""

import copy
import contextlib
import datetime as dt
import io
import json
import os
import shutil
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))

import week  # noqa: E402


def example():
    return copy.deepcopy(week.EXAMPLE)


class TestMonday(unittest.TestCase):
    def test_mon_to_wed_plan_this_week(self):
        for d in ("2026-10-12", "2026-10-13", "2026-10-14"):
            self.assertEqual(week.monday_for(dt.date.fromisoformat(d)), dt.date(2026, 10, 12), d)

    def test_thu_to_sun_plan_next_week(self):
        for d in ("2026-10-15", "2026-10-16", "2026-10-18"):
            self.assertEqual(week.monday_for(dt.date.fromisoformat(d)), dt.date(2026, 10, 19), d)


class TestCheck(unittest.TestCase):
    def test_example_is_valid(self):
        errors, warnings = week.check(example())
        self.assertEqual(errors, [])

    def test_week_of_must_be_a_monday(self):
        w = example()
        w["week_of"] = "2026-10-20"
        errors, _ = week.check(w)
        self.assertTrue(any("not a Monday" in e for e in errors))

    def test_post_date_must_match_day_and_week(self):
        w = example()
        w["posts"][0]["date"] = "2026-10-20"           # a Tuesday
        errors, _ = week.check(w)
        self.assertTrue(any("is a TUE, not MON" in e for e in errors), errors)
        w["posts"][0]["date"] = "2026-10-27"
        errors, _ = week.check(w)
        self.assertTrue(any("outside the week" in e for e in errors), errors)

    def test_reel_needs_script_and_shots(self):
        w = example()
        del w["posts"][0]["script"]
        w["posts"][0]["direction"]["shots"] = []
        errors, _ = week.check(w)
        self.assertTrue(any("needs a script" in e for e in errors))
        self.assertTrue(any("shot list" in e for e in errors))

    def test_carousel_needs_slides_not_a_script(self):
        w = example()
        p = w["posts"][0]
        p["format"] = "carousel"
        del p["script"]
        errors, _ = week.check(w)
        self.assertTrue(any("at least 2 slides" in e for e in errors))
        p["slides"] = [{"title": "a"}, {"title": "b"}]
        errors, _ = week.check(w)
        self.assertEqual(errors, [])

    def test_hashtags_capped(self):
        w = example()
        w["posts"][0]["caption"]["hashtags"] = ["#a", "#b", "#c", "#d"]
        errors, warnings = week.check(w)
        self.assertEqual(errors, [])
        self.assertTrue(any("the pack uses 3" in x for x in warnings))
        w["posts"][0]["caption"]["hashtags"] = ["#%d" % i for i in range(6)]
        errors, _ = week.check(w)
        self.assertTrue(any("never more than 5" in e for e in errors))
        w["posts"][0]["caption"]["hashtags"] = ["no hash"]
        errors, _ = week.check(w)
        self.assertTrue(any("hashtags must be" in e for e in errors))

    def test_duplicate_and_bad_ids(self):
        w = example()
        w["posts"].append(copy.deepcopy(w["posts"][0]))
        errors, _ = week.check(w)
        self.assertTrue(any("duplicate id" in e for e in errors))
        w["posts"][1]["id"] = "monday"
        errors, _ = week.check(w)
        self.assertTrue(any("id must be" in e for e in errors))
        w["posts"][1]["id"] = "mon-2"
        errors, _ = week.check(w)
        self.assertEqual(errors, [])

    def test_em_dash_and_invisible_chars_flagged_then_fixed(self):
        w = example()
        w["posts"][0]["caption"]["text"] = "Ek line—teen emotions​"
        errors, _ = week.check(w)
        self.assertTrue(any("em dashes" in e for e in errors))
        fixed, n = week.fix(w)
        self.assertEqual(n, 1)
        self.assertEqual(fixed["posts"][0]["caption"]["text"], "Ek line - teen emotions")
        self.assertEqual(week.check(fixed)[0], [])


class TestPlanMd(unittest.TestCase):
    def test_plan_lines_match_ig_plan_format(self):
        w = example()
        two = copy.deepcopy(w["posts"][0])
        two.update({"id": "thu", "day": "THU", "date": "2026-10-22", "time": "07:05", "trial": True})
        w["posts"].append(two)
        text = week.plan_md(w)
        self.assertTrue(text.startswith("WEEK OF OCT 19 2026\n"))
        self.assertIn("MON  7:30pm  REEL      PROOF    #18 Cold Open Demo - One line, three emotions", text)
        self.assertIn("THU  7:05am", text)
        self.assertIn("(trial)", text)
        self.assertIn("TUE  stories only + engage", text)
        self.assertIn("WHAT YOU NEED TO DO", text)
        self.assertIn("Sat Oct 17", text)


class TestCli(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="ig-week-test-")
        self.path = os.path.join(self.tmp, "week.json")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def run_cli(self, *args):
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(io.StringIO()):
            rc = week.main(list(args))
        return rc, buf.getvalue()

    def test_check_fix_then_plan_md(self):
        w = example()
        w["headline"] = "Five reels — one lever"
        with open(self.path, "w", encoding="utf-8") as f:
            json.dump(w, f)
        rc, out = self.run_cli("check", self.path, "--json")
        self.assertEqual(rc, 1)
        self.assertFalse(json.loads(out)["ok"])
        rc, out = self.run_cli("plan-md", self.path)
        self.assertEqual(rc, 1)                                   # never writes a plan from a broken week
        rc, out = self.run_cli("check", self.path, "--fix", "--json")
        self.assertEqual(rc, 0, out)
        self.assertEqual(json.loads(out)["fixed"], 1)
        with open(self.path, encoding="utf-8") as f:
            self.assertEqual(json.load(f)["headline"], "Five reels - one lever")
        rc, out = self.run_cli("plan-md", self.path)
        self.assertEqual(rc, 0)
        self.assertTrue(os.path.isfile(os.path.join(self.tmp, "plan.md")))

    def test_unreadable_file(self):
        rc, out = self.run_cli("check", os.path.join(self.tmp, "missing.json"), "--json")
        self.assertEqual(rc, 1)
        self.assertFalse(json.loads(out)["ok"])


if __name__ == "__main__":
    unittest.main()
