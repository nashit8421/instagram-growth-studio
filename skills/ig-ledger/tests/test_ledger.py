"""Tests for ledger.py and audit.py. Stdlib only.

Run from the skill folder:  python3 -m unittest discover -s tests
Every test points IG_DATA_DIR at a fresh temp dir. The real
~/IGStudio is never touched.
"""

import contextlib
import io
import json
import os
import shutil
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
SKILL = os.path.dirname(HERE)
FIXTURE = os.path.join(HERE, "fixtures", "meta_export.csv")
sys.path.insert(0, SKILL)

import ledger  # noqa: E402
import audit  # noqa: E402


class TempDataDir(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="ig-ledger-test-")
        self._old = os.environ.get("IG_DATA_DIR")
        os.environ["IG_DATA_DIR"] = self.tmp

    def tearDown(self):
        if self._old is None:
            os.environ.pop("IG_DATA_DIR", None)
        else:
            os.environ["IG_DATA_DIR"] = self._old
        shutil.rmtree(self.tmp, ignore_errors=True)

    def run_cli(self, mod, *argv):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = mod.main(list(argv))
        return code, out.getvalue(), err.getvalue()

    def write_csv(self, name, text, encoding="utf-8"):
        path = os.path.join(self.tmp, name)
        with open(path, "w", encoding=encoding, newline="") as f:
            f.write(text)
        return path


class TestStorage(TempDataDir):
    def test_data_dir_follows_env(self):
        self.assertEqual(ledger.data_dir(), self.tmp)
        self.assertEqual(ledger.ledger_path(), os.path.join(self.tmp, "posts.csv"))

    def test_empty_ledger(self):
        self.assertEqual(ledger.load_rows(), [])

    def test_header_and_column_order(self):
        ledger.add_row(format="reel", date="2026-09-01")
        with open(ledger.ledger_path(), encoding="utf-8") as f:
            header = f.readline().strip()
        self.assertEqual(header, ",".join(ledger.COLUMNS))
        self.assertEqual(ledger.COLUMNS[0], "id")
        self.assertEqual(ledger.COLUMNS[-1], "notes")
        self.assertEqual(len(ledger.COLUMNS), 22)

    def test_save_is_atomic_no_temp_left(self):
        ledger.add_row(format="reel")
        ledger.add_row(format="photo")
        leftovers = [f for f in os.listdir(self.tmp) if f != "posts.csv"]
        self.assertEqual(leftovers, [])


class TestAdd(TempDataDir):
    def test_ids_increment(self):
        self.assertEqual(ledger.add_row(format="reel"), "P0001")
        self.assertEqual(ledger.add_row(format="carousel"), "P0002")
        self.assertEqual(ledger.add_row(format="story"), "P0003")

    def test_default_date_today(self):
        import datetime
        pid = ledger.add_row(format="reel")
        self.assertEqual(ledger.get_row(pid)["date"], datetime.date.today().isoformat())

    def test_bad_format_rejected(self):
        with self.assertRaises(ValueError):
            ledger.add_row(format="tiktok")
        with self.assertRaises(ValueError):
            ledger.add_row(theme="no format")

    def test_cli_add_prints_only_id(self):
        code, out, _ = self.run_cli(
            ledger, "add", "--format", "reel", "--date", "2026-09-02", "--theme", "pricing",
            "--hook-formula", "3", "--first-line", "Nobody tells you  this",
            "--length", "27", "--trial", "--test-id", "t001", "--variant", "a",
            "--notes", "first one")
        self.assertEqual(code, 0)
        self.assertEqual(out, "P0001\n")
        r = ledger.get_row("P0001")
        self.assertEqual(r["trial"], "yes")
        self.assertEqual(r["test_id"], "T001")
        self.assertEqual(r["variant"], "A")
        self.assertEqual(r["first_line"], "Nobody tells you this")
        self.assertEqual(r["length_s"], "27")
        self.assertEqual(r["hook_formula"], "3")

    def test_unicode_and_commas_survive(self):
        pid = ledger.add_row(format="reel", first_line='I said "no", then — café ✨')
        self.assertEqual(ledger.get_row(pid)["first_line"], 'I said "no", then — café ✨')


