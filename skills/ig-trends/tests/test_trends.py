"""Tests for trends.py. Stdlib only.

Run from the skill folder:  python3 -m unittest discover -s tests
Every test points IG_DATA_DIR / IG_HOME at a fresh temp dir. The real
~/IGStudio is never touched.
"""

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

import trends  # noqa: E402

TODAY = dt.date(2026, 10, 15)
ENV_KEYS = ("IG_DATA_DIR", "IG_HOME", "IG_TODAY")


class Env(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="ig-trends-test-")
        self._old = {k: os.environ.get(k) for k in ENV_KEYS}
        for k in ENV_KEYS:
            os.environ.pop(k, None)
        os.environ["IG_DATA_DIR"] = self.tmp
        os.environ["IG_TODAY"] = TODAY.isoformat()

    def tearDown(self):
        for k, v in self._old.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        shutil.rmtree(self.tmp, ignore_errors=True)

    def cli(self, *argv):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            trends.main(list(argv))
        return out.getvalue()

    def add(self, name, kind="topic", **kw):
        argv = ["add", "--source", kw.pop("source", "google"), "--region",
                kw.pop("region", "IN"), "--kind", kind, "--name", name]
        for k, v in kw.items():
            argv += ["--" + k.replace("_", "-"), str(v)]
        return self.cli(*argv)


class Resolver(Env):
    def test_ig_data_dir_wins(self):
        self.assertEqual(trends.data_dir(), self.tmp)

    def test_active_account_folder(self):
        os.environ.pop("IG_DATA_DIR")
        os.environ["IG_HOME"] = self.tmp
        acct = os.path.join(self.tmp, "accounts", "jane")
        os.makedirs(acct)
        with open(os.path.join(self.tmp, "active-account"), "w") as f:
            f.write("@jane\n")
        self.assertEqual(trends.data_dir(), acct)

    def test_active_account_missing_folder_falls_back(self):
        os.environ.pop("IG_DATA_DIR")
        os.environ["IG_HOME"] = self.tmp
        with open(os.path.join(self.tmp, "active-account"), "w") as f:
            f.write("ghost")
        self.assertEqual(trends.data_dir(), self.tmp)

    def test_no_active_account(self):
        os.environ.pop("IG_DATA_DIR")
        os.environ["IG_HOME"] = self.tmp
        self.assertEqual(trends.data_dir(), self.tmp)

    def test_traversal_handle_ignored(self):
        os.environ.pop("IG_DATA_DIR")
        os.environ["IG_HOME"] = self.tmp
        with open(os.path.join(self.tmp, "active-account"), "w") as f:
            f.write("../etc")
        self.assertEqual(trends.data_dir(), self.tmp)


class Add(Env):
    def test_add_appends_rows_with_ids(self):
        self.add("ITR deadline", rank=2, growth="+400%", first_seen="2026-10-14")
        self.add("Aaj Ki Raat", kind="song", source="tiktok")
        rows = trends.load_rows()
        self.assertEqual([r["id"] for r in rows], ["T0001", "T0002"])
        self.assertEqual(rows[0]["growth"], "+400%")
        self.assertEqual(rows[1]["first_seen"], TODAY.isoformat())
        self.assertTrue(os.path.exists(os.path.join(self.tmp, "trends.csv")))

    def test_add_reports_safety(self):
        out = self.add("Bridge collapse in city", source="news")
        self.assertIn("EXCLUDE", out)

    def test_bad_growth_rejected(self):
        with self.assertRaises(SystemExit):
            self.add("x", growth="lots")


