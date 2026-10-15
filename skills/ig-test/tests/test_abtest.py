"""
Tests for abtest.py. Run from the ig-test folder:

    python3 -m unittest discover -s tests

Uses the real ../ig-ledger/ledger.py when it exists, else the stand-in in
tests/_fake_ledger. Force one with IG_TEST_LEDGER=fake or IG_TEST_LEDGER=real.
Every test points IG_DATA_DIR at its own temp dir. Nothing touches
~/.claude/instagram.
"""

import contextlib
import csv
import importlib
import io
import json
import math
import os
import shutil
import sys
import tempfile
import unittest

TESTS = os.path.dirname(os.path.abspath(__file__))
SKILL = os.path.dirname(TESTS)
REAL = os.path.join(SKILL, "..", "ig-ledger")
FAKE = os.path.join(TESTS, "_fake_ledger")

# Guard: never let an import-time default reach the real data dir.
os.environ["IG_DATA_DIR"] = tempfile.mkdtemp(prefix="igtest-import-")

_choice = os.environ.get("IG_TEST_LEDGER") or (
    "real" if os.path.isfile(os.path.join(REAL, "ledger.py")) else "fake")
sys.path.insert(0, FAKE if _choice == "fake" else REAL)
sys.modules.pop("ledger", None)
ledger = importlib.import_module("ledger")        # abtest's `import ledger` reuses this
LEDGER_KIND = _choice

sys.path.insert(0, SKILL)
import abtest  # noqa: E402

COLUMNS = ("id,date,format,theme,hook_formula,first_line,length_s,permalink,views,reach,"
           "likes,comments,shares,saves,follows,skip_rate,nonfollower_pct,avg_watch_s,"
           "trial,test_id,variant,notes").split(",")


def run(*argv):
    buf = io.StringIO()
    abtest.main(list(argv), out=buf)
    return buf.getvalue()


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="igtest-")
        self._old = os.environ.get("IG_DATA_DIR")
        os.environ["IG_DATA_DIR"] = self.tmp
        self._dirs = abtest.HOOKSCORE_DIRS

    def tearDown(self):
        abtest.HOOKSCORE_DIRS = self._dirs
        os.environ["IG_DATA_DIR"] = self._old
        shutil.rmtree(self.tmp, ignore_errors=True)

    def rows(self):
        with open(os.path.join(self.tmp, "posts.csv"), newline="", encoding="utf-8") as f:
            return list(csv.DictReader(f))

    def new_test(self, a="I lost $4,000 on my first ad", b="Stop running ads before you read this"):
        return run("new", "--a", a, "--b", b, "--formula-a", "cost", "--formula-b", "warning",
                   "--theme", "ads", "--length", "28")


class TestLedgerWiring(unittest.TestCase):
    def test_using_expected_ledger(self):
        self.assertIs(abtest.ledger, ledger)
        print(f"\n[ig-test] ledger under test: {LEDGER_KIND}", file=sys.stderr)

    def test_columns_match_contract(self):
        self.assertEqual(list(ledger.COLUMNS), COLUMNS)


