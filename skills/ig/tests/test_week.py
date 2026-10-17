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


VIRAL = {"version": 1, "made": "2026-10-16", "reels": [
    {"id": "V01", "account": "@someone", "views": 412000, "multiple": 38.4, "median": 10700,
     "hook": "1 line, 3 emotions. Which one was real?", "formula": "Cold Open Demo",
     "url": "https://www.instagram.com/reel/AAA/", "length_s": 21, "followers": 48000},
    {"id": "V02", "account": "@other", "views": 90000, "multiple": 6.0, "hook": "stop doing this"},
    {"id": "V03", "account": "@dad_a", "metric": "likes", "views": None, "likes": 2400, "multiple": 21.82,
     "hook": "Reel number 3"}]}


def viral():
    return copy.deepcopy(VIRAL)


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


class TestModel(unittest.TestCase):
    def test_reel_must_copy_a_viral_reel(self):
        w = example()
        del w["posts"][0]["model"]
        errors, _ = week.check(w)
        self.assertTrue(any("copies a reel that went viral" in e for e in errors), errors)

    def test_copy_list_required(self):
        w = example()
        w["posts"][0]["model"]["copy"] = []
        errors, _ = week.check(w)
        self.assertTrue(any("model.copy" in e for e in errors), errors)

    def test_ref_must_exist_in_viral_json(self):
        w = example()
        w["posts"][0]["model"]["ref"] = "V09"
        errors, _ = week.check(w, viral=viral())
        self.assertTrue(any("V09 is not in viral.json" in e for e in errors), errors)

    def test_without_viral_json_refs_are_only_warned(self):
        errors, warnings = week.check(example())
        self.assertEqual(errors, [])
        self.assertTrue(any("viral.json not found" in x for x in warnings))

    def test_fix_copies_the_facts_and_drops_made_up_ones(self):
        w = example()
        w["posts"][0]["model"].update({"views": 999999, "url": "https://example.com/made-up", "median": 5})
        errors, _ = week.check(w, viral=viral())
        self.assertTrue(any("differ from viral.json V01" in e for e in errors), errors)
        fixed, n = week.fix(w, viral())
        m = fixed["posts"][0]["model"]
        self.assertEqual(n, 1)
        self.assertEqual(m["views"], 412000)
        self.assertEqual(m["url"], "https://www.instagram.com/reel/AAA/")
        self.assertEqual(m["multiple"], 38.4)
        self.assertEqual(m["copy"], example()["posts"][0]["model"]["copy"])     # Claude's words stay
        self.assertEqual(week.check(fixed, viral=viral())[0], [])

    def test_fix_leaves_out_facts_viral_json_does_not_have(self):
        w = example()
        w["posts"][0]["model"].update({"ref": "V02", "url": "https://example.com/guess", "length_s": 30})
        fixed, _ = week.fix(w, viral())
        m = fixed["posts"][0]["model"]
        self.assertNotIn("url", m)
        self.assertNotIn("length_s", m)
        self.assertEqual(m["views"], 90000)

    def test_likes_model_shows_likes_in_plan(self):
        w = example()
        w["posts"][0]["model"]["ref"] = "V03"
        fixed, _ = week.fix(w, viral())
        m = fixed["posts"][0]["model"]
        self.assertEqual((m["metric"], m["likes"]), ("likes", 2400))
        self.assertNotIn("views", m)                         # null in viral.json stays out
        self.assertIn("@dad_a, 2,400 likes, 21.82x their usual", week.plan_md(fixed))

    def test_one_model_for_many_posts_is_a_warning(self):
        w = example()
        for d, day in (("2026-10-20", "TUE"), ("2026-10-21", "WED")):
            p = copy.deepcopy(w["posts"][0])
            p.update({"id": day.lower(), "day": day, "date": d})
            w["posts"].append(p)
        _, warnings = week.check(w)
        self.assertTrue(any("model for 3 posts" in x for x in warnings), warnings)

    def test_stories_need_no_model(self):
        w = example()
        p = w["posts"][0]
        p["format"] = "story"
        del p["model"]
        self.assertEqual(week.check(w)[0], [])

    def test_find_viral_from_archive(self):
        tmp = tempfile.mkdtemp()
        try:
            arch = os.path.join(tmp, ".studio", "weeks")
            os.makedirs(arch)
            with open(os.path.join(tmp, "viral.json"), "w") as f:
                json.dump(VIRAL, f)
            self.assertEqual(week.find_viral(os.path.join(arch, "2026-10-19.json")), os.path.join(tmp, "viral.json"))
            self.assertEqual(week.find_viral(os.path.join(tmp, "week.json")), os.path.join(tmp, "viral.json"))
            os.remove(os.path.join(tmp, "viral.json"))
            self.assertIsNone(week.find_viral(os.path.join(tmp, "week.json")))
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