class TestUpdate(TempDataDir):
    def test_update_numbers(self):
        pid = ledger.add_row(format="reel")
        r = ledger.update_row(pid, views="12,400", reach=9870, shares="88",
                              skip_rate="31.2%", nonfollower_pct=0.62, avg_watch_s="8.5")
        self.assertEqual(r["views"], "12400")
        self.assertEqual(r["reach"], "9870")
        self.assertEqual(r["skip_rate"], "31.2")
        self.assertEqual(r["nonfollower_pct"], "62")  # fraction scaled to 0-100
        self.assertEqual(r["avg_watch_s"], "8.5")
        self.assertEqual(ledger.load_rows()[0]["views"], "12400")

    def test_none_leaves_field_alone(self):
        pid = ledger.add_row(format="reel", theme="pricing")
        ledger.update_row(pid, views=100, theme=None)
        self.assertEqual(ledger.get_row(pid)["theme"], "pricing")

    def test_unknown_id(self):
        with self.assertRaises(KeyError):
            ledger.update_row("P0099", views=1)
        code, _, err = self.run_cli(ledger, "update", "P0099", "--views", "1")
        self.assertEqual(code, 2)
        self.assertIn("P0099", err)

    def test_unknown_field(self):
        pid = ledger.add_row(format="reel")
        with self.assertRaises(ValueError):
            ledger.update_row(pid, plays=10)

    def test_bad_number(self):
        pid = ledger.add_row(format="reel")
        with self.assertRaises(ValueError):
            ledger.update_row(pid, views="lots")
        with self.assertRaises(ValueError):
            ledger.update_row(pid, skip_rate="140")

    def test_cli_update_prints_row(self):
        ledger.add_row(format="reel")
        code, out, _ = self.run_cli(ledger, "update", "p0001", "--views", "5,000",
                                    "--skip-rate", "40", "--nonfollower-pct", "55",
                                    "--avg-watch", "7", "--permalink", "https://x/reel/1/")
        self.assertEqual(code, 0)
        self.assertIn("views", out)
        self.assertIn("5000", out)
        r = ledger.get_row("P0001")
        self.assertEqual((r["skip_rate"], r["nonfollower_pct"], r["avg_watch_s"]),
                         ("40", "55", "7"))


class TestList(TempDataDir):
    def test_list_filters(self):
        for f in ("reel", "carousel", "reel", "reel"):
            ledger.add_row(format=f)
        code, out, _ = self.run_cli(ledger, "list", "--json", "--format", "reel", "--last", "2")
        self.assertEqual(code, 0)
        rows = json.loads(out)
        self.assertEqual([r["id"] for r in rows], ["P0003", "P0004"])
        self.assertEqual(list(rows[0].keys()), ledger.COLUMNS)

    def test_list_text(self):
        ledger.add_row(format="reel", first_line="hello there")
        code, out, _ = self.run_cli(ledger, "list")
        self.assertEqual(code, 0)
        self.assertIn("P0001", out)
        self.assertIn("hello there", out)
        self.assertIn("====", out)