class Values(unittest.TestCase):
    def test_parse_growth(self):
        self.assertEqual(trends.parse_growth("+250%"), 250)
        self.assertEqual(trends.parse_growth("-30%"), -30)
        self.assertEqual(trends.parse_growth("3x"), 200)
        self.assertEqual(trends.parse_growth("Breakout"), 5000)
        self.assertEqual(trends.parse_growth("1,000%"), 1000)
        self.assertIsNone(trends.parse_growth("lots"))

    def row(self, **kw):
        r = {"id": "T1", "kind": "meme", "rank": "1", "growth": "+1000%",
             "first_seen": TODAY.isoformat(), "name": "x", "notes": ""}
        r.update(kw)
        return r

    def test_decay_by_half_life(self):
        fresh = trends.momentum(self.row(), TODAY)["momentum"]
        d = (TODAY - dt.timedelta(days=4)).isoformat()   # one meme half-life
        old = trends.momentum(self.row(first_seen=d), TODAY)["momentum"]
        self.assertAlmostEqual(old, fresh / 2, delta=1)

    def test_song_decays_slower_than_meme(self):
        d = (TODAY - dt.timedelta(days=8)).isoformat()
        meme = trends.momentum(self.row(first_seen=d), TODAY)["momentum"]
        song = trends.momentum(self.row(kind="song", first_seen=d), TODAY)["momentum"]
        self.assertGreater(song, meme * 2)

    def test_rank_and_growth_raise_momentum(self):
        hi = trends.momentum(self.row(rank="1", growth="+2000%"), TODAY)["momentum"]
        lo = trends.momentum(self.row(rank="40", growth="+20%"), TODAY)["momentum"]
        self.assertGreater(hi, lo)

    def test_phase(self):
        self.assertEqual(trends.momentum(self.row(), TODAY)["phase"], "rising")
        d5 = (TODAY - dt.timedelta(days=5)).isoformat()
        self.assertEqual(trends.momentum(self.row(first_seen=d5), TODAY)["phase"], "peaking")
        d9 = (TODAY - dt.timedelta(days=9)).isoformat()
        self.assertEqual(trends.momentum(self.row(first_seen=d9), TODAY)["phase"], "fading")
        self.assertEqual(trends.momentum(self.row(growth="-20%"), TODAY)["phase"], "fading")

    def test_safety(self):
        self.assertEqual(trends.safety_of(self.row(name="Earthquake in Delhi"))[0], "exclude")
        self.assertEqual(trends.safety_of(self.row(name="Bihar election results"))[0], "flag")
        self.assertEqual(trends.safety_of(self.row(name="Diwali outfit trend"))[0], "ok")
        # word boundaries: "warm" is not "war", "rip" not in "trip"
        self.assertEqual(trends.safety_of(self.row(name="warm trip vlog"))[0], "ok")
        self.assertEqual(trends.safety_of(self.row(name="x", source="news"))[0], "flag")
        self.assertEqual(trends.safety_of(self.row(name="Earthquake meme", safety="ok"))[0], "ok")

    def test_read_proof(self):
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "voice.md")
            with open(p, "w") as f:
                f.write("# voice\n## Proof I can use\n\nintro\n\n- Recovered $4,000 "
                        "from a late client with one clause\n-\n- 212 contracts reviewed\n"
                        "## The ask\n- keyword: CLAUSE\n")
            self.assertEqual(trends.read_proof(p), [
                "Recovered $4,000 from a late client with one clause",
                "212 contracts reviewed"])
            self.assertEqual(trends.read_proof(os.path.join(d, "nope.md")), [])


