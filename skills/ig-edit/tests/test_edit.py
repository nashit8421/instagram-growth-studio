"""Tests for edit.py and cover.py. They drive the real ffmpeg on short test
clips made here (testsrc2 + sine, with anullsrc gaps for the silences) and
are skipped when ffmpeg is not installed.

Run from the skill folder:
  python3 -m unittest discover -s tests

Every test points IG_DATA_DIR and IG_HOME at temp dirs. Nothing touches
~/IGStudio or ~/.claude/skills.
"""

import contextlib
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

HERE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(HERE))

os.environ["IG_DATA_DIR"] = tempfile.mkdtemp(prefix="igedit-import-")
os.environ["IG_HOME"] = tempfile.mkdtemp(prefix="igedit-home-")

import cover  # noqa: E402
import edit  # noqa: E402

try:
    FFMPEG = cover.tool("ffmpeg")
    FFPROBE = cover.tool("ffprobe")
except cover.CoverError:
    FFMPEG = FFPROBE = None

# tone 2s, gap 1.5s, tone 2s, gap 1.5s, tone 2s = 9s, speech 6s.
PATTERN = [("tone", 2.0), ("gap", 1.5), ("tone", 2.0), ("gap", 1.5), ("tone", 2.0)]


def make_clip(path, pattern=PATTERN, size="640x360", audio=True):
    total = sum(d for _, d in pattern)
    cmd = [FFMPEG, "-hide_banner", "-loglevel", "error", "-y",
           "-f", "lavfi", "-i", f"testsrc2=size={size}:rate=30:duration={total}"]
    if audio:
        for i, (kind, d) in enumerate(pattern):
            src = (f"sine=f={440 + 110 * i}:r=48000:d={d}" if kind == "tone"
                   else f"anullsrc=r=48000:cl=mono:d={d}")
            cmd += ["-f", "lavfi", "-i", src]
        n = len(pattern)
        cmd += ["-filter_complex", "".join(f"[{i + 1}:a]" for i in range(n))
                + f"concat=n={n}:v=0:a=1[a]", "-map", "0:v", "-map", "[a]", "-c:a", "aac"]
    cmd += ["-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p", str(path)]
    subprocess.run(cmd, check=True)
    return path


def streams(path):
    r = subprocess.run([FFPROBE, "-v", "error", "-print_format", "json", "-show_streams",
                        "-show_format", str(path)], capture_output=True, text=True, check=True)
    return json.loads(r.stdout)


def run_edit(*argv):
    buf, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stderr(err):
        code = edit.main([*map(str, argv), "--preset", "superfast"], out=buf)
    return code, buf.getvalue(), err.getvalue()