class TestImport(TempDataDir):
    def test_fixture_permalink_and_prefix_match(self):
        # matched by permalink
        a = ledger.add_row(format="reel", date="2026-09-18", hook_formula="6",
                           permalink="https://www.instagram.com/reel/DBHkW2nQeZs")
        # matched by same date + first line prefix (no permalink logged)
        b = ledger.add_row(format="reel", date="2026-09-05", hook_formula="1",
                           first_line="i spent $2,000 on a RING LIGHT so you")
        # same first line, wrong date: must NOT match
        c = ledger.add_row(format="reel", date="2026-08-01",
                           first_line="Stop sending your portfolio as a PDF.")
        s = ledger.import_file(FIXTURE)
        self.assertEqual((s["matched"], s["created"], s["skipped"]), (2, 6, 1))
        ra, rb, rc = ledger.get_row(a), ledger.get_row(b), ledger.get_row(c)
        self.assertEqual(ra["views"], "102300")      # thousands separator
        self.assertEqual(ra["saves"], "1975")
        self.assertEqual(ra["skip_rate"], "19.4")
        self.assertEqual(ra["hook_formula"], "6")    # kept what we logged
        self.assertEqual(rb["views"], "48900")
        self.assertEqual(rb["permalink"], "https://www.instagram.com/reel/DA4mTr8sWqP/")
        self.assertEqual(rc["views"], "")
        rows = ledger.load_rows()
        self.assertEqual(len(rows), 9)
        new = [r for r in rows if r["notes"] == "imported"]
        self.assertEqual(len(new), 6)
        first = next(r for r in new if r["date"] == "2026-09-02")
        self.assertEqual(first["format"], "reel")
        self.assertEqual(first["first_line"],
                         "Nobody tells you your first 30 reels are practice. "
                         "Here is what changed at reel 31.")
        self.assertEqual(first["length_s"], "27")
        formats = sorted(r["format"] for r in new)
        self.assertEqual(formats, ["carousel", "photo", "reel", "reel", "reel", "story"])

    def test_bom_header_is_read(self):
        with open(FIXTURE, "rb") as f:
            self.assertTrue(f.read(3) == b"\xef\xbb\xbf")
        records, mapped = ledger.read_export(FIXTURE)
        self.assertIn("permalink", mapped)
        self.assertTrue(all("permalink" in r for r in records))

    def test_reimport_is_idempotent(self):
        ledger.import_file(FIXTURE)
        s = ledger.import_file(FIXTURE)
        self.assertEqual((s["matched"], s["created"]), (8, 0))
        self.assertEqual(len(ledger.load_rows()), 8)

    def test_dry_run_writes_nothing(self):
        code, out, _ = self.run_cli(ledger, "import", FIXTURE, "--dry-run")
        self.assertEqual(code, 0)
        self.assertIn("matched 0, created 8, skipped 1", out)
        self.assertEqual(ledger.load_rows(), [])
        self.assertFalse(os.path.exists(ledger.ledger_path()))

    def test_alias_headers_and_formats(self):
        text = ("﻿Date,Caption,Type,Plays,Accounts reached,LIKES,Sends,Saved,"
                "New follows,Typical skip rate,Non-follower reach,Some new column\n"
                '2026-07-03,"How I quote a brand job",IG Reel,"1,234",900,50,7,9,3,'
                '0.42,61%,whatever\n'
                '07/04/2026 09:00,"Three fonts I keep",IG carousel,"2.5K",2000,80,4,30,2,,,x\n')
        path = self.write_csv("alias.csv", text)
        s = ledger.import_file(path)
        self.assertEqual((s["matched"], s["created"], s["skipped"]), (0, 2, 0))
        r1, r2 = ledger.load_rows()
        self.assertEqual((r1["date"], r1["format"], r1["views"], r1["reach"]),
                         ("2026-07-03", "reel", "1234", "900"))
        self.assertEqual((r1["shares"], r1["saves"], r1["follows"]), ("7", "9", "3"))
        self.assertEqual(r1["skip_rate"], "42")
        self.assertEqual(r1["nonfollower_pct"], "61")
        self.assertEqual((r2["date"], r2["format"], r2["views"]), ("2026-07-04", "carousel", "2500"))

    def test_prefix_match_rules(self):
        self.assertTrue(ledger.prefix_match("Nobody tells you", "nobody   TELLS you your first 30"))
        self.assertTrue(ledger.prefix_match("x" * 60, "x" * 45 + "different tail"))
        self.assertFalse(ledger.prefix_match("Nobody tells you", "Everybody tells you"))
        self.assertFalse(ledger.prefix_match("", "anything"))

    def test_import_does_not_blank_existing_numbers(self):
        pid = ledger.add_row(format="reel", date="2026-09-08",
                             permalink="https://www.instagram.com/p/DA7bZc1oHkY/")
        ledger.update_row(pid, skip_rate=12, nonfollower_pct=40)
        ledger.import_file(FIXTURE)
        r = ledger.get_row(pid)
        self.assertEqual(r["skip_rate"], "12")      # export cell was empty
        self.assertEqual(r["nonfollower_pct"], "40")
        self.assertEqual(r["views"], "6210")

    def test_semicolon_export(self):
        text = 'Permalink;Publish time;Views;Reach\nhttps://i/reel/9/;2026-07-01T10:00:00+0000;1234;800\n'
        path = self.write_csv("semi.csv", text)
        s = ledger.import_file(path)
        self.assertEqual(s["created"], 1)
        self.assertEqual(ledger.load_rows()[0]["date"], "2026-07-01")


def make_posts(views, **extra):
    """Write a ledger with one reel per views value."""
    for i, v in enumerate(views):
        fields = dict(format="reel", date=f"2026-08-{i + 1:02d}", views=v)
        for k, vals in extra.items():
            fields[k] = vals[i]
        ledger.add_row(**fields)