class TestNowPost(unittest.TestCase):
    def now_post(self, date="2026-10-17", day="SAT"):
        w = example()
        p = copy.deepcopy(w["posts"][0])
        p.update({"id": "now", "day": day, "date": date, "type": "trend", "title": "His car flies too"})
        w["posts"].insert(0, p)
        return w

    def test_now_post_before_the_week_is_valid(self):
        self.assertEqual(week.check(self.now_post())[0], [])

    def test_now_post_must_be_just_before_the_week(self):
        errors, _ = week.check(self.now_post("2026-10-19", "MON"))
        self.assertTrue(any("now post is dated" in e for e in errors), errors)
        errors, _ = week.check(self.now_post("2026-10-10", "SAT"))
        self.assertTrue(any("now post is dated" in e for e in errors), errors)
        errors, _ = week.check(self.now_post("2026-10-17", "SUN"))
        self.assertTrue(any("is a SAT, not SUN" in e for e in errors), errors)

    def test_plan_md_puts_now_first_and_never_as_a_day_line(self):
        text = week.plan_md(self.now_post())
        lines = text.splitlines()
        now_line = [l for l in lines if l.startswith("NOW")][0]
        self.assertIn("Sat Oct 17 7:30pm", now_line)
        self.assertLess(lines.index(now_line), [i for i, l in enumerate(lines) if l.startswith("MON")][0])
        self.assertEqual(len([l for l in lines if l.startswith("SAT")]), 1)     # the week's own Saturday only


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

    def test_copies_section_after_fix(self):
        w, _ = week.fix(example(), viral())
        text = week.plan_md(w)
        self.assertIn("COPIES  each post copies a reel that went viral", text)
        self.assertIn("  V01  @someone, 412,000 views, 38.4x their usual  https://www.instagram.com/reel/AAA/  ->  "
                      "Mon 'One line, three emotions'", text)
        # the line does not start with a day name, so plan.md parsers don't read it as a slot
        line = [x for x in text.splitlines() if x.strip().startswith("V01")][0]
        self.assertNotRegex(line, r"^\s*(MON|TUE|WED|THU|FRI|SAT|SUN)")


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

    def write_viral(self):
        with open(os.path.join(self.tmp, "viral.json"), "w", encoding="utf-8") as f:
            json.dump(VIRAL, f)

    def test_check_needs_viral_json(self):
        with open(self.path, "w", encoding="utf-8") as f:
            json.dump(example(), f)
        rc, out = self.run_cli("check", self.path, "--json")
        self.assertEqual(rc, 1)
        self.assertIn("run /ig-viral first", json.loads(out)["errors"][0])
        self.write_viral()
        rc, out = self.run_cli("check", self.path, "--fix", "--json")
        self.assertEqual(rc, 0, out)
        with open(self.path, encoding="utf-8") as f:
            self.assertEqual(json.load(f)["posts"][0]["model"]["account"], "@someone")

    def test_check_fix_then_plan_md(self):
        self.write_viral()
        w, _ = week.fix(example(), viral())
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
