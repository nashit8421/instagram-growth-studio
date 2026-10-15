"""Tests for direct.py. They build their own clips with ffmpeg in temp folders,
never fetch fonts and never touch ~/IGStudio."""

import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

os.environ["IG_DIRECT_NO_FETCH"] = "1"
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
import direct  # noqa: E402

HAVE_FFMPEG = bool(shutil.which("ffmpeg"))


def words(*items):
    return [{"i": k, "w": w, "start": a, "end": b} for k, (w, a, b) in enumerate(items)]


def footage(ws, dur=10.0, w=1920, h=1080, src="/x.mp4", audio=True):
    return {"source": src, "words": ws, "lines": direct.group_lines(ws), "silences": [],
            "info": {"width": w, "height": h, "fps": 30, "duration": dur, "has_audio": audio,
                     "orientation": "landscape" if w > h else "portrait"}}


WS = words(("Um,", 0.2, 0.5), ("so", 0.5, 0.8), ("trains", 2.0, 2.4), ("run", 2.4, 2.7), ("late.", 2.7, 3.2),
           ("Is", 4.0, 4.2), ("it", 4.2, 4.4), ("random?", 4.4, 5.0), ("No.", 5.4, 5.8))


class Units(unittest.TestCase):
    def test_ass_color(self):
        self.assertEqual(direct.ass_color("#FFD400"), "&H0000D4FF")
        self.assertEqual(direct.ass_color("#00000080"), "&H7F000000")
        self.assertEqual(direct.ass_color("nonsense"), "&H00FFFFFF")

    def test_refine_words_trusts_starts_and_snaps_to_pauses(self):
        ws = [{"i": 0, "w": "so", "start": 0.82, "end": 2.32}, {"i": 1, "w": "train", "start": 2.32, "end": 2.6},
              {"i": 2, "w": "late", "start": 5.98, "end": 7.28}]
        direct.refine_words(ws, [[0.96, 2.08], [5.68, 7.16]])
        self.assertEqual((ws[0]["start"], ws[0]["end"]), (0.82, 0.96))   # ends where the pause starts
        self.assertEqual(ws[1]["start"], 2.08)                            # starts where the pause ends
        self.assertLessEqual(ws[2]["end"], 5.68)                          # a start just inside a pause
        self.assertLess(ws[2]["start"], 5.68)                             # belongs to the speech before

    def test_shots_reorder_and_captions_follow_output_order(self):
        plan = {"shots": [{"id": "s1", "words": [5, 8], "role": "hook"}, {"id": "s2", "words": [2, 4]}],
                "captions": {"style": "bold-pop", "max_words": 3}}
        f = footage(WS)
        shots, dur, err = direct.resolve_shots(plan, f)
        self.assertEqual(err, [])
        self.assertEqual([s["id"] for s in shots], ["s1", "s2"])
        self.assertEqual(shots[1]["off"], shots[0]["dur"])
        cards, _ = direct.caption_cards(plan, f, shots)
        starts = [c["start"] for c in cards]
        self.assertEqual(starts, sorted(starts))
        self.assertEqual([w["text"] for w in cards[0]["words"]], ["Is", "it", "random?"])
        self.assertNotIn("Um,", [w["text"] for c in cards for w in c["words"]])   # cut words never caption
        self.assertTrue(all(c["end"] > c["start"] for c in cards))

    def test_no_blink_cards(self):
        ws = words(("one", 0.0, 0.3), ("two", 0.3, 0.6), ("three", 0.6, 0.9), ("four.", 0.9, 1.0))
        plan = {"shots": [{"id": "s1", "in": 0, "out": 1.05}], "captions": {"style": "bold-pop", "max_words": 3}}
        f = footage(ws, dur=2)
        shots, _, _ = direct.resolve_shots(plan, f)
        cards, _ = direct.caption_cards(plan, f, shots)
        self.assertEqual(len(cards), 1)
        self.assertEqual(len(cards[0]["words"]), 4)

    def test_word_pads_never_reach_far_into_neighbours(self):
        plan = {"shots": [{"id": "s1", "words": [3, 3]}]}
        shots, _, _ = direct.resolve_shots(plan, footage(WS))
        s = shots[0]
        self.assertGreaterEqual(s["a"], 2.0 + 0.6 * 0.4 - 1e-6)
        self.assertLessEqual(s["b"], 2.7)

    def test_bad_shots_are_errors(self):
        plan = {"shots": [{"id": "a", "words": [7, 99]}, {"id": "b"}, {"id": "c", "in": 1, "out": 1.1},
                          {"id": "d", "words": [0, 1], "transition": "spin"}]}
        _, _, err = direct.resolve_shots(plan, footage(WS))
        self.assertEqual(len(err), 4)

    def test_fixes_and_hidden_words(self):
        plan = {"shots": [{"id": "s1", "words": [0, 4]}], "captions": {"fixes": {"0": "", "2": "Trains"}}}
        f = footage(WS)
        shots, _, _ = direct.resolve_shots(plan, f)
        cards, _ = direct.caption_cards(plan, f, shots)
        texts = [w["text"] for c in cards for w in c["words"]]
        self.assertNotIn("Um,", texts)
        self.assertIn("Trains", texts)

    def test_a_hidden_glued_word_leaves_no_gap(self):
        ws = words(("auto", 1.0, 1.3), ("correlation", 1.3, 2.2), ("today", 2.3, 2.6))
        plan = {"shots": [{"id": "s1", "words": [0, 2]}],
                "captions": {"style": "clean", "fixes": {"0": "autocorrelation", "1": ""}}}
        f = footage(ws, dur=3)
        shots, _, _ = direct.resolve_shots(plan, f)
        cards, _ = direct.caption_cards(plan, f, shots)
        first = cards[0]["words"][0]
        self.assertEqual(first["text"], "autocorrelation")
        self.assertGreaterEqual(first["end"] - first["start"], 1.1)

    def test_fit_lines_breaks_then_shrinks(self):
        lines, size = direct.fit_lines("SHORT", 100, "Anton", 900)
        self.assertEqual((lines, size), (["SHORT"], 100))
        lines, size = direct.fit_lines("WHY IS YOUR TRAIN ALWAYS LATE EVERY SINGLE DAY", 110, "Anton", 900)
        self.assertEqual(len(lines), 2)
        lines, size = direct.fit_lines("SUPERCALIFRAGILISTICEXPIALIDOCIOUSLY", 140, "Anton", 600)
        self.assertLess(size, 140)

    def test_ass_has_karaoke_steps_and_frame_one_hook(self):
        plan = {"shots": [{"id": "s1", "words": [5, 8], "role": "hook"}], "captions": {"style": "bold-pop"},
                "text_overlays": [{"text": "IS IT RANDOM? 📊", "style": "hook", "start": 0, "end": 2}]}
        f = footage(WS)
        shots, dur, _ = direct.resolve_shots(plan, f)
        cards, spec = direct.caption_cards(plan, f, shots)
        ovs, _ = direct.overlay_list(plan, dur)
        doc = direct.ass_document(cards, spec, ovs)
        self.assertEqual(doc.count(",Caption,"), 4)              # one event per spoken word
        hook = [l for l in doc.splitlines() if ",Box," in l][0]
        self.assertIn("\\fad(0,80)", hook)                       # no fade-in on frame 1
        self.assertNotIn("📊", hook)

    def test_checklist_flags_a_weak_edit(self):
        ws = words(*[(f"w{k}", k * 1.0, k * 1.0 + 0.5) for k in range(20)])
        plan = {"shots": [{"id": "s1", "words": [0, 19], "role": "value"}],
                "captions": {"style": "clean", "max_words": 8, "size": 50},
                "text_overlays": [{"text": "A B", "style": "cta"}, {"text": "C", "style": "cta", "start": 3}]}
        f = footage(ws, dur=21)
        shots, dur, _ = direct.resolve_shots(plan, f)
        cards, _ = direct.caption_cards(plan, f, shots)
        ovs, _ = direct.overlay_list(plan, dur)
        lint = direct.checklist(plan, f, shots, dur, cards, ovs)
        failed = {i["key"] for i in lint["items"] if not i["ok"]}
        for k in ("hook_text", "hook_shot", "pacing", "cut_rate", "caption_size", "caption_words", "one_ask", "loop"):
            self.assertIn(k, failed)
        self.assertLess(lint["score"], 60)
        self.assertTrue(all(i["fix"] for i in lint["items"] if not i["ok"]))

    def test_merge_reads_sections(self):
        d = Path(tempfile.mkdtemp())
        try:
            direct.write_json(d / "footage.json", footage(WS))
            direct.write_json(d / "brief.json", {"mood": "energetic"})
            direct.write_json(d / "cuts.json", {"shots": [{"id": "s1", "words": [5, 8]}], "why": "w"})
            direct.write_json(d / "captions.json", {"captions": {"style": "clean"}, "text_overlays": []})
            direct.write_json(d / "look.json", {"grade": "warm", "cover": {"at": 1}})
            plan = direct.merge(d)
            self.assertEqual(plan["brief"]["mood"], "energetic")
            self.assertEqual(plan["look"]["grade"], "warm")
            self.assertEqual(plan["cover"], {"at": 1})
            self.assertEqual(plan["sound"], {})
        finally:
            shutil.rmtree(d)