class Pure(unittest.TestCase):
    """No ffmpeg needed."""

    def test_parse_time(self):
        self.assertEqual(edit.parse_time("00:14:20"), 860)
        self.assertEqual(edit.parse_time("1:30.5"), 90.5)
        self.assertEqual(edit.parse_time("12"), 12)
        with self.assertRaises(edit.EditError):
            edit.parse_time("ten")

    def test_silences_to_segments(self):
        stderr = ("[silencedetect @ 0x1] silence_start: 2.0\n"
                  "[silencedetect @ 0x1] silence_end: 3.5 | silence_duration: 1.5\n"
                  "[silencedetect @ 0x1] silence_start: 5.5\n")
        sil = edit.parse_silences(stderr, 9.0)
        self.assertEqual(sil, [(2.0, 3.5), (5.5, 9.0)])
        runs = edit.speech_runs(sil, 9.0)
        self.assertEqual(runs, [(0.0, 2.0), (3.5, 5.5)])
        self.assertEqual(edit.keep_segments(runs, 9.0, 0.12), [(0.0, 2.12), (3.38, 5.62)])
        # Gaps smaller than MERGE_GAP after padding are not worth a cut.
        self.assertEqual(edit.keep_segments([(0, 1), (1.4, 2)], 3, 0.12), [(0.0, 2.12)])

    def test_rotation_makes_portrait(self):
        info = {"format": {"duration": "4.0"},
                "streams": [{"codec_type": "video", "width": 1920, "height": 1080,
                             "avg_frame_rate": "30000/1001",
                             "side_data_list": [{"rotation": -90}]},
                            {"codec_type": "audio"}]}
        p = edit.parse_probe(info)
        self.assertEqual((p["width"], p["height"], p["rotation"]), (1080, 1920, -90))
        self.assertAlmostEqual(p["fps"], 29.97, places=2)
        self.assertTrue(p["has_audio"])

    def test_timeline_and_srt_remap(self):
        tl = edit.Timeline([(0.0, 2.0), (4.0, 6.0)])
        self.assertEqual(tl.duration, 4.0)
        self.assertEqual(tl.map(5.0), 3.0)
        self.assertEqual(tl.map(3.0), 2.0)         # inside the cut
        self.assertIsNone(tl.interval(2.5, 3.5))   # wholly cut
        cues = edit.parse_srt("1\n00:00:04,500 --> 00:00:05,500\n<i>Hello there</i>\n")
        cards = edit.cards_from_cues(cues, tl)
        self.assertEqual(cards[0]["text"], "Hello there")
        self.assertEqual((cards[0]["start"], cards[0]["end"]), (2.5, 3.5))

    def test_cards_max_six_words(self):
        for line in ("Here is the template, and it is boringly simple.",
                     "one two three four five six seven eight nine ten eleven twelve thirteen"):
            for c in edit.split_words(line):
                self.assertLessEqual(len(c.split()), 6)
        self.assertEqual(edit.split_words("Here is the template, and it is boringly simple."),
                         ["Here is the template,", "and it is boringly simple."])

    def test_word_grouping(self):
        tl = edit.Timeline([(0.0, 10.0)])
        words = [{"word": w, "start": i * 0.3, "end": i * 0.3 + 0.25}
                 for i, w in enumerate("I used to spend five hours. Now it takes twenty minutes "
                                       "with one simple boring template".split())]
        cards = edit.cards_from_words(words, tl)
        self.assertEqual(cards[0]["text"], "I used to spend five hours.")
        self.assertTrue(all(len(c["text"].split()) <= 6 for c in cards))

    def test_script_lines_match_runs(self):
        cards, how = edit.cards_from_script(["First line here.", "Second one."],
                                            [(0.1, 2.0), (2.3, 4.0)], 4.2)
        self.assertIn("matched", how)
        self.assertEqual(cards[1]["start"], 2.3)

    def test_ass_safe_zone(self):
        doc = edit.ass_document([{"start": 0, "end": 1, "text": "hi"}], "5 HOURS -> 20 MIN", 2.5)
        self.assertIn("PlayResX: 1080", doc)
        self.assertIn("→", doc)
        cap = next(l for l in doc.splitlines() if l.startswith("Style: Caption"))
        f = cap.split(",")
        margin_r, margin_v = int(f[-3]), int(f[-2])
        self.assertGreaterEqual(margin_r, 230)
        self.assertGreaterEqual(margin_v, 1920 - 1440)
        hook = next(l for l in doc.splitlines() if l.startswith("Style: Hook")).split(",")
        self.assertGreaterEqual(int(hook[-2]), 230)
        self.assertIn("Hook,,0,0,0,,5 HOURS", doc)

    def test_data_dir_resolver(self):
        home = Path(tempfile.mkdtemp())
        env = {"IG_HOME": str(home)}
        with mock.patch.dict(os.environ, env):
            os.environ.pop("IG_DATA_DIR", None)
            self.assertEqual(edit.data_dir(), home)
            (home / "active-account").write_text("@sam\n")
            self.assertEqual(edit.data_dir(), home)            # folder missing
            (home / "accounts" / "sam").mkdir(parents=True)
            self.assertEqual(edit.data_dir(), home / "accounts" / "sam")
            os.environ["IG_DATA_DIR"] = str(home / "x")
            self.assertEqual(edit.data_dir(), home / "x")
        shutil.rmtree(home)

    def test_cap_prefers_a_pause(self):
        segs, how = edit.cap_segments([(0.0, 100.0)], 90, [(0, 40), (41, 85), (86, 100)], 0.12)
        self.assertEqual(segs, [(0.0, 85.12)])
        self.assertIn("pause", how)