class TestAudit(TempDataDir):
    def test_median_and_multiples(self):
        make_posts([1000, 2000, 3000, 4000, 10000],
                   reach=[800, 1600, 2500, 3000, 9000],
                   shares=[8, 16, 25, 30, 180])
        a = audit.analyse(ledger.load_rows())
        self.assertEqual(a["median_views"], 3000)
        by = {p["id"]: p for p in a["posts"]}
        self.assertAlmostEqual(by["P0005"]["outlier"], 3.33)
        self.assertAlmostEqual(by["P0001"]["outlier"], 0.33)
        self.assertAlmostEqual(by["P0005"]["sends_per_reach"], 0.02)
        self.assertEqual(a["top"][0]["id"], "P0005")
        self.assertEqual(a["bottom"][0]["id"], "P0001")
        # under 10 posts, top and bottom split instead of overlapping
        self.assertEqual((len(a["top"]), len(a["bottom"])), (3, 2))

    def test_top_bottom_five_each_at_ten(self):
        make_posts(list(range(100, 1500, 100)))
        a = audit.analyse(ledger.load_rows())
        self.assertEqual((len(a["top"]), len(a["bottom"])), (5, 5))
        self.assertEqual(a["bottom"][0]["views"], 100)

    def test_even_count_median(self):
        make_posts([100, 200, 300, 400])
        self.assertEqual(audit.analyse(ledger.load_rows())["median_views"], 250)

    def test_trials_excluded_from_baseline(self):
        make_posts([1000, 2000, 3000])
        ledger.add_row(format="reel", date="2026-08-10", views=90000, trial=True,
                       test_id="T001", variant="A")
        a = audit.analyse(ledger.load_rows())
        self.assertEqual(a["median_views"], 2000)
        self.assertEqual(a["n"], 3)
        self.assertEqual([p["id"] for p in a["trials"]], ["P0004"])
        self.assertNotIn("P0004", [p["id"] for p in a["top"]])
        self.assertAlmostEqual(a["trials"][0]["outlier"], 45.0)
        out = io.StringIO()
        audit.render(a, out=out)
        self.assertIn("TRIAL REELS", out.getvalue())

    def test_small_n_warning(self):
        make_posts([100, 200, 300])
        a = audit.analyse(ledger.load_rows())
        self.assertEqual(a["confidence"], "too_few")
        out = io.StringIO()
        audit.render(a, out=out)
        self.assertIn("cannot be trusted yet", out.getvalue())
        self.assertIn("n=3", out.getvalue())

    def test_confidence_levels(self):
        make_posts(list(range(100, 1300, 100)))
        self.assertEqual(audit.analyse(ledger.load_rows())["confidence"], "early")
        make_posts(list(range(100, 2000, 100)))
        a = audit.analyse(ledger.load_rows())
        self.assertGreaterEqual(a["n"], 30)
        self.assertEqual(a["confidence"], "visible")
        out = io.StringIO()
        audit.render(a, out=out)
        self.assertIn("patterns are visible", out.getvalue())

    def test_missing_metrics_do_not_crash(self):
        ledger.add_row(format="reel", views=500)               # views only
        ledger.add_row(format="reel", views=900, reach=0, shares=3)  # zero reach
        ledger.add_row(format="carousel")                      # nothing at all
        ledger.add_row(format="photo", views=300, reach=200, follows=1,
                       nonfollower_pct=70)
        a = audit.analyse(ledger.load_rows())
        self.assertEqual(a["n"], 3)
        self.assertEqual(a["n_without_views"], 1)
        by = {p["id"]: p for p in a["posts"]}
        self.assertIsNone(by["P0001"]["sends_per_reach"])
        self.assertIsNone(by["P0002"]["sends_per_reach"])
        out = io.StringIO()
        audit.render(a, out=out)
        json.dumps(a)
        code, out, _ = self.run_cli(audit, "--json")
        self.assertEqual(code, 0)
        json.loads(out)

    def test_empty_ledger(self):
        code, out, _ = self.run_cli(audit)
        self.assertEqual(code, 0)
        self.assertIn("Nothing to audit", out)

    def test_groups_and_length_buckets(self):
        make_posts([1000, 3000, 2000, 6000],
                   hook_formula=["3", "3", "11", "1"],
                   length_s=[10, 20, 45, 75],
                   theme=["pricing", "pricing", "tools", ""])
        a = audit.analyse(ledger.load_rows(), formulas={"3": "Nobody Tells You"})
        hooks = {g["group"]: g for g in a["groups"]["hook_formula"]}
        self.assertEqual(hooks["#3 Nobody Tells You"]["n"], 2)
        self.assertAlmostEqual(hooks["#3 Nobody Tells You"]["mean_outlier"], 0.8)
        self.assertTrue(hooks["#3 Nobody Tells You"]["thin"])
        lengths = {g["group"] for g in a["groups"]["length"]}
        self.assertEqual(lengths, {"<15s", "15-30s", "30-60s", "60s+"})
        self.assertEqual(audit.length_bucket(15), "15-30s")
        self.assertEqual(audit.length_bucket(30), "30-60s")
        self.assertEqual(audit.length_bucket(None), "unknown")
        themes = {g["group"] for g in a["groups"]["theme"]}
        self.assertIn("(not logged)", themes)

    def test_profile_problem(self):
        # travelled (>=50% non-follower) but under 0.2% follows per reach
        make_posts([20000, 30000, 25000],
                   reach=[18000, 27000, 22000], follows=[10, 20, 15],
                   nonfollower_pct=[70, 80, 65])
        a = audit.analyse(ledger.load_rows())
        self.assertTrue(a["profile"]["flag"])
        self.assertEqual(len(a["profile"]["posts_flagged"]), 3)
        out = io.StringIO()
        audit.render(a, out=out)
        self.assertIn("PROFILE PROBLEM", out.getvalue())

    def test_no_profile_problem_when_converting(self):
        make_posts([20000, 30000, 25000],
                   reach=[18000, 27000, 22000], follows=[150, 200, 180],
                   nonfollower_pct=[70, 80, 65])
        self.assertFalse(audit.analyse(ledger.load_rows())["profile"]["flag"])

    def test_filters(self):
        make_posts([1000, 2000, 3000])
        ledger.add_row(format="carousel", date="2026-09-01", views=50000)
        ledger.add_row(format="story", date="2026-09-02", views=10)
        a = audit.analyse(ledger.load_rows())
        self.assertEqual(a["n"], 4)                    # stories left out by default
        self.assertEqual(a["n_stories_excluded"], 1)
        self.assertEqual(audit.analyse(ledger.load_rows(), fmt="reel")["n"], 3)
        self.assertEqual(audit.analyse(ledger.load_rows(), fmt="story")["n"], 1)
        self.assertEqual(audit.analyse(ledger.load_rows(), since="2026-08-02")["n"], 3)
        code, out, _ = self.run_cli(audit, "--json", "--format", "reel", "--since", "2026-08-02")
        self.assertEqual(json.loads(out)["n"], 2)

    def test_audit_after_fixture_import(self):
        ledger.import_file(FIXTURE)
        code, out, _ = self.run_cli(audit)
        self.assertEqual(code, 0)
        self.assertIn("TOP 4 BY OUTLIER MULTIPLE", out)
        self.assertIn("BOTTOM 3", out)
        self.assertIn("n=7", out)                      # 8 imported, story left out


