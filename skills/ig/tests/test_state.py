"""Tests for state.py. Stdlib only.

Run from the skill folder:  python3 -m unittest discover -s tests
Every test points IG_HOME and IG_DATA_DIR at a fresh temp dir and runs
build_state with checks off, so nothing outside the temp dir is read.
"""

import contextlib
import datetime as dt
import io
import json
import os
import shutil
import sys
import tempfile
import time
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))

import state  # noqa: E402

TODAY = dt.date(2026, 10, 15)          # a Thursday

FILLED_VOICE = """# Voice
- **Who I talk to:** freelancers in their first year
- **How I sound:** blunt, warm, a bit dry
- **Words I use:** scope, invoice, retainer
"""


def set_mtime(path, day):
    ts = time.mktime(dt.datetime(day.year, day.month, day.day, 12).timetuple())
    os.utime(path, (ts, ts))


class StateTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="ig-state-test-")
        self.data = os.path.join(self.tmp, "data")
        os.makedirs(self.data)
        self._env = {k: os.environ.get(k) for k in ("IG_HOME", "IG_DATA_DIR")}
        os.environ["IG_HOME"] = os.path.join(self.tmp, "home")
        os.environ["IG_DATA_DIR"] = self.data

    def tearDown(self):
        for k, v in self._env.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        shutil.rmtree(self.tmp, ignore_errors=True)

    def write(self, name, text, day=None):
        path = os.path.join(self.data, name)
        with open(path, "w", encoding="utf-8") as f:
            f.write(text if isinstance(text, str) else json.dumps(text))
        if day:
            set_mtime(path, day)
        return path

    def scan(self, scanned=TODAY, tier="micro", niche="freelancing and careers", followers=18400):
        self.write("account.json", {"handle": "me", "scanned_at": f"{scanned.isoformat()}T10:00:00",
                                    "size": {"tier": tier, "followers": followers},
                                    "niche_guess": {"label": niche}, "n_feed": 40})

    def setup_done(self):
        self.scan()
        self.write("profile.json", {"region": "IN", "niche": "freelance contracts", "account_type": "creator"})
        self.write("voice.md", FILLED_VOICE)
        self.write("followers.csv", f"date,followers\n{TODAY.isoformat()},18400\n")

    def keys(self, today=TODAY):
        return [s["key"] for s in state.build_state(today, checks=False)["next"]]


class TestSetupOrder(StateTest):
    def test_fresh_account_scan_comes_first(self):
        st = state.build_state(TODAY, checks=False)
        keys = [s["key"] for s in st["next"]]
        self.assertEqual(keys[:4], ["scan", "profile", "voice", "baseline"])
        first = st["next"][0]
        self.assertEqual(first["skill"], "/ig-scan")
        self.assertTrue(first["blocking"])
        self.assertIn("Which Instagram account are we growing?", first["ask"])
        self.assertIn("kweo", first["ask"])
        self.assertEqual(st["stage"], "setup")
        self.assertIsNone(st["scan"])

    def test_with_scan_profile_is_first_and_mentions_prefill(self):
        self.scan()
        st = state.build_state(TODAY, checks=False)
        keys = [s["key"] for s in st["next"]]
        self.assertNotIn("scan", keys)
        self.assertNotIn("rescan", keys)
        self.assertEqual(keys[0], "profile")
        self.assertIn("prefill", st["next"][0]["why"])
        baseline = next(s for s in st["next"] if s["key"] == "baseline")
        self.assertIn("18,400", baseline["why"])
        self.assertEqual(st["scan"]["size_tier"], "micro")
        self.assertEqual(st["scan"]["niche_guess"], "freelancing and careers")
        self.assertEqual(st["scan"]["scanned"], TODAY.isoformat())

    def test_with_scan_nothing_blocks_or_asks(self):
        # After a scan, Claude fills profile, voice and baseline itself and
        # goes straight on to the plan: no questions, nothing blocking.
        self.scan()
        st = state.build_state(TODAY, checks=False)
        for s in st["next"]:
            self.assertFalse(s["blocking"], s["key"])
            if s["key"] in ("profile", "voice", "baseline", "plan"):
                self.assertIsNone(s["ask"], s["key"])
        self.assertIn("plan", [s["key"] for s in st["next"]])

    def test_setup_done_goes_to_run(self):
        self.setup_done()
        st = state.build_state(TODAY, checks=False)
        self.assertEqual(st["stage"], "run")
        keys = [s["key"] for s in st["next"]]
        for k in ("scan", "profile", "voice", "baseline"):
            self.assertNotIn(k, keys)
        self.assertEqual(keys[-1], "engage")
        self.assertIn("trends", keys)
        self.assertIn("plan", keys)

    def test_voice_never_asks_or_blocks(self):
        # Posts copy viral reels' tone, so nobody is asked for their own captions.
        st = state.build_state(TODAY, checks=False)
        voice = next(s for s in st["next"] if s["key"] == "voice")
        self.assertIsNone(voice["ask"])
        self.assertFalse(voice["blocking"])

    def test_viral_research_before_trends_and_plan(self):
        self.setup_done()
        keys = self.keys()
        self.assertIn("viral", keys)
        self.assertLess(keys.index("viral"), keys.index("plan"))
        self.write("viral.json", {"reels": []}, day=TODAY - dt.timedelta(days=3))
        self.assertNotIn("viral", self.keys())
        self.write("viral.json", {"reels": []}, day=TODAY - dt.timedelta(days=20))
        st = state.build_state(TODAY, checks=False)
        viral = next(s for s in st["next"] if s["key"] == "viral")
        self.assertIn("20 days old", viral["why"])
        self.assertEqual(st["viral_age_days"], 20)

    def test_profile_score_only_after_setup_and_empty_ledger(self):
        self.setup_done()
        self.assertIn("profile_score", self.keys())
        self.write("posts.csv", "id,date,format\nP0001,2026-10-10,reel\n")
        self.assertNotIn("profile_score", self.keys())


