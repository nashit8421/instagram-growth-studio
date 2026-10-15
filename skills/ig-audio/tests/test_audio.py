"""
Tests for audio.py. Run from the ig-audio folder:

    python3 -m unittest discover -s tests

Every test points IG_DATA_DIR (or IG_HOME) at its own temp dir. Nothing
touches ~/IGStudio or ~/.claude/skills. Script timing uses the
built-in fallback unless a test opts into beats.py.
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

# Guard: never let an import-time default reach the real data dir.
os.environ["IG_DATA_DIR"] = tempfile.mkdtemp(prefix="igaudio-import-")
os.environ.pop("IG_HOME", None)

TESTS = os.path.dirname(os.path.abspath(__file__))
SKILL = os.path.dirname(TESTS)
sys.path.insert(0, SKILL)
import audio  # noqa: E402

TODAY = "2026-10-15"
D = dt.date.fromisoformat


def run(*argv):
    buf = io.StringIO()
    err = io.StringIO()
    with contextlib.redirect_stderr(err):
        code = audio.main(list(argv) + [f"--today={TODAY}"], out=buf)
    return code, buf.getvalue()


def add(name, **kw):
    argv = ["add", "--name", name, "--source", kw.pop("source", "instagram"),
            "--region", kw.pop("region", "IN")]
    for k, v in kw.items():
        argv += ["--" + k.replace("_", "-"), str(v)]
    code, out = run(*argv)
    assert code == 0, out
    return out


def suggest(*extra):
    code, out = run("suggest", "--reel-length", "28", "--json", "--top", "20", *extra)
    assert code == 0, out
    return json.loads(out)


def names(res):
    return [p["name"] for p in res["picks"]]


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="igaudio-")
        self._env = {k: os.environ.get(k) for k in ("IG_DATA_DIR", "IG_HOME")}
        os.environ["IG_DATA_DIR"] = self.tmp
        os.environ.pop("IG_HOME", None)
        self._dirs = audio.BEATS_DIRS
        audio.BEATS_DIRS = []           # fallback timing unless a test opts in

    def tearDown(self):
        audio.BEATS_DIRS = self._dirs
        for k, v in self._env.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        shutil.rmtree(self.tmp, ignore_errors=True)

    def rows(self):
        with open(os.path.join(self.tmp, "sounds.csv"), encoding="utf-8") as f:
            return list(csv.DictReader(f))


class DataDir(Base):
    def test_active_account_and_fallbacks(self):
        home = os.path.join(self.tmp, "home")
        os.makedirs(os.path.join(home, "accounts", "acme"))
        os.environ.pop("IG_DATA_DIR")
        os.environ["IG_HOME"] = home
        self.assertEqual(audio.data_dir(), home)
        with open(os.path.join(home, "active-account"), "w") as f:
            f.write("@acme\n")
        self.assertEqual(audio.data_dir(), os.path.join(home, "accounts", "acme"))
        with open(os.path.join(home, "active-account"), "w") as f:
            f.write("ghost")
        self.assertEqual(audio.data_dir(), home)   # folder missing: fall back
        os.environ["IG_DATA_DIR"] = self.tmp
        self.assertEqual(audio.data_dir(), self.tmp)


class Upsert(Base):
    def test_add_then_update_computes_growth(self):
        add("Song A", artist="X", reels_count="2K", seen="2026-10-05", trend="rising")
        out = add("song a ", artist="x", reels_count="4,000", seen="2026-10-10")
        rows = self.rows()
        self.assertEqual(len(rows), 1)                  # upserted, not duplicated
        r = rows[0]
        self.assertEqual(r["reels_count"], "4000")
        self.assertEqual(r["prev_reels_count"], "2000")
        self.assertEqual(r["prev_seen"], "2026-10-05")
        self.assertEqual(r["first_seen"], "2026-10-05")
        self.assertEqual(r["last_seen"], "2026-10-10")
        self.assertIn("+100%", out)
        g, prev, now, days = audio.row_growth(r)
        self.assertEqual(days, 5)
        self.assertAlmostEqual(g, 2 ** (1 / 5) - 1, places=6)
        # trend not passed on update: inferred from 14.9% a day
        self.assertEqual(r["trend"], "rising")
        self.assertIn("trend set to rising", out)

    def test_inferred_fading_and_kept_fields(self):
        add("Song B", reels_count=5000, seen="2026-10-01", bpm=100, mood="calm",
            business_ok="yes")
        add("Song B", reels_count=4900, seen="2026-10-08")
        r = self.rows()[0]
        self.assertEqual(r["trend"], "fading")
        self.assertEqual((r["bpm"], r["mood"], r["business_ok"]), ("100", "calm", "yes"))

    def test_explicit_trend_wins_and_same_artist_distinguishes(self):
        add("Song C", artist="One", reels_count=1000, seen="2026-10-01")
        add("Song C", artist="One", reels_count=900, seen="2026-10-05", trend="peaking")
        add("Song C", artist="Two", reels_count=50)
        rows = self.rows()
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0]["trend"], "peaking")

    def test_parse_count(self):
        self.assertEqual(audio.parse_count("1.2K"), 1200)
        self.assertEqual(audio.parse_count("3M"), 3000000)
        self.assertEqual(audio.parse_count("12,400"), 12400)
        self.assertIsNone(audio.parse_count(""))
        with self.assertRaises(ValueError):
            audio.parse_count("lots")


class Ranking(Base):
    def test_trend_order(self):
        for t in ("fading", "peaking", "rising"):
            add(f"T {t}", reels_count=5000, trend=t, seen=TODAY)
        self.assertEqual(names(suggest()), ["T rising", "T peaking", "T fading"])

    def test_reels_count_sweet_spot(self):
        add("Tiny", reels_count=100, trend="rising", seen=TODAY)
        add("Sweet", reels_count=8000, trend="rising", seen=TODAY)
        add("Crowded", reels_count=900000, trend="rising", seen=TODAY)
        n = names(suggest())
        self.assertEqual(n[0], "Sweet")
        self.assertEqual(audio.count_fit("instagram", 8000)[0], 1.0)
        self.assertLess(audio.count_fit("instagram", 100)[0], 0.5)
        self.assertLess(audio.count_fit("instagram", 900000)[0], 0.5)
        # TikTok has its own scale
        self.assertEqual(audio.count_fit("tiktok", 200000)[0], 1.0)

    def test_growth_between_sightings_breaks_ties(self):
        add("Hot", reels_count=1000, seen="2026-10-12", trend="rising")
        add("Hot", reels_count=3000, seen="2026-10-15", trend="rising")
        add("Flat", reels_count=3000, seen="2026-10-12", trend="rising")
        add("Flat", reels_count=3000, seen="2026-10-15", trend="rising")
        res = suggest()
        self.assertEqual(names(res)[0], "Hot")
        self.assertTrue(any("a day" in w for w in res["picks"][0]["why"]))

    def test_mood_fit(self):
        add("Calm one", reels_count=5000, trend="rising", mood="calm", seen=TODAY)
        add("Upbeat one", reels_count=5000, trend="rising", mood="upbeat", seen=TODAY)
        self.assertEqual(names(suggest("--mood", "upbeat"))[0], "Upbeat one")
        self.assertEqual(names(suggest("--mood", "calm"))[0], "Calm one")
        self.assertEqual(audio.mood_fit("calm", "lofi"), 0.6)   # neighbour

    def test_region_penalty(self):
        add("Here", reels_count=5000, trend="rising", seen=TODAY, region="IN")
        add("There", reels_count=5000, trend="rising", seen=TODAY, region="US")
        res = suggest("--region", "in")
        self.assertEqual(names(res)[0], "Here")
        self.assertTrue(any("trending in US" in f for f in res["picks"][1]["flags"]))


class Business(Base):
    def setUp(self):
        super().setUp()
        add("Licensed hit", reels_count=5000, trend="rising", business_ok="no", seen=TODAY)
        add("Collection track", reels_count=5000, trend="rising", business_ok="yes",
            seen=TODAY)
        add("Mystery", reels_count=5000, trend="rising", business_ok="unknown", seen=TODAY)

    def test_business_excludes_no_and_flags_unknown(self):
        res = suggest("--account", "business")
        n = names(res)
        self.assertNotIn("Licensed hit", n)
        self.assertEqual(n, ["Collection track", "Mystery"])
        self.assertEqual([e["name"] for e in res["excluded"]], ["Licensed hit"])
        mystery = res["picks"][1]
        self.assertTrue(any("business use unknown" in f for f in mystery["flags"]))
        self.assertAlmostEqual(mystery["parts"]["eligibility"], audio.ELIG_UNKNOWN_BUSINESS)

    def test_creator_sees_everything(self):
        res = suggest("--account", "creator")
        self.assertEqual(len(res["picks"]), 3)
        self.assertEqual(res["excluded"], [])

    def test_text_report_names_exclusion(self):
        code, out = run("suggest", "--reel-length", "20", "--account", "business")
        self.assertEqual(code, 0)
        self.assertIn("left out 1 not cleared for business accounts: Licensed hit", out)
        self.assertIn("Add the sound inside Instagram", out)
        self.assertIn("Audio is one factor", out)
        self.assertNotIn("\u2014", out)          # no em dashes in the report


class Freshness(Base):
    def test_decay_curve(self):
        today = D(TODAY)
        f = lambda days: audio.freshness(
            {"first_seen": (today - dt.timedelta(days=days)).isoformat(),
             "last_seen": TODAY}, today)[0]
        self.assertEqual(f(0), 1.0)
        self.assertEqual(f(audio.FRESH_FULL_DAYS), 1.0)
        self.assertAlmostEqual(f(audio.FRESH_HALF_DAYS), 0.5)
        self.assertAlmostEqual(f(audio.FRESH_HALF_DAYS + audio.FRESH_HALVING_DAYS), 0.25)
        self.assertGreater(f(10), f(20))

    def test_old_sound_ranks_lower_and_stale_is_flagged(self):
        add("New", reels_count=5000, trend="rising", seen="2026-10-13")
        add("Old", reels_count=5000, trend="rising", seen="2026-09-10")
        res = suggest()
        self.assertEqual(names(res), ["New", "Old"])
        self.assertTrue(any("last checked" in f for f in res["picks"][1]["flags"]))


SCRIPT_FAST = "\n".join(["Two words."] * 10)          # ~0.7s beats
SCRIPT_SLOW = "\n".join(["This line has quite a few more words in it than that."] * 6)


class Bpm(Base):
    def write(self, text):
        p = os.path.join(self.tmp, "script.txt")
        with open(p, "w", encoding="utf-8") as f:
            f.write(text)
        return p

    def test_grid_fit(self):
        # 2.0s beat at 120 bpm is exactly 4 beats of the song
        score, k, n = audio.grid_fit(2.0, 120)
        self.assertEqual((score, k), (1.0, 4))
        # halfway between 4 and 8 scores 0
        self.assertEqual(audio.grid_fit(3.0, 120)[0], 0.0)

    def test_pace_matches_script(self):
        add("Slow song", reels_count=5000, trend="rising", bpm=70, seen=TODAY)
        add("Fast song", reels_count=5000, trend="rising", bpm=150, seen=TODAY)
        fast = suggest("--script", self.write(SCRIPT_FAST))
        self.assertEqual(names(fast)[0], "Fast song")
        self.assertEqual(fast["script"]["engine"], "fallback")
        slow = suggest("--script", self.write(SCRIPT_SLOW))
        self.assertEqual(names(slow)[0], "Slow song")
        self.assertIsNotNone(slow["picks"][0]["grid"])
        self.assertTrue(any("beats average" in h for h in slow["picks"][0]["how"]))

    def test_drop_lands_on_payoff_and_voiceover_volume(self):
        add("Any", reels_count=5000, trend="rising", bpm=100, seen=TODAY)
        script = "Hook line here.\nOne.\nTwo two.\nThe payoff is 9 signed.\nComment hook."
        res = suggest("--script", self.write(script), "--voiceover", "yes")
        how = " ".join(res["picks"][0]["how"])
        self.assertIn("payoff, beat 4", how)
        self.assertIn("10-20%", how)
        self.assertIsNotNone(res["original_audio"])
        self.assertIn("original audio", res["original_audio"])

    def test_no_voiceover_no_original_audio_block(self):
        add("Any", reels_count=5000, trend="rising", seen=TODAY)
        self.assertIsNone(suggest("--voiceover", "no")["original_audio"])

    def test_uses_beats_py_when_present(self):
        fake = os.path.join(self.tmp, "ig-reel")
        os.makedirs(fake)
        with open(os.path.join(fake, "beats.py"), "w") as f:
            f.write("def analyse(raw, wpm=165, target=None):\n"
                    "    return {'total_seconds': 6.0, 'beats': [\n"
                    "        {'n': 1, 'start': 0.0, 'dur': 2.0, 'label': 'HOOK'},\n"
                    "        {'n': 2, 'start': 2.0, 'dur': 2.0, 'label': ''},\n"
                    "        {'n': 3, 'start': 4.0, 'dur': 2.0, 'label': 'CTA'}]}\n")
        audio.BEATS_DIRS = [fake]
        add("Any", reels_count=5000, trend="rising", bpm=120, seen=TODAY)
        res = suggest("--script", self.write("a\nb\nc"))
        self.assertEqual(res["script"]["engine"], "beats.py")
        self.assertEqual(res["picks"][0]["grid"]["grid"], 4)
        self.assertEqual(res["picks"][0]["parts"]["bpm"], 1.0)


class Prune(Base):
    def test_prune_and_dry_run(self):
        add("Recent", seen="2026-10-10")
        add("Old", seen="2026-09-01")
        add("Edge", seen="2026-09-17")          # exactly on the cutoff: kept
        code, out = run("prune", "--older-than", "28", "--dry-run")
        self.assertIn("would drop: Old", out)
        self.assertEqual(len(self.rows()), 3)
        code, out = run("prune", "--older-than", "28")
        self.assertEqual(code, 0)
        self.assertEqual(sorted(r["name"] for r in self.rows()), ["Edge", "Recent"])
        self.assertIn("1 pruned, 2 kept", out)


class ListCmd(Base):
    def test_list_json_and_filters(self):
        add("A", region="IN", trend="rising", seen=TODAY)
        add("B", region="US", trend="fading", seen=TODAY)
        code, out = run("list", "--region", "in", "--json")
        self.assertEqual([r["name"] for r in json.loads(out)], ["A"])
        code, out = run("list", "--trend", "fading")
        self.assertIn("B", out)
        self.assertIn("1 sound ", out)

    def test_empty(self):
        code, out = run("list")
        self.assertIn("No sounds saved", out)
        code, out = run("suggest", "--reel-length", "20")
        self.assertIn("No sounds saved yet", out)


if __name__ == "__main__":
    unittest.main()