class AccountResolution(unittest.TestCase):
    """data_dir() follows the ig-account rule: IG_DATA_DIR, else the active
    account folder under IG_HOME, else IG_HOME."""

    def setUp(self):
        self.home = tempfile.mkdtemp(prefix="ig-ledger-home-")
        self._env = {k: os.environ.get(k) for k in ("IG_HOME", "IG_DATA_DIR")}
        os.environ["IG_HOME"] = self.home
        os.environ.pop("IG_DATA_DIR", None)

    def tearDown(self):
        for k, v in self._env.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        shutil.rmtree(self.home, ignore_errors=True)

    def activate(self, text, make="acme"):
        if make:
            os.makedirs(os.path.join(self.home, "accounts", make), exist_ok=True)
        with open(os.path.join(self.home, "active-account"), "w") as f:
            f.write(text)

    def test_single_account_default(self):
        self.assertEqual(ledger.data_dir(), self.home)
        self.assertEqual(ledger.ledger_path(), os.path.join(self.home, "posts.csv"))

    def test_active_account(self):
        self.activate(" @Acme\n")
        self.assertEqual(ledger.data_dir(), os.path.join(self.home, "accounts", "acme"))

    def test_missing_folder_falls_back(self):
        self.activate("ghost", make=None)
        self.assertEqual(ledger.data_dir(), self.home)

    def test_bad_handle_falls_back(self):
        self.activate("../acme", make=None)
        self.assertEqual(ledger.data_dir(), self.home)

    def test_ig_data_dir_wins(self):
        self.activate("acme")
        os.environ["IG_DATA_DIR"] = os.path.join(self.home, "override")
        self.assertEqual(ledger.data_dir(), os.path.join(self.home, "override"))

    def test_rows_stay_in_their_account(self):
        os.makedirs(os.path.join(self.home, "accounts", "client"))
        self.activate("acme")
        with contextlib.redirect_stdout(io.StringIO()):
            ledger.main(["add", "--format", "reel", "--first-line", "acme post"])
        self.assertEqual(len(ledger.load_rows()), 1)
        self.activate("client")
        self.assertEqual(ledger.load_rows(), [])
        self.assertTrue(os.path.isfile(os.path.join(self.home, "accounts", "acme", "posts.csv")))
        self.assertFalse(os.path.exists(os.path.join(self.home, "posts.csv")))


if __name__ == "__main__":
    unittest.main()