class TestNew(Base):
    def test_new_creates_two_rows(self):
        out = self.new_test()
        self.assertIn("NEW A/B TEST T001", out)
        rows = self.rows()
        self.assertEqual(len(rows), 2)
        a, b = rows
        self.assertEqual((a["test_id"], a["variant"], b["variant"]), ("T001", "A", "B"))
        for r in rows:
            self.assertEqual(r["format"], "reel")
            self.assertEqual(r["trial"], "yes")
            self.assertEqual(r["theme"], "ads")
            self.assertEqual(r["length_s"], "28")
        self.assertEqual(a["first_line"], "I lost $4,000 on my first ad")
        self.assertEqual(a["hook_formula"], "cost")
        self.assertEqual(b["hook_formula"], "warning")
        self.assertTrue(a["id"].startswith("P"))

    def test_checklist(self):
        out = self.new_test().lower()
        for phrase in ("trial reel", "same hour", "time of day", "same video",
                       "do not share", "24 hours", "professional account",
                       "nothing has been posted"):
            self.assertIn(phrase, out)

    def test_next_test_id_increments(self):
        self.new_test()
        out = self.new_test(a="Hook three", b="Hook four")
        self.assertIn("T002", out)
        self.assertEqual({r["test_id"] for r in self.rows()}, {"T001", "T002"})

    def test_same_hook_refused(self):
        with self.assertRaises(SystemExit), contextlib.redirect_stderr(io.StringIO()):
            run("new", "--a", "Same line", "--b", "same line")

    def test_hookscore_used_when_present(self):
        if abtest.load_hookscore() is None:
            self.skipTest("ig-reel/hookscore.py not installed here")
        out = self.new_test()
        self.assertIn("hookscore", out)
        self.assertIn("cannot pick between two decent hooks", out)

    def test_missing_hookscore_is_graceful(self):
        abtest.HOOKSCORE_DIRS = [os.path.join(self.tmp, "nope")]
        self.assertIsNone(abtest.load_hookscore())
        out = self.new_test()
        self.assertIn("not scored", out)
        self.assertEqual(len(self.rows()), 2)
        j = json.loads(run("new", "--a", "x one", "--b", "y two", "--json"))
        self.assertIsNone(j["scores"])

    def test_broken_hookscore_is_graceful(self):
        d = os.path.join(self.tmp, "broken")
        os.makedirs(d)
        with open(os.path.join(d, "hookscore.py"), "w") as f:
            f.write("raise RuntimeError('boom')\n")
        self.assertIsNone(abtest.load_hookscore([d]))


class TestRecord(Base):
    def test_record_updates_only_that_variant(self):
        self.new_test()
        out = run("record", "T001", "a", "--views", "1,200", "--shares", "14",
                  "--skip-rate", "38.5%", "--avg-watch", "9.2", "--likes", "1.1k")
        self.assertIn("Now record B", out)
        a, b = self.rows()
        self.assertEqual(a["views"], "1200")
        self.assertEqual(a["shares"], "14")
        self.assertEqual(float(a["skip_rate"]), 38.5)
        self.assertEqual(float(a["avg_watch_s"]), 9.2)
        self.assertEqual(a["likes"], "1100")
        self.assertEqual(b["views"], "")

    def test_small_skip_rate_not_scaled(self):
        # 0.5 means 0.5 percent. The real ledger would read a bare 0.5 as a
        # fraction and store 50. abtest must not let that happen.
        self.new_test()
        run("record", "T001", "A", "--views", "500", "--skip-rate", "0.5")
        self.assertEqual(float(self.rows()[0]["skip_rate"]), 0.5)

    def test_record_numeric_test_id(self):
        self.new_test()
        run("record", "1", "B", "--views", "800")
        self.assertEqual(self.rows()[1]["views"], "800")

    def test_record_unknown_test(self):
        self.new_test()
        with self.assertRaises(SystemExit), contextlib.redirect_stderr(io.StringIO()):
            run("record", "T009", "A", "--views", "10")

    def test_bad_skip_rate_rejected(self):
        self.new_test()
        with self.assertRaises(SystemExit), contextlib.redirect_stderr(io.StringIO()):
            run("record", "T001", "A", "--views", "10", "--skip-rate", "140")