class TestRescan(StateTest):
    def test_fresh_scan_no_rescan(self):
        self.setup_done()
        self.assertNotIn("rescan", self.keys())

    def test_thirty_days_is_not_stale_yet(self):
        self.setup_done()
        self.scan(scanned=TODAY - dt.timedelta(days=30))
        self.assertNotIn("rescan", self.keys())

    def test_stale_scan_adds_nonblocking_rescan(self):
        self.setup_done()
        self.scan(scanned=TODAY - dt.timedelta(days=45))
        st = state.build_state(TODAY, checks=False)
        step = next(s for s in st["next"] if s["key"] == "rescan")
        self.assertEqual(step["skill"], "/ig-scan")
        self.assertFalse(step["blocking"])
        self.assertIn("45 days", step["why"])
        self.assertEqual(st["stage"], "run")

    def test_unparseable_date_falls_back_to_mtime(self):
        self.setup_done()
        path = self.write("account.json", {"handle": "me", "scanned_at": "soon"},
                          day=TODAY - dt.timedelta(days=40))
        self.assertTrue(os.path.exists(path))
        self.assertIn("rescan", self.keys())

    def test_broken_account_json_counts_as_missing(self):
        self.write("account.json", "{not json")
        self.assertEqual(self.keys()[0], "scan")


class TestTodaySlot(StateTest):
    def test_today_slot_from_current_plan(self):
        self.setup_done()
        self.write("plan.md", "WEEK\nWED  -\nTHU  REEL  pricing myth, formula 3\nFRI  CAROUSEL  scope\n",
                   day=TODAY)
        st = state.build_state(TODAY, checks=False)
        self.assertEqual(st["today"]["day"], "THU")
        self.assertEqual(st["today"]["format"], "reel")
        step = next(s for s in st["next"] if s["key"] == "create_today")
        self.assertIn("/ig-reel", step["skill"])
        self.assertNotIn("plan", [s["key"] for s in st["next"]])

    def test_rest_day_has_no_create_step(self):
        self.setup_done()
        self.write("plan.md", "THU  -\n", day=TODAY)
        st = state.build_state(TODAY, checks=False)
        self.assertTrue(st["today"]["rest"])
        self.assertNotIn("create_today", [s["key"] for s in st["next"]])

    def test_stale_plan_is_ignored(self):
        self.setup_done()
        self.write("plan.md", "THU  REEL  old\n", day=TODAY - dt.timedelta(days=10))
        st = state.build_state(TODAY, checks=False)
        self.assertIsNone(st["today"])
        self.assertIn("plan", [s["key"] for s in st["next"]])


class TestVoice(StateTest):
    def test_missing(self):
        self.assertEqual(state.voice_status(), "missing")

    def test_template(self):
        self.write("voice.md", "Copy this to your data folder.\n- **Who I talk to:** (fill in)\n- **Tone:**\n")
        self.assertEqual(state.voice_status(), "template")

    def test_filled_fields(self):
        self.write("voice.md", FILLED_VOICE)
        self.assertEqual(state.voice_status(), "filled")

    def test_short_plain_voice_counts_as_filled(self):
        # A voice.md Claude drafted from captions, with plain "Field: value" lines
        self.write("voice.md", "# Voice\n\nWho: an actor in the making.\nLanguage: Hinglish.\n"
                               "Tone: teasing, sassy.\nEmoji: 1-2 per caption.\n")
        self.assertEqual(state.voice_status(), "filled")

    def test_free_text_counts(self):
        self.write("voice.md", "# Voice\n\n" + "I write short and plain sentences about contracts. " * 20)
        self.assertEqual(state.voice_status(), "filled")


class TestCLI(StateTest):
    def run_cli(self, *argv):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = state.main(list(argv))
        return code, out.getvalue()

    def test_render_shows_scan_line(self):
        code, out = self.run_cli("--no-checks", "--today", TODAY.isoformat())
        self.assertIn("scan       not yet (/ig-scan)", out)
        self.scan()
        code, out = self.run_cli("--no-checks", "--today", TODAY.isoformat())
        self.assertIn("micro, niche guess freelancing and careers, scanned 2026-10-15", out)

    def test_json_has_scan(self):
        self.scan()
        code, out = self.run_cli("--no-checks", "--today", TODAY.isoformat(), "--json")
        st = json.loads(out)
        self.assertEqual(st["scan"]["followers"], 18400)

    def test_set_profile(self):
        code, out = self.run_cli("set", "--region", "in", "--niche", "freelance contracts",
                                 "--account-type", "creator")
        self.assertEqual(code, 0)
        self.assertEqual(state.load_profile()["region"], "IN")


if __name__ == "__main__":
    unittest.main()
