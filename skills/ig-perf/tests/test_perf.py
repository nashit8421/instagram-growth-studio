"""
Tests for perf.py. Run from the ig-perf folder:

    python3 -m unittest discover -s tests

Uses the real ig-ledger (sibling folder first, then the installed pack). Every
test points IG_DATA_DIR at its own temp dir. Nothing touches
~/IGStudio or ~/.claude/skills.
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
os.environ["IG_DATA_DIR"] = tempfile.mkdtemp(prefix="igperf-import-")
os.environ["IG_HOME"] = tempfile.mkdtemp(prefix="igperf-home-")

sys.path.insert(0, SKILL)
import perf  # noqa: E402

ledger = perf.get_ledger()

SCRIPT = """$18,000 is what one missing clause cost me.
I signed a client contract without a kill fee.
They cancelled three weeks in and paid nothing for the work already done.
So now every contract I send has one line in it.
If you cancel after kickoff, you pay fifty percent.
That single clause has paid me back four times this year.
Put the kill fee in before you send the next one, or it costs you $18,000 too."""


def run(*argv):
    buf, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stderr(err):
        code = perf.main(list(argv), out=buf)
    return code, buf.getvalue(), err.getvalue()


def m_(**kw):
    base = {k: None for k in perf.METRICS}
    base.update(length_s=None, hours=48.0)
    base.update(kw)
    return base


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="igperf-")
        os.environ["IG_DATA_DIR"] = self.tmp
        self.hooks = perf.load_hooks()

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def add(self, date="2026-10-12", hook="3", length="30", trial=False, fmt="reel", **kw):
        return ledger.add_row(format=fmt, date=date, hook_formula=hook, length_s=length,
                              first_line=kw.pop("first_line", "a test line"),
                              trial=trial, **kw)

    def check(self, pid, hours, at, **metrics):
        return perf.record_check(pid, metrics, hours=hours, at=perf.parse_time(at))

    def diag(self, m, vel=None, row=None):
        r = perf.rates(m)
        found, missing, noise = perf.diagnose(m, r, vel or {"trend": "slowing"}, [], row,
                                              self.hooks)
        return [f["rule"] for f in found], found, missing, noise


class TestDataDir(unittest.TestCase):
    def test_active_account_rule(self):
        home = tempfile.mkdtemp(prefix="igperf-acct-")
        saved = os.environ.pop("IG_DATA_DIR")
        old_home = os.environ.get("IG_HOME")
        try:
            os.environ["IG_HOME"] = home
            self.assertEqual(perf.data_dir(), home)
            with open(os.path.join(home, "active-account"), "w") as f:
                f.write("@studio.k\n")
            self.assertEqual(perf.data_dir(), home)        # folder missing: fall back
            os.makedirs(os.path.join(home, "accounts", "studio.k"))
            self.assertEqual(perf.data_dir(), os.path.join(home, "accounts", "studio.k"))
            os.environ["IG_DATA_DIR"] = "/x/y"
            self.assertEqual(perf.data_dir(), "/x/y")
        finally:
            os.environ["IG_DATA_DIR"] = saved
            os.environ["IG_HOME"] = old_home
            shutil.rmtree(home, ignore_errors=True)


class TestCheck(Base):
    def test_appends_snapshot_and_updates_ledger(self):
        pid = self.add()
        snap, note = self.check(pid, 24, "2026-10-13 12:00", views=1200, reach=900,
                                shares=4, skip_rate=34.0, nonfollower_pct=55.0,
                                avg_watch_s=11.5)
        self.assertIn("ledger updated", note)
        with open(os.path.join(self.tmp, "snapshots.csv")) as f:
            rows = list(csv.DictReader(f))
        self.assertEqual(list(rows[0].keys()), perf.SNAP_COLUMNS)
        self.assertEqual(rows[0]["views"], "1200")
        self.assertEqual(rows[0]["hours_since_post"], "24")
        row = ledger.get_row(pid)
        self.assertEqual(row["views"], "1200")
        self.assertEqual(row["skip_rate"], "34")          # not scaled to 3400
        self.assertEqual(row["nonfollower_pct"], "55")
        self.assertEqual(row["avg_watch_s"], "11.5")
        self.assertEqual(row["likes"], "")                # untouched, not zero

    def test_cli_fraction_percent_scaled(self):
        pid = self.add()
        code, out, err = run("check", pid, "--views", "1.2k", "--skip-rate", "0.34",
                             "--hours", "5", "--at", "2026-10-12 17:00", "--quiet")
        self.assertEqual(code, 0, err)
        self.assertEqual(ledger.get_row(pid)["skip_rate"], "34")
        self.assertEqual(ledger.get_row(pid)["views"], "1200")

    def test_backfill_does_not_overwrite_newer_totals(self):
        pid = self.add()
        self.check(pid, 72, "2026-10-15 12:00", views=5000)
        snap, note = self.check(pid, 24, "2026-10-13 12:00", views=2000)
        self.assertIn("keeps the newer", note)
        self.assertEqual(ledger.get_row(pid)["views"], "5000")
        self.assertEqual(len(perf.load_snapshots(pid)), 2)

    def test_age_from_at_and_earlier_check(self):
        pid = self.add()
        self.check(pid, 2, "2026-10-12 14:00", views=300)       # posted 12:00
        snap, _ = perf.record_check(pid, {"views": 900}, at=perf.parse_time("2026-10-13 18:00"))
        self.assertEqual(snap["hours_since_post"], "30")

    def test_age_from_posted_at_cli(self):
        pid = self.add()
        code, out, err = run("check", pid, "--views", "100", "--at", "2026-10-12 10:30",
                             "--posted-at", "2026-10-12 09:00", "--quiet")
        self.assertEqual(code, 0, err)
        self.assertEqual(perf.load_snapshots(pid)[0]["hours_since_post"], "1.5")

    def test_unknown_id_and_no_numbers(self):
        with self.assertRaises(KeyError):
            perf.record_check("P0099", {"views": 1}, hours=1)
        pid = self.add()
        with self.assertRaises(ValueError):
            perf.record_check(pid, {}, hours=1)
        code, _, err = run("check", "P0099", "--views", "5", "--hours", "1")
        self.assertEqual(code, 2)
        self.assertIn("no post with id", err)


class TestVelocity(Base):
    def pts(self, *pairs):
        return [{"hours": h, "views": v} for h, v in pairs]

    def test_one_check(self):
        v = perf.velocity(self.pts((2, 400)))
        self.assertEqual(v["trend"], "one check")
        self.assertAlmostEqual(v["segments"][0]["per_hour"], 200)

    def test_slowing(self):
        v = perf.velocity(self.pts((1, 500), (24, 3000), (72, 4500)))
        self.assertEqual(v["trend"], "slowing")
        self.assertAlmostEqual(v["segments"][1]["per_hour"], 2500 / 23)

    def test_accelerating(self):
        v = perf.velocity(self.pts((24, 1000), (48, 1500), (72, 4000)))
        self.assertEqual(v["trend"], "accelerating")

    def test_stalled(self):
        v = perf.velocity(self.pts((24, 4000), (72, 6000), (168, 6050)))
        self.assertEqual(v["trend"], "stalled")

    def test_no_views(self):
        self.assertEqual(perf.velocity([{"hours": 3, "views": None}])["trend"], "none")


class TestDiagnosis(Base):
    def test_hook_rule_cites_formula_and_two_others(self):
        rules, found, _, _ = self.diag(m_(skip_rate=52, avg_watch_s=5, length_s=30),
                                       row={"hook_formula": "3"})
        self.assertEqual(rules[0], "hook")
        self.assertIn("Nobody Tells You", found[0]["detail"])
        alts = found[0]["alternatives"]
        self.assertEqual(len(alts), 2)
        self.assertNotIn("3", [a["id"] for a in alts])
        self.assertNotIn("middle", rules)      # middle needs an OK skip rate

    def test_hook_suggestions_prefer_account_winners(self):
        rows = []
        for fid, views in (("7", 3000), ("7", 2800), ("3", 500), ("3", 600), ("9", 900)):
            rows.append({"id": "Px", "views": str(views), "hook_formula": fid, "trial": ""})
        alts = perf.suggest_formulas("3", rows, self.hooks)
        self.assertEqual(alts[0][0], "7")
        self.assertIn("your median", alts[0][2])

    def test_middle_rule(self):
        rules, found, _, _ = self.diag(m_(skip_rate=30, avg_watch_s=8, length_s=30))
        self.assertEqual(rules[0], "middle")
        self.assertIn("beats.py", found[0]["detail"])

    def test_sends_rule(self):
        rules, *_ = self.diag(m_(skip_rate=30, avg_watch_s=18, length_s=30,
                                 shares=3, reach=2000))
        self.assertEqual(rules, ["sends"])

    def test_sends_ok(self):
        rules, *_ = self.diag(m_(skip_rate=30, avg_watch_s=18, length_s=30,
                                 shares=30, reach=2000))
        self.assertEqual(rules, [])

    def test_profile_rule(self):
        rules, found, _, _ = self.diag(m_(skip_rate=30, avg_watch_s=18, length_s=30,
                                          shares=40, reach=4000, follows=3,
                                          nonfollower_pct=70))
        self.assertEqual(rules, ["profile"])
        self.assertIn("/ig-profile", found[0]["detail"])

    def test_travel_rule_only_after_24h(self):
        m = m_(skip_rate=30, avg_watch_s=18, length_s=30, shares=40, reach=4000,
               follows=20, nonfollower_pct=18, hours=30)
        self.assertEqual(self.diag(m)[0], ["travel"])
        m["hours"] = 6
        self.assertEqual(self.diag(m)[0], [])

    def test_stalled_with_good_metrics(self):
        m = m_(skip_rate=30, avg_watch_s=18, length_s=30, shares=40, reach=4000,
               follows=20, nonfollower_pct=60, hours=120)
        rules, found, _, _ = self.diag(m, vel={"trend": "stalled"})
        self.assertEqual(rules, ["stalled"])
        self.assertIn("carousel", found[0]["detail"])
        m["hours"] = 48
        self.assertEqual(self.diag(m, vel={"trend": "stalled"})[0], [])

    def test_priority_order(self):
        m = m_(skip_rate=60, avg_watch_s=18, length_s=30, shares=1, reach=4000,
               follows=1, nonfollower_pct=80)
        rules = self.diag(m)[0]
        self.assertEqual(rules[0], "hook")
        self.assertIn("profile", rules)

    def test_missing_metrics_listed_not_guessed(self):
        rules, _, missing, noise = self.diag(m_(views=300))
        self.assertEqual(rules, [])
        self.assertTrue(any("skip rate" in x for x in missing))
        self.assertTrue(noise)

    def test_noise_warning_on_small_reach(self):
        _, _, _, noise = self.diag(m_(reach=400, shares=1))
        self.assertIn("0.25 points", noise)


class TestStatus(Base):
    def seed_peers(self):
        for i, (v24, v72) in enumerate(((1000, 1800), (1200, 2000), (800, 1500))):
            pid = self.add(date="2026-10-0%d" % (i + 1))
            self.check(pid, 24, "2026-10-0%d 12:00" % (i + 2), views=v24)
            self.check(pid, 72, "2026-10-0%d 12:00" % (i + 4), views=v72)

    def test_same_age_comparison(self):
        self.seed_peers()
        pid = self.add(date="2026-10-12")
        self.check(pid, 24, "2026-10-13 12:00", views=3000)
        st = perf.build_status(pid)
        self.assertEqual(st["compare"]["basis"], "same age")
        self.assertEqual(st["compare"]["n"], 3)
        self.assertAlmostEqual(st["compare"]["multiple"], 3.0)

    def test_interpolates_between_peer_checks(self):
        self.seed_peers()
        pid = self.add(date="2026-10-12")
        self.check(pid, 48, "2026-10-14 12:00", views=1600)
        st = perf.build_status(pid)
        self.assertEqual(st["compare"]["basis"], "same age")
        self.assertAlmostEqual(st["compare"]["baseline"], 1400)   # median of 1400,1600,1150

    def test_falls_back_to_ledger_median(self):
        for v in (1000, 2000, 3000):
            p = self.add()
            ledger.update_row(p, views=str(v))
        pid = self.add()
        self.check(pid, 24, "2026-10-13 12:00", views=4000)
        st = perf.build_status(pid)
        self.assertEqual(st["compare"]["basis"], "ledger median")
        self.assertAlmostEqual(st["compare"]["multiple"], 2.0)
        self.assertIn("young post", st["compare"]["note"])

    def test_trials_kept_apart(self):
        for v in (100, 100, 100):
            p = self.add(trial=True)
            ledger.update_row(p, views=str(v))
        p = self.add()
        ledger.update_row(p, views="1000")
        pid = self.add()
        self.check(pid, 24, "2026-10-13 12:00", views=2000)
        self.assertEqual(perf.build_status(pid)["compare"]["n"], 1)

    def test_minimal_post_renders(self):
        pid = self.add(hook="", length="")
        st = perf.build_status(pid)                       # no snapshots at all
        self.assertEqual(st["timeline"], [])
        buf = io.StringIO()
        perf.render_status(st, buf)
        self.assertIn("no checks yet", buf.getvalue())
        self.check(pid, 3, "2026-10-12 15:00", views=150)
        code, out, err = run("status", pid)
        self.assertEqual(code, 0, err)
        self.assertIn("not checked, no data", out)
        self.assertIn("IMPROVE", out)
        self.assertEqual(len(perf.build_status(pid)["improve_now"]), 3)
        self.assertEqual(len(perf.build_status(pid)["improve_next"]), 3)

    def test_status_json_and_checkpoints(self):
        pid = self.add()
        self.check(pid, 1, "2026-10-12 13:00", views=200, reach=150)
        self.check(pid, 26, "2026-10-13 14:00", views=2600, reach=2000, shares=4,
                   skip_rate=50.0, avg_watch_s=7, nonfollower_pct=40.0, follows=3)
        code, out, err = run("status", pid, "--json")
        self.assertEqual(code, 0, err)
        st = json.loads(out)
        self.assertEqual([t["checkpoint"] for t in st["timeline"]], ["1h", "24h"])
        self.assertEqual(st["diagnosis"][0]["rule"], "hook")
        self.assertEqual(len(st["improve_now"]), 3)
        self.assertEqual(len(st["improve_next"]), 3)

    def test_script_maps_drop_to_beat(self):
        pid = self.add(length="25")
        self.check(pid, 24, "2026-10-13 12:00", views=2000, reach=1500, skip_rate=30.0,
                   avg_watch_s=8.0)
        path = os.path.join(self.tmp, "script.txt")
        with open(path, "w") as f:
            f.write(SCRIPT)
        with open(path) as f:
            st = perf.build_status(pid, f.read())
        if perf.load_beats() is None:
            self.skipTest("ig-reel/beats.py not installed")
        self.assertEqual(st["diagnosis"][0]["rule"], "middle")
        b = st["script"]["drop_beat"]
        self.assertIsNotNone(b)
        self.assertGreater(b["n"], 1)
        code, out, _ = run("status", pid, "--script", path)
        self.assertIn("ON THE SCRIPT", out)
        self.assertIn("Average viewer leaves", out)


class TestDue(Base):
    def test_due_list(self):
        a = self.add(date="2026-10-14")              # no checks, ~25h old: 24h due
        b = self.add(date="2026-10-14")
        self.check(b, 24, "2026-10-15 12:00", views=500)   # 24h covered
        c = self.add(date="2026-10-01")              # too old
        d = self.add(date="2026-10-14", fmt="story")
        e = self.add(date="2026-10-10")              # ~121h, 72h window passed
        items = perf.due_list(perf.parse_time("2026-10-15 13:00"))
        ids = {i["post_id"]: i for i in items}
        self.assertIn(a, ids)
        self.assertEqual(ids[a]["checkpoint"], "24h")
        self.assertEqual(ids[a]["posted_at_how"], "assumed noon")
        self.assertNotIn(b, ids)
        self.assertNotIn(c, ids)
        self.assertNotIn(d, ids)
        self.assertTrue(ids[e]["late"])
        self.assertEqual(ids[e]["checkpoint"], "72h")

    def test_one_hour_due_and_not_before(self):
        a = self.add(date="2026-10-15")
        self.check(a, 0.2, "2026-10-15 12:12", views=20)   # pins post time to 12:00
        self.assertEqual(perf.due_list(perf.parse_time("2026-10-15 12:20")), [])
        items = perf.due_list(perf.parse_time("2026-10-15 13:00"))
        self.assertEqual(items[0]["checkpoint"], "1h")

    def test_cli(self):
        self.add(date="2026-10-14")
        code, out, _ = run("due", "--now", "2026-10-15 13:00")
        self.assertEqual(code, 0)
        self.assertIn("CHECKS DUE  ·  1 post", out)


class TestRetention(Base):
    def test_parse_points(self):
        self.assertEqual(perf.parse_points("3:61, 0:100,1:82"), [(0, 100), (1, 82), (3, 61)])
        for bad in ("0:100", "0-100,3:50", "0:100,3:150"):
            with self.assertRaises(ValueError):
                perf.parse_points(bad)

    def test_steepest_drop_and_end_ignored(self):
        a = perf.analyse_retention(perf.parse_points("0:100,1:70,3:61,10:50,28:40,30:5"),
                                   length=30)
        self.assertEqual(a["steepest"][0]["from_s"], 0)
        self.assertNotIn(28, [s["from_s"] for s in a["steepest"]])
        self.assertEqual(a["held_at_3s"], 61)

    def test_maps_onto_beats(self):
        if perf.load_beats() is None:
            self.skipTest("ig-reel/beats.py not installed")
        pts = perf.parse_points("0:100,3:85,6:80,9:45,14:40,20:35")
        a = perf.analyse_retention(pts, length=None, script_text=SCRIPT)
        self.assertTrue(a["mapped_to_script"])
        w = a["steepest"][0]
        self.assertEqual((w["from_s"], w["to_s"]), (6, 9))
        self.assertTrue(w["beats"])
        self.assertTrue(all(b["n"] >= 2 for b in w["beats"]))

    def test_cli_saves_and_status_shows(self):
        pid = self.add()
        path = os.path.join(self.tmp, "s.txt")
        with open(path, "w") as f:
            f.write(SCRIPT)
        code, out, err = run("retention", pid, "--points", "0:100,1:82,3:61,10:40,20:22",
                             "--script", path)
        self.assertEqual(code, 0, err)
        self.assertIn("Steepest drop", out)
        self.assertEqual(len(perf.load_retention(pid)), 1)
        self.assertIsNotNone(perf.build_status(pid)["retention"])


if __name__ == "__main__":
    unittest.main()