class TestMath(unittest.TestCase):
    def test_two_prop_z_known_value(self):
        # 60/1000 vs 30/1000: pooled p = .045, se = sqrt(.045*.955*.002)
        z = abtest.two_prop_z(60, 1000, 30, 1000)
        expect = 0.03 / math.sqrt(0.045 * 0.955 * 0.002)
        self.assertAlmostEqual(z, expect, places=9)
        self.assertAlmostEqual(z, 3.2364, places=3)

    def test_two_prop_z_symmetry_and_zero(self):
        self.assertAlmostEqual(abtest.two_prop_z(30, 1000, 60, 1000),
                               -abtest.two_prop_z(60, 1000, 30, 1000))
        self.assertEqual(abtest.two_prop_z(50, 500, 50, 500), 0.0)
        self.assertEqual(abtest.two_prop_z(0, 500, 0, 500), 0.0)      # no variance
        self.assertEqual(abtest.two_prop_z(500, 500, 500, 500), 0.0)
        self.assertEqual(abtest.two_prop_z(1, 0, 1, 10), 0.0)

    def test_p_value(self):
        self.assertAlmostEqual(abtest.p_two_sided(1.96), 0.05, places=3)
        self.assertAlmostEqual(abtest.p_two_sided(0), 1.0)

    def test_count_z(self):
        self.assertAlmostEqual(abtest.count_z(1200, 800), 400 / math.sqrt(2000))
        self.assertEqual(abtest.count_z(0, 0), 0.0)

    def test_parsers(self):
        self.assertEqual(abtest.count("12,400"), 12400)
        self.assertEqual(abtest.count("1.2k"), 1200)
        self.assertEqual(abtest.percent("38.5%"), 38.5)
        self.assertEqual(abtest.norm_test_id("t3"), "T3")
        self.assertEqual(abtest.norm_test_id("3"), "T003")


class TestReport(Base):
    def record(self, v, **kw):
        argv = ["record", "T001", v]
        for k, val in kw.items():
            argv += ["--" + k.replace("_", "-"), str(val)]
        run(*argv)

    def report(self):
        return json.loads(run("report", "T001", "--json"))

    def test_waiting(self):
        self.new_test()
        self.record("A", views=900)
        res = self.report()
        self.assertEqual(res["status"], "waiting")
        self.assertIsNone(res["verdict"])
        self.assertIn("Waiting for numbers", run("report", "T001"))

    def test_skip_rate_is_primary_and_decides(self):
        self.new_test()
        # B has more shares, A holds far better. Skip rate decides.
        self.record("A", views=2000, shares=20, skip_rate=30)
        self.record("B", views=2000, shares=24, skip_rate=45)
        res = self.report()
        self.assertEqual(res["metrics"][0]["name"], "held past 3s")
        self.assertEqual(res["metrics"][0]["role"], "primary")
        self.assertEqual(res["verdict"], "WINNER A")
        self.assertEqual(res["decided_on"], "held past 3s")
        held_z = abtest.two_prop_z(1400, 2000, 1100, 2000)
        self.assertAlmostEqual(res["metrics"][0]["z"], held_z, places=6)

    def test_lower_skip_rate_wins_for_b(self):
        self.new_test()
        self.record("A", views=1500, skip_rate=50)
        self.record("B", views=1500, skip_rate=40)
        self.assertEqual(self.report()["verdict"], "WINNER B")

    def test_shares_primary_without_skip_rate(self):
        self.new_test()
        self.record("A", views=3000, shares=90)
        self.record("B", views=3000, shares=40, skip_rate=20)   # only one has skip
        res = self.report()
        self.assertEqual(res["metrics"][0]["name"], "shares per view")
        self.assertEqual(res["metrics"][0]["role"], "primary")
        self.assertEqual(res["verdict"], "WINNER A")

    def test_close_numbers_too_close(self):
        self.new_test()
        self.record("A", views=1000, shares=12, skip_rate=40)
        self.record("B", views=1050, shares=10, skip_rate=41)
        res = self.report()
        self.assertEqual(res["verdict"], "TOO CLOSE")
        self.assertIsNone(res["winner"])
        txt = run("report", "T001")
        self.assertIn("TOO CLOSE", txt)
        self.assertNotIn("won T001", " ".join(r["notes"] for r in self.rows()))

    def test_small_sample_too_close_even_if_huge_gap(self):
        self.new_test()
        self.record("A", views=250, shares=40, skip_rate=10)
        self.record("B", views=2500, shares=5, skip_rate=80)
        res = self.report()
        self.assertTrue(any(m["significant"] for m in res["metrics"]))
        self.assertEqual(res["verdict"], "TOO CLOSE")
        self.assertIn("300", " ".join(res["reasons"]))

    def test_winner_notes_written_and_idempotent(self):
        self.new_test()
        ledger.update_row(self.rows()[0]["id"], notes="shot on the balcony")
        self.record("A", views=2000, skip_rate=30)
        self.record("B", views=2000, skip_rate=45)
        txt = run("report", "T001")
        self.assertIn("WINNER A", txt)
        self.assertIn("Share A to your followers", txt)
        self.assertIn("learning", txt)
        run("report", "T001")
        a, b = self.rows()
        self.assertEqual(a["notes"], "shot on the balcony; won T001")
        self.assertEqual(b["notes"], "lost T001")

    def test_views_tiebreak_only(self):
        self.new_test()
        self.record("A", views=5000)
        self.record("B", views=1000)
        res = self.report()
        self.assertEqual(res["metrics"][0]["name"], "views")
        self.assertEqual(res["verdict"], "WINNER A")

    def test_secondary_decides_when_primary_noise(self):
        self.new_test()
        self.record("A", views=3000, shares=90, skip_rate=40)
        self.record("B", views=3000, shares=40, skip_rate=40.5)
        res = self.report()
        self.assertFalse(res["metrics"][0]["significant"])
        self.assertEqual(res["decided_on"], "shares per view")
        self.assertIn("weaker evidence", " ".join(res["reasons"]))

    def test_report_unknown_test(self):
        with self.assertRaises(SystemExit), contextlib.redirect_stderr(io.StringIO()):
            run("report", "T404")


