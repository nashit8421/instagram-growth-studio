"""
Tests for grow.py. Run from the ig-grow folder:

    python3 -m unittest discover -s tests

Every test points IG_DATA_DIR (or IG_HOME) at its own temp dir. Nothing here
reads or writes ~/.claude/instagram or ~/.claude/skills.
"""

import contextlib
import csv
import datetime as dt
import io
import json
import os
import shutil
import sys
import tempfile
import unittest

TESTS = os.path.dirname(os.path.abspath(__file__))
SKILL = os.path.dirname(TESTS)

# Guard: never let an import-time default reach the real data dir.
os.environ["IG_DATA_DIR"] = tempfile.mkdtemp(prefix="iggrow-import-")
os.environ["IG_HOME"] = tempfile.mkdtemp(prefix="iggrow-home-")

sys.path.insert(0, SKILL)
import grow  # noqa: E402

LEDGER_COLUMNS = ("id,date,format,theme,hook_formula,first_line,length_s,permalink,views,reach,"
                  "likes,comments,shares,saves,follows,skip_rate,nonfollower_pct,avg_watch_s,"
                  "trial,test_id,variant,notes").split(",")
TODAY = dt.date(2026, 10, 15)


def run(*argv):
    buf = io.StringIO()
    grow.main(["--today", TODAY.isoformat(), *argv], out=buf)
    return buf.getvalue()


def run_json(*argv):
    return json.loads(run(*argv, "--json"))


