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


if __name__ == "__main__":
    unittest.main()