class TestList(Base):
    def test_list_statuses(self):
        self.assertIn("none yet", run("list"))
        self.new_test()                              # T001 waiting
        self.new_test(a="Hook c", b="Hook d")        # T002 ready
        self.new_test(a="Hook e", b="Hook f")        # T003 decided
        for v in "AB":
            run("record", "T002", v, "--views", "600")
        run("record", "T003", "A", "--views", "2000", "--skip-rate", "30")
        run("record", "T003", "B", "--views", "2000", "--skip-rate", "45")
        run("report", "T003")
        items = {i["test_id"]: i for i in json.loads(run("list", "--json"))}
        self.assertEqual(items["T001"]["status"], "waiting for numbers")
        self.assertEqual(items["T002"]["status"], "ready")
        self.assertEqual(items["T003"]["status"], "decided")
        self.assertEqual(items["T003"]["winner"], "A")
        txt = run("list")
        self.assertIn("T003", txt)
        self.assertIn("A won", txt)


class TestAccountResolution(unittest.TestCase):
    """With no IG_DATA_DIR, tests land in the active account's posts.csv."""

    def setUp(self):
        self.home = tempfile.mkdtemp(prefix="igtest-home-")
        self._env = {k: os.environ.get(k) for k in ("IG_HOME", "IG_DATA_DIR")}
        os.environ["IG_HOME"] = self.home
        os.environ.pop("IG_DATA_DIR", None)
        for h in ("acme", "client"):
            os.makedirs(os.path.join(self.home, "accounts", h))

    def tearDown(self):
        for k, v in self._env.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        shutil.rmtree(self.home, ignore_errors=True)

    def use(self, h):
        with open(os.path.join(self.home, "active-account"), "w") as f:
            f.write(h + "\n")

    def test_ledger_follows_active_account(self):
        self.use("@ACME")
        self.assertEqual(ledger.data_dir(), os.path.join(self.home, "accounts", "acme"))
        run("new", "--a", "I lost $4,000 on my first ad", "--b", "Stop running ads before you read this")
        self.assertTrue(os.path.isfile(os.path.join(self.home, "accounts", "acme", "posts.csv")))
        self.assertIn("T001", run("list"))
        self.use("client")
        self.assertEqual(json.loads(run("list", "--json")), [])
        self.assertFalse(os.path.exists(os.path.join(self.home, "posts.csv")))

    def test_no_active_account_uses_home(self):
        self.assertEqual(ledger.data_dir(), self.home)


if __name__ == "__main__":
    unittest.main()