def write_posts(d, posts):
    with open(os.path.join(d, "posts.csv"), "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=LEDGER_COLUMNS)
        w.writeheader()
        for i, p in enumerate(posts, 1):
            row = {c: "" for c in LEDGER_COLUMNS}
            row["id"] = f"P{i:04d}"
            row.update({k: str(v) for k, v in p.items()})
            w.writerow(row)


def write_followers(d, pairs):
    with open(os.path.join(d, "followers.csv"), "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(grow.FOLLOWER_COLUMNS)
        for day, n in pairs:
            w.writerow([day.isoformat(), n, "", "", ""])


def reels(n, every_days=2, **metrics):
    """n posts spread back from TODAY, every `every_days` days."""
    out = []
    for i in range(n):
        p = {"date": (TODAY - dt.timedelta(days=1 + i * every_days)).isoformat(),
             "format": "reel", "theme": "pricing", "hook_formula": "3"}
        p.update(metrics)
        out.append(p)
    return out


HEALTHY = dict(views=5000, reach=4000, follows=40, shares=60, skip_rate=35, nonfollower_pct=60)


class TempDir(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.mkdtemp(prefix="iggrow-")
        self._env = {k: os.environ.get(k) for k in ("IG_DATA_DIR", "IG_HOME")}
        os.environ["IG_DATA_DIR"] = self.d

    def tearDown(self):
        for k, v in self._env.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        shutil.rmtree(self.d, ignore_errors=True)


class TestDataDir(TempDir):
    def test_env_wins(self):
        self.assertEqual(grow.data_dir(), self.d)

    def test_active_account(self):
        os.environ.pop("IG_DATA_DIR")
        os.environ["IG_HOME"] = self.d
        os.makedirs(os.path.join(self.d, "accounts", "bakery"))
        with open(os.path.join(self.d, "active-account"), "w") as f:
            f.write("@bakery\n")
        self.assertEqual(grow.data_dir(), os.path.join(self.d, "accounts", "bakery"))

    def test_active_account_missing_folder_falls_back(self):
        os.environ.pop("IG_DATA_DIR")
        os.environ["IG_HOME"] = self.d
        with open(os.path.join(self.d, "active-account"), "w") as f:
            f.write("ghost")
        self.assertEqual(grow.data_dir(), self.d)


class TestCheckin(TempDir):
    def test_appends_and_week_math(self):
        write_followers(self.d, [(TODAY - dt.timedelta(days=7), 900)])
        r = run_json("checkin", "--followers", "960")
        self.assertEqual(r["week"]["net"], 60)
        self.assertAlmostEqual(r["week"]["rate_pct"], 60 / 900 * 100)
        self.assertEqual(len(grow.load_followers()), 2)

    def test_same_date_replaces(self):
        run("checkin", "--followers", "100")
        run("checkin", "--followers", "105")
        rows = grow.load_followers()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["followers"], 105)

    def test_month_and_weekly_series(self):
        pairs = [(TODAY - dt.timedelta(days=7 * k), 1000 - 50 * k) for k in range(5, 0, -1)]
        write_followers(self.d, pairs)
        r = run_json("checkin", "--followers", "1000")
        self.assertEqual(r["weekly"], [50, 50, 50, 50])
        self.assertEqual(r["month"]["net"], 1000 - (1000 - 50 * 5))  # baseline 35 days back
        out = run("checkin", "--followers", "1000")
        self.assertIn("Week", out)
        self.assertIn("projection, not a promise", out.lower())

    def test_accepts_k_suffix(self):
        r = run_json("checkin", "--followers", "1.2k")
        self.assertEqual(r["row"]["followers"], 1200)


class TestProjection(TempDir):
    def test_next_milestone(self):
        self.assertEqual(grow.next_milestone(999), 1000)
        self.assertEqual(grow.next_milestone(1000), 5000)
        self.assertEqual(grow.next_milestone(60000), 100000)

    def test_days_to_milestone(self):
        rows = [{"date": TODAY - dt.timedelta(days=28), "followers": 720},
                {"date": TODAY, "followers": 860}]  # +5 a day
        pr = grow.projection(rows, TODAY)
        self.assertEqual(pr["milestone"], 1000)
        self.assertAlmostEqual(pr["per_day"], 5.0)
        self.assertEqual(pr["days"], 28)
        self.assertEqual(pr["eta"], (TODAY + dt.timedelta(days=28)).isoformat())

    def test_no_date_when_shrinking(self):
        rows = [{"date": TODAY - dt.timedelta(days=14), "followers": 900},
                {"date": TODAY, "followers": 880}]
        pr = grow.projection(rows, TODAY)
        self.assertIsNone(pr["days"])

    def test_milestones_hit(self):
        write_followers(self.d, [(TODAY - dt.timedelta(days=60), 450),
                                 (TODAY - dt.timedelta(days=30), 980),
                                 (TODAY - dt.timedelta(days=20), 1010),
                                 (TODAY, 1500)])
        hit = run_json("milestones")
        self.assertEqual([m["milestone"] for m in hit], [100, 500, 1000])
        self.assertTrue(hit[0]["before_tracking"])
        self.assertEqual(hit[2]["date"], (TODAY - dt.timedelta(days=20)).isoformat())


class TestBottleneck(TempDir):
    def setUp(self):
        super().setUp()
        write_followers(self.d, [(TODAY - dt.timedelta(days=28), 1000), (TODAY, 1100)])

    def bottleneck(self):
        return run_json("report")["bottleneck"]["name"]

    def test_consistency(self):
        write_posts(self.d, reels(4, every_days=7, **HEALTHY))  # 1 a week
        self.assertEqual(self.bottleneck(), "consistency")

    def test_retention(self):
        write_posts(self.d, reels(16, **{**HEALTHY, "skip_rate": 64}))
        self.assertEqual(self.bottleneck(), "retention")

    def test_reach(self):
        write_posts(self.d, reels(16, **{**HEALTHY, "nonfollower_pct": 12}))
        self.assertEqual(self.bottleneck(), "reach")

    def test_reach_fallback_without_nonfollower(self):
        m = {**HEALTHY, "reach": 200}
        m.pop("nonfollower_pct")
        write_posts(self.d, reels(16, **m))
        self.assertEqual(self.bottleneck(), "reach")

    def test_conversion(self):
        write_posts(self.d, reels(16, **{**HEALTHY, "follows": 2}))  # 0.05%
        self.assertEqual(self.bottleneck(), "conversion")

    def test_healthy_names_weakest(self):
        write_posts(self.d, reels(16, **HEALTHY))
        b = run_json("report")["bottleneck"]
        self.assertTrue(b.get("healthy"))
        self.assertIn(b["name"], grow.BOTTLENECKS)

    def test_pipeline_order(self):
        # Both retention and conversion fail: retention is upstream, it wins.
        write_posts(self.d, reels(16, **{**HEALTHY, "skip_rate": 70, "follows": 1}))
        self.assertEqual(self.bottleneck(), "retention")

    def test_report_text(self):
        write_posts(self.d, reels(16, **{**HEALTHY, "follows": 2}))
        out = run("report")
        self.assertIn("GROWTH REPORT", out)
        self.assertIn("BOTTLENECK  CONVERSION", out)
        self.assertIn("====", out)
        self.assertNotIn("\u2014", out)


class TestPlan(TempDir):
    def setUp(self):
        super().setUp()
        write_followers(self.d, [(TODAY - dt.timedelta(days=28), 1000), (TODAY, 1100)])

    def plan(self, posts):
        write_posts(self.d, posts)
        return run_json("plan")

    def skills(self, p):
        return [a["skill"] for a in p["actions"]]

    def test_max_seven_and_calendar_last(self):
        p = self.plan(reels(16, **{**HEALTHY, "nonfollower_pct": 10}))
        self.assertLessEqual(len(p["actions"]), 7)
        self.assertEqual(p["actions"][-1]["skill"], "/ig-calendar")

    def test_reach_maps(self):
        with open(os.path.join(self.d, "trends.md"), "w") as f:
            f.write("# Trends\n\n- Silent tutorial with text overlay\n")
        p = self.plan(reels(16, **{**HEALTHY, "nonfollower_pct": 10}))
        s = self.skills(p)
        for want in ("/ig-trends", "/ig-test", "/ig-dm"):
            self.assertIn(want, s)
        self.assertTrue(any("Silent tutorial" in a["action"] for a in p["actions"]))

    def test_conversion_maps_to_profile(self):
        p = self.plan(reels(16, **{**HEALTHY, "follows": 2}))
        self.assertEqual(p["actions"][0]["skill"], "/ig-profile")

    def test_retention_maps(self):
        s = self.skills(self.plan(reels(16, **{**HEALTHY, "skip_rate": 70})))
        self.assertIn("/ig-reel", s)
        self.assertIn("/ig-test", s)

    def test_consistency_maps(self):
        s = self.skills(self.plan(reels(4, every_days=7, **HEALTHY)))
        self.assertIn("/ig-plan", s)
        self.assertIn("/ig-repurpose", s)

    def test_perf_due(self):
        posts = reels(16, **HEALTHY)
        posts.append({"date": (TODAY - dt.timedelta(days=1)).isoformat(), "format": "reel"})
        p = self.plan(posts)
        due = [a for a in p["actions"] if a["skill"] == "/ig-perf"]
        self.assertEqual(len(due), 1)
        self.assertIn("P0017", due[0]["action"])

    def test_top_formulas_named(self):
        posts = reels(8, **HEALTHY) + [
            {**p, "hook_formula": "7", "views": 20000} for p in reels(8, **HEALTHY)]
        p = self.plan(posts)
        reel = [a for a in p["actions"] if a["skill"] == "/ig-reel"]
        self.assertTrue(reel)
        self.assertIn("#7", reel[0]["action"])

    def test_engagement_round_dropped_when_done(self):
        days = [TODAY - dt.timedelta(days=i) for i in range(28)]
        with open(os.path.join(self.d, "engaged.md"), "w") as f:
            f.write("\n".join(f"{d.isoformat()} @someone - added a datum" for d in days))
        s = self.skills(self.plan(reels(16, **{**HEALTHY, "follows": 2})))
        self.assertNotIn("/ig-comment", s)


class TestOnboarding(TempDir):
    def test_empty_data(self):
        p = run_json("plan")
        self.assertEqual(p["mode"], "onboarding")
        s = [a["skill"] for a in p["actions"]]
        self.assertTrue(s[0].startswith("grow.py checkin"))
        for want in ("/ig-reel", "/ig-profile", "/ig-plan", "/ig-comment"):
            self.assertIn(want, s)
        self.assertLessEqual(len(s), 7)
        self.assertTrue(any("voice.md" in a["action"] for a in p["actions"]))
        self.assertTrue(any("9" in a["action"] for a in p["actions"]))

    def test_voice_present_skips_voice(self):
        with open(os.path.join(self.d, "voice.md"), "w") as f:
            f.write("voice")
        p = run_json("plan")
        self.assertFalse(any("voice.md" in a["action"] for a in p["actions"]))

    def test_empty_report_and_milestones(self):
        self.assertIn("ONBOARDING", run("report"))
        self.assertIn("No check-ins", run("milestones"))


if __name__ == "__main__":
    unittest.main()
