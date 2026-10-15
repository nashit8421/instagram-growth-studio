"""Tests for render.py. The render tests drive real headless Chrome and are
skipped when no Chrome or Chromium is installed.

Run from the skill folder:
  python3 -m unittest discover -s tests
"""

import contextlib
import io
import json
import os
import struct
import sys
import tempfile
import unittest
import zlib
from pathlib import Path

HERE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(HERE))

import render  # noqa: E402

try:
    CHROME = render.find_chrome()
except render.SpecError:
    CHROME = None


def read_png_pixel(path, x, y):
    """Minimal stdlib PNG decoder: 8-bit RGB or RGBA, not interlaced."""
    data = Path(path).read_bytes()
    pos, idat = 8, b""
    width = height = ctype = None
    while pos < len(data):
        length, tag = struct.unpack(">I4s", data[pos:pos + 8])
        chunk = data[pos + 8:pos + 8 + length]
        if tag == b"IHDR":
            width, height, depth, ctype, _, _, interlace = struct.unpack(">IIBBBBB", chunk)
            assert depth == 8 and interlace == 0, "unsupported PNG"
        elif tag == b"IDAT":
            idat += chunk
        pos += 12 + length
    bpp = {2: 3, 6: 4}[ctype]
    raw = zlib.decompress(idat)
    stride = width * bpp
    prev = bytearray(stride)
    for row in range(y + 1):
        f = raw[row * (stride + 1)]
        line = bytearray(raw[row * (stride + 1) + 1:(row + 1) * (stride + 1)])
        for i in range(stride):
            a = line[i - bpp] if i >= bpp else 0
            b = prev[i]
            c = prev[i - bpp] if i >= bpp else 0
            if f == 1:
                line[i] = (line[i] + a) & 255
            elif f == 2:
                line[i] = (line[i] + b) & 255
            elif f == 3:
                line[i] = (line[i] + (a + b) // 2) & 255
            elif f == 4:
                p = a + b - c
                pa, pb, pc = abs(p - a), abs(p - b), abs(p - c)
                pr = a if pa <= pb and pa <= pc else (b if pb <= pc else c)
                line[i] = (line[i] + pr) & 255
        prev = line
    return tuple(prev[x * bpp:x * bpp + 3])


def close(a, b, tol=6):
    return all(abs(i - j) <= tol for i, j in zip(a, b))


class TempData(unittest.TestCase):
    """Every test gets its own IG_DATA_DIR so nothing touches ~/.claude."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="ig-render-test-")
        self.dir = Path(self.tmp.name)
        self._old = os.environ.get("IG_DATA_DIR")
        os.environ["IG_DATA_DIR"] = str(self.dir / "data")

    def tearDown(self):
        if self._old is None:
            os.environ.pop("IG_DATA_DIR", None)
        else:
            os.environ["IG_DATA_DIR"] = self._old
        self.tmp.cleanup()

    def spec(self, obj, name="spec.json"):
        p = self.dir / name
        p.write_text(json.dumps(obj))
        return p

    def run_cli(self, *args):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = render.main([str(a) for a in args])
        return code, out.getvalue(), err.getvalue()


class TestPure(TempData):

    def test_contrast_ratio(self):
        self.assertAlmostEqual(render.contrast("#000000", "#FFFFFF"), 21.0, places=1)
        self.assertAlmostEqual(render.contrast("#fff", "#fff"), 1.0, places=2)

    def test_low_contrast_brand_warns(self):
        b = self.dir / "brand.json"
        b.write_text(json.dumps({"bg": "#FFFFFF", "fg": "#BBBBBB"}))
        _, _, warnings = render.load_brand(str(b))
        self.assertTrue(any("4.5:1" in w for w in warnings))

    def test_brand_from_data_dir(self):
        d = Path(os.environ["IG_DATA_DIR"])
        d.mkdir(parents=True)
        (d / "brand.json").write_text(json.dumps({"accent": "#0055FF", "handle": "@me"}))
        brand, source, _ = render.load_brand()
        self.assertEqual(brand["accent"], "#0055FF")
        self.assertIn(str(d), source)

    def test_default_brand_when_none(self):
        brand, source, warnings = render.load_brand()
        self.assertEqual(source, "built-in default")
        self.assertEqual(warnings, [])

    def test_bad_colour_rejected(self):
        b = self.dir / "brand.json"
        b.write_text(json.dumps({"bg": "red; }</style><script>"}))
        with self.assertRaises(render.SpecError):
            render.load_brand(str(b))

    def test_font_name_cannot_break_css(self):
        stack = render.font_stack("Evil}</style><script>alert(1)</script>", "sans-serif")
        self.assertNotIn("<", stack)
        self.assertNotIn("}", stack)

    def test_escaping_in_html(self):
        warnings = []
        doc, _ = render.carousel_slide_html({"title": "<script>alert(1)</script>", "body": "a & b"},
                                            1, 6, render.DEFAULT_BRAND, "@me", warnings)
        self.assertIn("&lt;script&gt;alert(1)&lt;/script&gt;", doc)
        self.assertIn("a &amp; b", doc)
        self.assertNotIn("<script>alert(1)", doc)

    def test_long_title_shrinks_and_warns(self):
        short_w, long_w = [], []
        doc_s, _ = render.carousel_slide_html({"title": "Short"}, 2, 6, render.DEFAULT_BRAND, "", short_w)
        long_title = "This headline goes on and on well past anything a slide should carry " * 2
        doc_l, _ = render.carousel_slide_html({"title": long_title}, 2, 6, render.DEFAULT_BRAND, "", long_w)
        size = lambda d: int(d.split('data-shrink style="font-size:')[1].split("px")[0])
        self.assertLess(size(doc_l), size(doc_s))
        self.assertGreaterEqual(size(doc_l), render.MIN_FONT)
        self.assertEqual(short_w, [])
        self.assertTrue(any("split this slide" in w.lower() for w in long_w))

    def test_story_sticker_placeholder(self):
        doc, _ = render.story_frame_html({"title": "Q?", "sticker": "poll: Yes / Not yet"},
                                         0, render.DEFAULT_BRAND, [])
        self.assertIn("add POLL sticker here", doc)
        self.assertIn("dashed", doc)

    def test_too_many_slides_is_error(self):
        spec = self.spec({"kind": "carousel", "slides": [{"title": f"S{i}"} for i in range(21)]})
        code, _, err = self.run_cli(spec, "--out", self.dir / "out")
        self.assertEqual(code, 2)
        self.assertIn("20", err)

    def test_missing_chrome_is_clear(self):
        old = os.environ.get("CHROME_PATH")
        os.environ["CHROME_PATH"] = str(self.dir / "no-such-chrome")
        try:
            spec = self.spec({"kind": "carousel", "slides": [{"title": "A"}]})
            code, _, err = self.run_cli(spec, "--out", self.dir / "out")
        finally:
            if old is None:
                os.environ.pop("CHROME_PATH", None)
            else:
                os.environ["CHROME_PATH"] = old
        self.assertEqual(code, 2)
        self.assertIn("CHROME_PATH", err)

    def test_png_size_reader(self):
        p = self.dir / "x.png"
        ihdr = struct.pack(">IIBBBBB", 1080, 1350, 8, 2, 0, 0, 0)
        p.write_bytes(b"\x89PNG\r\n\x1a\n" + struct.pack(">I", 13) + b"IHDR" + ihdr + b"\0\0\0\0")
        self.assertEqual(render.png_size(p), (1080, 1350))


@unittest.skipUnless(CHROME, "Chrome or Chromium not installed")
class TestChromeRender(TempData):

    def setUp(self):
        super().setUp()
        os.environ.pop("CHROME_PATH", None)

    def test_carousel_render(self):
        evil = "<script>document.documentElement.style.background='#ff0000';" \
               "document.body.style.background='#ff0000'</script>"
        slides = [{"role": "cover", "title": "THE $18,000 CLAUSE", "body": "One line."},
                  {"title": evil, "body": "Escaped, not run."},
                  {"title": "This title is far too long for one slide and keeps going until "
                            "it has to shrink a lot to fit inside the box " * 2},
                  {"title": "Three", "body": "Body."},
                  {"role": "recap", "title": "Recap", "list": ["One", "Two", "Three"]},
                  {"role": "cta", "title": "Comment WORD", "body": "I will send it."}]
        spec = self.spec({"kind": "carousel", "handle": "@test", "alt": "Cover alt", "slides": slides})
        out = self.dir / "out"
        code, stdout, err = self.run_cli(spec, "--out", out)
        self.assertEqual(code, 0, err)
        for i in range(1, 7):
            self.assertEqual(render.png_size(out / f"slide-{i:02d}.png"), (1080, 1350))
        self.assertTrue((out / "grid-preview.png").exists())
        self.assertGreater(render.png_size(out / "grid-preview.png")[0], 1080)
        alt = (out / "alt-text.txt").read_text()
        self.assertIn("Cover alt", alt)
        self.assertIn("<script>", alt)   # plain text file: the literal title
        bg = render.parse_hex(render.DEFAULT_BRAND["bg"])
        # Script in the title did not run: background is still the brand bg,
        # top-left and bottom-right, which also proves the page fills the PNG.
        self.assertTrue(close(read_png_pixel(out / "slide-02.png", 4, 4), bg))
        self.assertTrue(close(read_png_pixel(out / "slide-02.png", 1075, 1345), bg))
        self.assertIn("shrank", stdout)
        self.assertIn("1080x1350", stdout)
        # No HTML left behind without --keep-html.
        self.assertEqual(list(out.glob("*.html")), [])

    def test_story_render(self):
        spec = self.spec({"kind": "story", "frames": [
            {"title": "Third refund request this year.", "note": "selfie"},
            {"title": "Burned by a late approval?", "sticker": "poll: Yes / Not yet"}]})
        out = self.dir / "story"
        code, stdout, err = self.run_cli(spec, "--out", out, "--keep-html")
        self.assertEqual(code, 0, err)
        self.assertEqual(render.png_size(out / "frame-01.png"), (1080, 1920))
        self.assertEqual(render.png_size(out / "frame-02.png"), (1080, 1920))
        self.assertTrue((out / "frame-02.html").exists())
        self.assertIn("add POLL sticker here", (out / "frame-02.html").read_text())
        self.assertIn("poll sticker", stdout)
        self.assertFalse((out / "grid-preview.png").exists())

    def test_examples_render(self):
        for name in ("carousel", "story"):
            out = self.dir / name
            code, stdout, err = self.run_cli(HERE / "examples" / f"{name}.json", "--out", out,
                                             "--brand", HERE / "brand.example.json")
            self.assertEqual(code, 0, err)
            self.assertIn("no warnings", stdout)


class TestAccountResolution(unittest.TestCase):
    """brand.json comes from the active account's folder (ig-account rule)."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="ig-render-home-")
        self.home = Path(self.tmp.name)
        self._env = {k: os.environ.get(k) for k in ("IG_HOME", "IG_DATA_DIR")}
        os.environ["IG_HOME"] = str(self.home)
        os.environ.pop("IG_DATA_DIR", None)
        (self.home / "brand.json").write_text(json.dumps({"accent": "#111111"}))
        acme = self.home / "accounts" / "acme"
        acme.mkdir(parents=True)
        (acme / "brand.json").write_text(json.dumps({"accent": "#0055FF"}))

    def tearDown(self):
        for k, v in self._env.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        self.tmp.cleanup()

    def use(self, text):
        (self.home / "active-account").write_text(text)

    def test_single_account(self):
        self.assertEqual(render.data_dir(), self.home)
        self.assertEqual(render.load_brand()[0]["accent"], "#111111")

    def test_active_account_brand(self):
        self.use("@Acme\n")
        self.assertEqual(render.data_dir(), self.home / "accounts" / "acme")
        brand, source, _ = render.load_brand()
        self.assertEqual(brand["accent"], "#0055FF")
        self.assertIn("accounts", source)

    def test_active_without_folder_falls_back(self):
        self.use("ghost")
        self.assertEqual(render.data_dir(), self.home)

    def test_active_account_without_brand_uses_default(self):
        (self.home / "accounts" / "bare").mkdir()
        self.use("bare")
        self.assertEqual(render.load_brand()[1], "built-in default")

    def test_ig_data_dir_wins(self):
        self.use("acme")
        os.environ["IG_DATA_DIR"] = str(self.home / "override")
        self.assertEqual(render.data_dir(), self.home / "override")


if __name__ == "__main__":
    unittest.main()
