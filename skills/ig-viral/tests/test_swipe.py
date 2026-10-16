"""Tests for swipe.py. Stdlib only.

Run from the skill folder:  python3 -m unittest discover -s tests
"""

import json
import os
import subprocess
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
SWIPE = os.path.join(os.path.dirname(HERE), "swipe.py")
sys.path.insert(0, os.path.dirname(HERE))

import swipe  # noqa: E402

TSV = ("account\tfollowers\tmedian\tviews\thook\turl\tlength\tstructure\n"
       "@small\t4000\t2000\t80000\tnobody tells you your first 30 reels flop\thttps://www.instagram.com/reel/AAA/\t21s\t"
       "hook, 3 quick fails, the fix, the loop\n"
       "@big\t2000000\t500000\t400000\tstop doing this before an audition\t\t\t\n"
       "@mid\t20000\t5000\t30000\tI tried acting in 5 accents\thttps://www.instagram.com/reel/BBB/\t34\t\n")


class TestViralJson(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.tsv = os.path.join(self.tmp, "captured.tsv")
        with open(self.tsv, "w", encoding="utf-8") as f:
            f.write(TSV)

    def run_swipe(self):
        out = os.path.join(self.tmp, "acct", "swipe.md")
        r = subprocess.run([sys.executable, SWIPE, self.tsv, "--out", out], capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stderr)
        return out

    def test_out_writes_viral_json_next_to_swipe_md(self):
        out = self.run_swipe()
        v = json.load(open(os.path.join(os.path.dirname(out), "viral.json"), encoding="utf-8"))
        self.assertEqual(v["n"], 3)
        ids = [r["id"] for r in v["reels"]]
        self.assertEqual(ids, ["V01", "V02", "V03"])
        top = v["reels"][0]
        self.assertEqual(top["account"], "@small")       # 40x beats a big raw number
        self.assertEqual(top["multiple"], 40.0)
        self.assertEqual(top["views"], 80000)
        self.assertEqual(top["url"], "https://www.instagram.com/reel/AAA/")
        self.assertEqual(top["length_s"], 21)
        self.assertEqual(top["structure"], "hook, 3 quick fails, the fix, the loop")
        big = [r for r in v["reels"] if r["account"] == "@big"][0]
        self.assertNotIn("url", big)                     # empty cells are left out, never filled in
        self.assertIsNone(big["length_s"])

    def test_swipe_md_names_the_ids(self):
        out = self.run_swipe()
        md = open(out, encoding="utf-8").read()
        self.assertIn("## V01  40.0x", md)
        self.assertIn("- url: https://www.instagram.com/reel/AAA/", md)

    def test_to_viral_without_optional_columns(self):
        rows = swipe.read_rows(self.tsv)
        a = swipe.analyse(rows, swipe.load_formulas(swipe.HOOKS))
        v = swipe.to_viral(a)
        self.assertTrue(all(r["id"].startswith("V") for r in v["reels"]))


def reader_file(tmp, handle, reels, followers=5000):
    path = os.path.join(tmp, f"reader-{handle}.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump({"handle": handle, "followers": followers, "source": "kweo", "reels": reels}, f)
    return path


class TestReader(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()

    def test_likes_when_views_are_hidden_and_median_from_own_reels(self):
        reels = [{"url": f"https://www.instagram.com/reel/R{i}/", "likes": n, "comments": 3,
                  "caption": f"Reel number {i} #dadlife"} for i, n in enumerate([100, 120, 90, 2400, 110])]
        reels.append({"url": "https://www.instagram.com/reel/NOLIKES/", "caption": "no count shown"})
        rows, notes = swipe.read_reader([reader_file(self.tmp, "dad_a", reels)])
        self.assertEqual(len(rows), 5)                      # the reel with no number is left out
        self.assertTrue(all(r["metric"] == "likes" and r["median"] == 110 for r in rows))
        a = swipe.analyse(rows, swipe.load_formulas(swipe.HOOKS))
        v = swipe.to_viral(a)
        top = v["reels"][0]
        self.assertEqual(top["url"], "https://www.instagram.com/reel/R3/")
        self.assertEqual(top["likes"], 2400)
        self.assertIsNone(top["views"])
        self.assertEqual(top["metric"], "likes")
        self.assertEqual(top["multiple"], round(2400 / 110, 2))
        self.assertEqual(top["hook"], "Reel number 3")      # caption's first line, hashtags dropped

    def test_views_win_when_most_reels_show_them(self):
        reels = [{"url": f"u{i}", "views": v, "likes": 5, "caption": "x"} for i, v in enumerate(["1.2K", "16.2K", "900", "1,100"])]
        rows, _ = swipe.read_reader([reader_file(self.tmp, "b", reels)])
        self.assertTrue(all(r["metric"] == "views" for r in rows))
        self.assertEqual(sorted(r["count"] for r in rows), [900, 1100, 1200, 16200])

    def test_too_few_reels_means_no_baseline_not_followers(self):
        reels = [{"url": "u1", "likes": 5000, "caption": "big one"}, {"url": "u2", "likes": 10, "caption": "small"}]
        rows, notes = swipe.read_reader([reader_file(self.tmp, "c", reels, followers=100)])
        self.assertTrue(any("fewer than 3" in n for n in notes))
        a = swipe.analyse(rows, None)
        self.assertTrue(all(r["outlier"] is None for r in a["reels"]))   # likes / followers is not a multiple

    def test_handle_and_audio_from_the_reels(self):
        path = os.path.join(self.tmp, "r.json")
        with open(path, "w", encoding="utf-8") as f:
            json.dump({"source": "kweo", "reels": [{"account": "zara.abbasi22", "url": f"u{i}", "likes": n,
                                                     "first_line": "line", "audio": "Badshah • Therapy"}
                                                    for i, n in enumerate([5, 6, 70])]}, f)
        rows, _ = swipe.read_reader([path])
        self.assertEqual({r["account"] for r in rows}, {"@zara.abbasi22"})
        self.assertEqual(rows[0]["sound"], "Badshah • Therapy")

    def test_count_parsing(self):
        self.assertEqual(swipe.count("16.2K"), 16200)
        self.assertEqual(swipe.count("1.1M"), 1100000)
        self.assertEqual(swipe.count("12,345"), 12345)
        self.assertIsNone(swipe.count("about 5k views"))
        self.assertIsNone(swipe.count(None))
        self.assertIsNone(swipe.count(True))

    def test_cli_reader_writes_viral_json(self):
        reels = [{"url": f"https://www.instagram.com/reel/R{i}/", "likes": n, "caption": f"line {i}"}
                 for i, n in enumerate([10, 12, 300])]
        f = reader_file(self.tmp, "d", reels)
        out = os.path.join(self.tmp, "acct", "swipe.md")
        r = subprocess.run([sys.executable, SWIPE, "--reader", f, "--out", out], capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stderr)
        v = json.load(open(os.path.join(self.tmp, "acct", "viral.json"), encoding="utf-8"))
        self.assertEqual(v["reels"][0]["likes"], 300)
        self.assertIn("- likes: 300", open(out, encoding="utf-8").read())


if __name__ == "__main__":
    unittest.main()