class Blend(Env):
    def seed(self):
        self.add("Diwali bonus", rank=1, growth="+900%", first_seen="2026-10-14",
                 niche_match=3)
        self.add("Old meme", kind="meme", rank=1, growth="+900%",
                 first_seen="2026-10-03", niche_match=3)
        self.add("Stadium stampede", source="news", rank=1, growth="Breakout")
        self.add("Election exit polls", rank=2, growth="+500%", niche_match=2)
        self.add("Cricket final", rank=3, growth="+300%")
        self.add("red pen clause read-aloud", kind="format", source="instagram",
                 scope="niche", niche_match=3)

    def test_blend_ranks_and_excludes(self):
        self.seed()
        out = self.cli("blend", "--niche", "freelance contracts", "--json")
        b = json.loads(out)
        names = [x["trend"] for x in b["board"]]
        self.assertEqual(names[0], "Diwali bonus")
        self.assertNotIn("Stadium stampede", names)
        self.assertEqual([e["name"] for e in b["excluded"]], ["Stadium stampede"])
        self.assertNotIn("Old meme", names)       # day 12, past the 10-day meme lifespan
        ex = next(x for x in b["board"] if x["trend"] == "Election exit polls")
        self.assertEqual(ex["safety"], "flag")
        top = b["board"][0]
        self.assertEqual(top["angle"], "red pen clause read-aloud")
        self.assertEqual(top["formula_id"], 9)
        self.assertEqual(top["niche_fit_source"], "set")
        cricket = next(x for x in b["board"] if x["trend"] == "Cricket final")
        self.assertEqual(cricket["niche_fit_source"], "guess")
        self.assertTrue(os.path.exists(os.path.join(self.tmp, "trends.md")))

    def test_flag_penalty(self):
        self.add("Same trend A", rank=1, growth="+500%", niche_match=2)
        self.add("Same trend B election", rank=1, growth="+500%", niche_match=2)
        b = json.loads(self.cli("blend", "--niche", "x", "--json", "--no-write"))
        sc = {x["trend"]: x["score"] for x in b["board"]}
        self.assertLess(sc["Same trend B election"], sc["Same trend A"])

    def test_proof_used_when_present(self):
        with open(os.path.join(self.tmp, "voice.md"), "w") as f:
            f.write("## Proof I can use\n- 212 freelance contracts reviewed\n")
        self.add("Diwali bonus", rank=1, growth="+900%", niche_match=3)
        b = json.loads(self.cli("blend", "--niche", "freelance contracts", "--json"))
        self.assertEqual(b["board"][0]["proof"], "212 freelance contracts reviewed")
        self.assertEqual(b["proofs"], 1)

    def test_no_niche_rows_uses_niche_as_angle(self):
        self.add("Diwali bonus", rank=1)
        b = json.loads(self.cli("blend", "--niche", "freelance contracts", "--json"))
        self.assertEqual(b["board"][0]["angle"], "freelance contracts")

    def test_max_two_angles_per_trend_and_top(self):
        self.add("Hot", rank=1, growth="+900%")
        b = json.loads(self.cli("blend", "--niche", "n", "--angle", "a", "--angle", "b",
                                "--angle", "c", "--json", "--top", "5"))
        self.assertEqual(len(b["board"]), 2)

    def test_song_fills_sound_slot(self):
        self.add("Aaj Ki Raat", kind="song", source="tiktok", rank=1)
        b = json.loads(self.cli("blend", "--niche", "n", "--json"))
        self.assertEqual(b["board"][0]["sound"], "Aaj Ki Raat")

    def test_region_filter(self):
        self.add("India thing", region="IN")
        self.add("US thing", region="US")
        b = json.loads(self.cli("blend", "--niche", "n", "--region", "us", "--json"))
        self.assertEqual([x["trend"] for x in b["board"]], ["US thing"])

    def test_text_board(self):
        self.seed()
        out = self.cli("blend", "--niche", "freelance contracts")
        self.assertIn("VIRALITY BLAST", out)
        self.assertIn("LEFT OUT, NOT SAFE TO RIDE", out)
        self.assertIn("Nobody can promise", out)
        self.assertNotIn("\u2014", out)
        with open(os.path.join(self.tmp, "trends.md"), encoding="utf-8") as f:
            md = f.read()
        self.assertIn("# Virality blast", md)
        self.assertNotIn("\u2014", md)


class Prune(Env):
    def test_prune_drops_expired_only(self):
        self.add("old meme", kind="meme", first_seen="2026-10-01")    # day 14 > 10
        self.add("old song", kind="song", first_seen="2026-10-01")    # day 14 < 35
        self.add("new topic", first_seen="2026-10-14")
        out = json.loads(self.cli("prune", "--dry-run", "--json"))
        self.assertEqual(out["removed"], ["T0001"])
        self.assertEqual(len(trends.load_rows()), 3)
        self.cli("prune")
        self.assertEqual([r["name"] for r in trends.load_rows()], ["old song", "new topic"])

    def test_list(self):
        self.add("a thing")
        out = self.cli("list")
        self.assertIn("a thing", out)
        rows = json.loads(self.cli("list", "--json"))
        self.assertEqual(rows[0]["phase"], "rising")


if __name__ == "__main__":
    unittest.main()