@unittest.skipUnless(HAVE_FFMPEG, "ffmpeg not installed")
class EndToEnd(unittest.TestCase):
    """A real 6 s clip -> plan -> storyboard -> render. No Whisper: the words are given."""

    @classmethod
    def setUpClass(cls):
        cls.dir = Path(tempfile.mkdtemp(prefix="ig-direct-test-"))
        cls.src = cls.dir / "raw.mp4"
        subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
                        "-f", "lavfi", "-i", "testsrc2=s=1280x720:r=30:d=6",
                        "-f", "lavfi", "-i", "sine=f=220:sample_rate=48000:d=6",
                        "-c:v", "libx264", "-preset", "ultrafast", "-c:a", "aac", "-shortest", str(cls.src)],
                       check=True)
        cls.work = cls.dir / "edit"
        cls.work.mkdir()
        ws = words(("Trains", 0.3, 0.8), ("are", 0.8, 1.0), ("always", 1.0, 1.5), ("late.", 1.5, 2.0),
                   ("Why?", 2.6, 3.1), ("Autocorrelation.", 3.6, 4.6), ("Save", 4.9, 5.2), ("this.", 5.2, 5.6))
        f = footage(ws, dur=6.0, w=1280, h=720, src=str(cls.src))
        f["frames"], f["sheets"] = [], []
        direct.write_json(cls.work / "footage.json", f)
        direct.write_json(cls.work / "brief.json", {"concept": "test", "mood": "energetic", "loop": "why? again"})
        direct.write_json(cls.work / "cuts.json", {"shots": [
            {"id": "s1", "words": [4, 4], "role": "hook", "zoom": [1.1, 1.2], "focus": [0.6, 0.5]},
            {"id": "s2", "words": [0, 3], "role": "setup", "transition": "punch"},
            {"id": "s3", "words": [5, 5], "role": "payoff", "transition": "flash", "zoom": 1.15},
            {"id": "s4", "words": [6, 7], "role": "loop"}]})
        direct.write_json(cls.work / "captions.json", {
            "captions": {"style": "bold-pop", "emphasis": ["autocorrelation."]},
            "text_overlays": [{"text": "WHY ARE TRAINS LATE?", "style": "hook", "start": 0, "end": 1.5}]})
        direct.write_json(cls.work / "look.json", {"grade": "punchy", "vignette": True,
                                                   "progress_bar": {"color": "#FFD400"}, "cover": {"at": 0.4}})
        direct.write_json(cls.work / "sound.json", {"sfx": {"cuts": "whoosh", "volume": 0.3}, "brief": "beat"})
        direct.merge(cls.work)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.dir, ignore_errors=True)

    def probe(self, path):
        r = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "stream=codec_type,width,height",
                            "-show_entries", "format=duration", "-of", "json", str(path)],
                           capture_output=True, text=True, check=True)
        return json.loads(r.stdout)

    def test_1_storyboard(self):
        d = direct.storyboard(self.work)
        self.assertEqual(len(d["panels"]), 5)                     # frame 0 + one per shot
        for p in d["panels"]:
            self.assertTrue((self.work / p["image"]).exists(), p)
        html = (self.work / "storyboard.html").read_text()
        self.assertIn("storyboard/frame_01.jpg", html)
        self.assertIn("checklist", html)
        self.assertTrue((self.work / "storyboard.md").exists())

    def test_2_render(self):
        rep = direct.render(self.work)
        info = self.probe(rep["video"])
        v = [s for s in info["streams"] if s["codec_type"] == "video"][0]
        self.assertEqual((v["width"], v["height"]), (1080, 1920))
        self.assertTrue(any(s["codec_type"] == "audio" for s in info["streams"]))
        self.assertAlmostEqual(float(info["format"]["duration"]), rep["length"], delta=0.15)
        self.assertTrue(Path(rep["cover"]).exists())
        self.assertTrue(rep["checks"])

    def test_3_cli_check_and_bad_plan(self):
        out = __import__("io").StringIO()
        self.assertEqual(direct.main(["check", str(self.work), "--json"], out=out), 0)
        self.assertIn("score", json.loads(out.getvalue()))
        bad = self.dir / "bad"
        shutil.copytree(self.work, bad)
        direct.write_json(bad / "cuts.json", {"shots": [{"id": "x", "words": [0, 50]}]})
        direct.merge(bad)
        out = __import__("io").StringIO()
        self.assertEqual(direct.main(["render", str(bad), "--json"], out=out), 1)
        self.assertIn("fix the plan first", json.loads(out.getvalue())["error"])


if __name__ == "__main__":
    unittest.main()