@unittest.skipUnless(FFMPEG, "ffmpeg not installed")
class WithFFmpeg(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.tmp = Path(tempfile.mkdtemp(prefix="igedit-"))
        cls.land = make_clip(cls.tmp / "land.mp4")
        cls.script = cls.tmp / "script.txt"
        cls.script.write_text("Proposals took five hours.\nNow twenty minutes.\nHere is how.\n")

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def setUp(self):
        self.out = Path(tempfile.mkdtemp(dir=self.tmp))
        p = mock.patch.object(edit, "find_transcriber", return_value=None)
        p.start()
        self.addCleanup(p.stop)

    def test_probe(self):
        p = edit.probe(self.land)
        self.assertEqual((p["width"], p["height"]), (640, 360))
        self.assertAlmostEqual(p["duration"], 9.0, delta=0.1)
        self.assertEqual(p["fps"], 30)
        self.assertTrue(p["has_audio"])
        mute = make_clip(self.out / "mute.mp4", [("gap", 2.0)], audio=False)
        self.assertFalse(edit.probe(mute)["has_audio"])

    def test_full_edit_cuts_crops_and_burns(self):
        reel = self.out / "reel.mp4"
        code, text, err = run_edit(self.land, "--out", reel, "--cut-silence",
                                   "--script", self.script, "--hook-text", "5 HOURS -> 20 MIN",
                                   "--json", "--cover-at", "1.0")
        self.assertEqual(code, 0, err)
        r = json.loads(text)
        # 3 speech runs of 2s, each padded 0.12s at the cut sides: 6 + 4 * 0.12.
        self.assertAlmostEqual(r["output_duration"], 6.48, delta=0.15)
        self.assertEqual(r["cuts"], 2)
        self.assertAlmostEqual(r["seconds_cut"], 2.52, delta=0.15)

        info = streams(reel)
        v = next(s for s in info["streams"] if s["codec_type"] == "video")
        a = next(s for s in info["streams"] if s["codec_type"] == "audio")
        self.assertEqual((v["width"], v["height"]), (1080, 1920))
        self.assertEqual(v["codec_name"], "h264")
        self.assertEqual(v["profile"], "High")
        self.assertEqual(v["pix_fmt"], "yuv420p")
        self.assertEqual(v["avg_frame_rate"], "30/1")
        self.assertEqual(a["codec_name"], "aac")
        head = reel.read_bytes()[:4096]
        self.assertIn(b"moov", head, "faststart: moov atom should sit before mdat")

        # Captions: the SRT and ASS were written and ffmpeg burned the ASS.
        self.assertEqual(r["captions"]["source"], "script")
        self.assertTrue(r["captions"]["burned"])
        self.assertIn("ass=captions.ass", r["commands"][0])
        srt = edit.parse_srt(reel.with_suffix(".srt").read_text())
        self.assertGreaterEqual(len(srt), 3)
        self.assertTrue(all(len(c["text"].split()) <= 6 for c in srt))
        ass = reel.with_suffix(".ass").read_text()
        self.assertIn("Style: Hook", ass)
        self.assertIn("5 HOURS → 20 MIN", ass)
        self.assertEqual(r["crop"], "centre crop")
        self.assertTrue((self.out / "edit-report.json").exists())
        self.assertEqual(len(r["check_frames"]), 3)
        self.assertTrue(Path(r["cover"]).exists())
        self.assertTrue(any("approximate" in w or "timed from the script" in w
                            for w in r["warnings"]))
        self.assertTrue(any("under 7s" in w for w in r["warnings"]))

    def test_no_cut_keeps_length_and_flags_dead_air(self):
        clip = make_clip(self.out / "late.mp4", [("gap", 1.2), ("tone", 2.0), ("gap", 0.3)])
        code, text, err = run_edit(clip, "--out", self.out / "r.mp4", "--json",
                                   "--no-check-frames", "--captions", "none")
        self.assertEqual(code, 0, err)
        r = json.loads(text)
        self.assertAlmostEqual(r["output_duration"], 3.5, delta=0.1)
        self.assertEqual(r["cuts"], 0)
        self.assertTrue(any("dead air before hook" in w for w in r["warnings"]))

    def test_landscape_blur_fit_dry_run(self):
        reel = self.out / "blur.mp4"
        code, text, err = run_edit(self.land, "--out", reel, "--crop", "none", "--dry-run")
        self.assertEqual(code, 0, err)
        self.assertIn("fit on blurred background", text)
        self.assertIn("boxblur", text)
        self.assertIn("Nothing was encoded", text)
        self.assertFalse(reel.exists())
        self.assertFalse((self.out / "edit-report.json").exists())

    def test_dry_run_json_plan(self):
        code, text, err = run_edit(self.land, "--out", self.out / "x.mp4", "--cut-silence",
                                   "--dry-run", "--json")
        self.assertEqual(code, 0, err)
        r = json.loads(text)
        self.assertTrue(r["dry_run"])
        self.assertIn("silencedetect", r["commands"][1])
        self.assertIn("libx264", r["commands"][0])
        self.assertEqual(len(r["segments"]), 3)
        self.assertFalse((self.out / "x.mp4").exists())

    def test_clip_extraction(self):
        reel = self.out / "clip.mp4"
        code, text, err = run_edit(self.land, "--out", reel, "--start", "00:00:02",
                                   "--end", "00:00:06", "--json", "--no-check-frames",
                                   "--captions", "none")
        self.assertEqual(code, 0, err)
        r = json.loads(text)
        self.assertEqual(r["window"], {"start": 2.0, "end": 6.0, "length": 4.0})
        self.assertAlmostEqual(edit.probe(reel)["duration"], 4.0, delta=0.15)
        # With cutting on, the 1.5s gap at 2.0-3.5 goes.
        code, text, _ = run_edit(self.land, "--out", self.out / "clip2.mp4", "--start", "2",
                                 "--end", "6", "--cut-silence", "--json", "--dry-run")
        self.assertAlmostEqual(json.loads(text)["output_duration"], 2.27, delta=0.1)

    def test_srt_input_is_remapped(self):
        srt = self.out / "subs.srt"
        srt.write_text("1\n00:00:03,600 --> 00:00:05,400\nSecond sentence here\n")
        code, text, err = run_edit(self.land, "--out", self.out / "s.mp4", "--cut-silence",
                                   "--srt", srt, "--json", "--dry-run")
        self.assertEqual(code, 0, err)
        r = json.loads(text)
        self.assertEqual(r["captions"]["source"], "srt")
        card = r["caption_cards"][0]
        self.assertAlmostEqual(card["start"], 2.12 + 0.22, delta=0.1)

    def test_missing_whisper_path(self):
        code, text, err = run_edit(self.land, "--out", self.out / "w.mp4", "--json", "--dry-run")
        self.assertEqual(code, 0, err)
        r = json.loads(text)
        self.assertEqual(r["captions"]["source"], "none")
        self.assertTrue(any("brew install whisper-cpp" in n for n in r["notes"]))
        self.assertTrue(any("no captions" in w for w in r["warnings"]))
        # The hint points at the temp data dir, never the real one.
        self.assertNotIn(str(Path.home() / "IGStudio"), " ".join(r["notes"]))

    def test_no_audio_input(self):
        mute = make_clip(self.out / "mute.mp4", [("gap", 8.0)], audio=False)
        code, text, err = run_edit(mute, "--out", self.out / "m.mp4", "--cut-silence",
                                   "--json", "--no-check-frames", "--captions", "none")
        self.assertEqual(code, 0, err)
        r = json.loads(text)
        self.assertTrue(any("no audio track" in w for w in r["warnings"]))
        a = [s for s in streams(self.out / "m.mp4")["streams"] if s["codec_type"] == "audio"]
        self.assertEqual(len(a), 1, "a silent AAC track is added")

    def test_cover_cli(self):
        reel = self.out / "c.mp4"
        run_edit(self.land, "--out", reel, "--no-check-frames", "--captions", "none")
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            code = cover.main([str(reel), "--at", "1.2", "--out", str(self.out / "cover.jpg"),
                               "--json"])
        self.assertEqual(code, 0)
        res = json.loads(buf.getvalue())
        info = streams(res["cover"])["streams"][0]
        self.assertEqual((info["width"], info["height"]), (1080, 1920))

    def test_bad_inputs(self):
        code, _, err = run_edit(self.tmp / "nope.mov", "--out", self.out / "a.mp4")
        self.assertEqual(code, 1)
        self.assertIn("not found", err)
        code, _, err = run_edit(self.land, "--out", self.out / "a.mp4", "--start", "20")
        self.assertEqual(code, 1)
        self.assertIn("past the end", err)


if __name__ == "__main__":
    unittest.main()
