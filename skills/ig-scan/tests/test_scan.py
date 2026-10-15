"""Tests for scan.py. Stdlib only, no network.

Run from the skill folder:  python3 -m unittest discover -s tests
Every test points IG_HOME and IG_DATA_DIR at a fresh temp dir. The real
~/.claude/instagram is never touched.
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
import urllib.error
import zipfile
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
SKILL = os.path.dirname(HERE)
sys.path.insert(0, SKILL)
sys.path.insert(0, HERE)

import scan  # noqa: E402
from synth import make_captured  # noqa: E402

TODAY = dt.date(2026, 10, 15)
TOKEN = "IGAAsecretTOKEN123xyz"


def _read(path):
    with open(path, encoding="utf-8") as f:
        return f.read()


def _write(path, text):
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)


def jload(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


class Temp(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="ig-scan-test-")
        self.data = os.path.join(self.tmp, "data")
        os.makedirs(self.data)
        self._env = {k: os.environ.get(k) for k in ("IG_HOME", "IG_DATA_DIR", "IG_ACCESS_TOKEN")}
        os.environ["IG_HOME"] = os.path.join(self.tmp, "home")
        os.environ["IG_DATA_DIR"] = self.data
        os.environ.pop("IG_ACCESS_TOKEN", None)

    def tearDown(self):
        for k, v in self._env.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        shutil.rmtree(self.tmp, ignore_errors=True)

    def cli(self, *argv):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = scan.main(list(argv))
        return code, out.getvalue(), err.getvalue()

    def write(self, name, obj):
        path = os.path.join(self.tmp, name)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(obj, f, ensure_ascii=False)
        return path

    def ingest_synth(self, **kw):
        path = self.write("captured.json", make_captured(**kw))
        code, out, err = self.cli("ingest", "--captured", path)
        self.assertEqual(code, 0, err)
        return path

    def analysis(self):
        code, out, err = self.cli("analyze", "--today", TODAY.isoformat(), "--json")
        self.assertEqual(code, 0, err)
        return json.loads(out)

    def all_files_text(self):
        chunks = []
        for root, _, files in os.walk(self.tmp):
            for f in files:
                with open(os.path.join(root, f), "rb") as fh:
                    chunks.append(fh.read().decode("utf-8", "replace"))
        return "\n".join(chunks)


# ---------------------------------------------------------------- DYI

def mojibake(s):
    """How DYI exports store text: UTF-8 bytes, each written as \\u00XX."""
    return s.encode("utf-8").decode("latin-1")


def dyi_tree():
    posts = [
        {"media": [{"uri": "media/posts/202609/a.jpg", "creation_timestamp": 1790000000,
                    "title": mojibake("Café contracts, नमस्ते freelancers #freelance")}]},
        {"media": [{"uri": "media/posts/202609/b1.jpg", "creation_timestamp": 1789000000, "title": ""},
                   {"uri": "media/posts/202609/b2.jpg", "creation_timestamp": 1789000000, "title": ""}],
         "title": mojibake("3 clauses — every contract needs"), "creation_timestamp": 1789000000},
        {"media": [{"uri": "media/posts/202608/c.mp4", "creation_timestamp": 1788000000,
                    "title": "Old feed video"}]},
    ]
    reels = {"ig_reels_media": [
        {"media": [{"uri": "media/reels/202609/r.mp4", "creation_timestamp": 1790500000,
                    "title": mojibake("Nobody tells you this ✅")}]}]}
    stories = {"ig_stories": [{"uri": "media/stories/s.mp4", "creation_timestamp": 1790600000, "title": ""}]}
    followers = [{"string_list_data": [{"value": f"f{i}"}]} for i in range(7)]
    following = {"relationships_following": [{"string_list_data": [{"value": "x"}]}] * 3}
    personal = {"profile_user": [{"string_map_data": {
        "Username": {"value": "dyi_handle"}, "Name": {"value": mojibake("Zoë")},
        "Bio": {"value": "Lahore based"}}}]}
    base = "instagram-dyi_handle-2026-10-01"
    return {
        f"{base}/your_instagram_activity/content/posts_1.json": posts,
        f"{base}/your_instagram_activity/content/reels.json": reels,
        f"{base}/your_instagram_activity/content/stories.json": stories,
        f"{base}/connections/followers_and_following/followers_1.json": followers,
        f"{base}/connections/followers_and_following/following.json": following,
        f"{base}/personal_information/personal_information/personal_information.json": personal,
    }


class TestDYI(Temp):
    def make_zip(self):
        path = os.path.join(self.tmp, "export.zip")
        with zipfile.ZipFile(path, "w") as z:
            for name, obj in dyi_tree().items():
                z.writestr(name, json.dumps(obj))          # ensure_ascii: Ã style escapes
        return path

    def test_fix_mojibake(self):
        self.assertEqual(scan.fix_mojibake(mojibake("café नमस्ते — ✅")), "café नमस्ते — ✅")
        self.assertEqual(scan.fix_mojibake("plain ascii"), "plain ascii")
        self.assertEqual(scan.fix_mojibake("already ok नमस्ते"), "already ok नमस्ते")

    def test_zip_parse(self):
        acc, posts, raw, notes = scan.from_dyi(self.make_zip())
        types = sorted(p["type"] for p in posts)
        self.assertEqual(types, ["carousel", "photo", "reel", "reel"])   # stories off by default
        caps = {p["caption"] for p in posts}
        self.assertIn("Café contracts, नमस्ते freelancers #freelance", caps)
        self.assertIn("3 clauses — every contract needs", caps)
        self.assertIn("Nobody tells you this ✅", caps)
        self.assertEqual(acc["handle"], "dyi_handle")
        self.assertEqual(acc["name"], "Zoë")
        self.assertEqual(acc["followers"], 7)
        self.assertEqual(acc["following"], 3)
        self.assertTrue(all(p["likes"] is None for p in posts))
        self.assertTrue(any("no likes" in n for n in notes))

    def test_folder_and_stories(self):
        root = os.path.join(self.tmp, "unzipped")
        for name, obj in dyi_tree().items():
            path = os.path.join(root, name)
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "w") as f:
                json.dump(obj, f)
        acc, posts, _, _ = scan.from_dyi(root, stories=True)
        self.assertEqual(sum(p["type"] == "story" for p in posts), 1)

    def test_cli_followers_override_and_no_followers_note(self):
        tree = {k: v for k, v in dyi_tree().items() if "followers_1" not in k}
        path = os.path.join(self.tmp, "nofollow.zip")
        with zipfile.ZipFile(path, "w") as z:
            for name, obj in tree.items():
                z.writestr(name, json.dumps(obj))
        _, _, _, notes = scan.from_dyi(path)
        self.assertTrue(any("--followers" in n for n in notes))
        code, out, err = self.cli("dyi", path, "--followers", "12345")
        self.assertEqual(code, 0, err)
        acc = jload((os.path.join(self.data, "scan", "account.json")))
        self.assertEqual(acc["followers"], 12345)

    def test_not_an_export(self):
        path = os.path.join(self.tmp, "empty.zip")
        with zipfile.ZipFile(path, "w") as z:
            z.writestr("readme.txt", "hi")
        code, _, err = self.cli("dyi", path)
        self.assertEqual(code, 2)
        self.assertIn("posts_", err)


# ---------------------------------------------------------------- captured

class TestCaptured(Temp):
    def test_ingest_writes_scan_files(self):
        self.ingest_synth()
        d = os.path.join(self.data, "scan")
        acc = jload((os.path.join(d, "account.json")))
        posts = jload((os.path.join(d, "posts.json")))["posts"]
        self.assertEqual(acc["handle"], "contractcoach")
        self.assertEqual(acc["source"], "kweo")
        self.assertEqual(len(posts), 40)
        self.assertTrue(os.listdir(os.path.join(d, "raw")))

    def test_null_metrics_and_extra_fields(self):
        cap = {"handle": "@Someone", "followers": "12.4K", "source": "kweo", "scanned_at": "2026-10-15",
               "notes": "views hidden on two posts",
               "posts": [{"date": "2026-10-01", "type": "Reel", "caption": "hi there", "likes": None,
                          "comments": None, "views": None, "url": "https://www.instagram.com/reel/A/",
                          "pinned": True},
                         {"date": "2026-10-03", "type": "carousel", "caption": "two", "likes": "1,204",
                          "url": "https://www.instagram.com/p/B/", "unknown_field": 1}]}
        acc, posts, raw, notes, stash = scan.from_captured([self.write("c.json", cap)])
        self.assertEqual(acc["handle"], "someone")
        self.assertEqual(acc["followers"], 12400)
        a = next(p for p in posts if p["url"].endswith("/A/"))
        self.assertTrue(a["pinned"])
        self.assertIsNone(a["likes"])
        b = next(p for p in posts if p["url"].endswith("/B/"))
        self.assertEqual(b["likes"], 1204)
        self.assertTrue(any("views hidden" in n for n in notes))

    def test_multi_file_merge_dedupes_by_url(self):
        prof = make_captured(n=6)
        extra = {"source": "kweo", "posts": [
            dict(prof["posts"][0], likes=999),                       # duplicate url, newer number
            {"date": "2026-01-02", "type": "photo", "caption": "older post", "likes": 5,
             "url": "https://www.instagram.com/p/OLD1/"}], "notes": ""}
        ins = {"source": "kweo", "insights": [
            {"url": prof["posts"][1]["url"], "views": 7777, "reach": 6000, "saves": 40, "shares": 9,
             "follows": 3, "skip_rate": 31, "nonfollower_pct": 55, "avg_watch_s": 8.5},
            {"url": "https://www.instagram.com/p/NOPE/", "views": 1}], "notes": ""}
        p1, p2, p3 = self.write("a.json", prof), self.write("b.json", extra), self.write("c.json", ins)
        code, out, err = self.cli("ingest", "--captured", p1, "--captured", p2, "--captured", p3)
        self.assertEqual(code, 0, err)
        posts = jload((os.path.join(self.data, "scan", "posts.json")))["posts"]
        self.assertEqual(len(posts), 7)
        urls = [p["url"] for p in posts]
        self.assertEqual(len(urls), len(set(urls)))
        first = next(p for p in posts if p["url"] == prof["posts"][0]["url"])
        self.assertEqual(first["likes"], 999)
        second = next(p for p in posts if p["url"] == prof["posts"][1]["url"])
        self.assertEqual((second["views"], second["reach"], second["saves"], second["follows"]),
                         (7777, 6000, 40, 3))
        self.assertIn("no matching post url", out)
        # a second ingest of the same files changes nothing
        self.cli("ingest", "--captured", p1, "--captured", p2)
        self.assertEqual(len(jload((os.path.join(self.data, "scan", "posts.json")))["posts"]), 7)

    def test_insights_file_alone_fills_existing_scan(self):
        prof = make_captured(n=4)
        self.cli("ingest", "--captured", self.write("a.json", prof))
        ins = {"source": "kweo", "insights": [{"url": prof["posts"][2]["url"], "reach": 4321}]}
        code, out, err = self.cli("ingest", "--captured", self.write("i.json", ins))
        self.assertEqual(code, 0, err)
        posts = jload((os.path.join(self.data, "scan", "posts.json")))["posts"]
        self.assertEqual(len(posts), 4)
        self.assertEqual(next(p for p in posts if p["url"] == prof["posts"][2]["url"])["reach"], 4321)
        acc = jload((os.path.join(self.data, "scan", "account.json")))
        self.assertEqual(acc["handle"], "contractcoach")          # not blanked by the handle-less file

    def test_blocked_login_saves_nothing(self):
        good = self.write("a.json", make_captured(n=3))
        bad = self.write("b.json", {"source": "kweo", "blocked": "login", "posts": [], "notes": "login wall"})
        code, out, err = self.cli("ingest", "--captured", good, "--captured", bad)
        self.assertEqual(code, 3)
        self.assertIn("log in", err)
        self.assertFalse(os.path.exists(os.path.join(self.data, "scan", "posts.json")))

    def test_new_handle_starts_over(self):
        self.ingest_synth(n=5)
        path = self.write("other.json", make_captured(n=3, handle="otherclient"))
        code, out, _ = self.cli("ingest", "--captured", path)
        posts = jload((os.path.join(self.data, "scan", "posts.json")))["posts"]
        self.assertEqual(len(posts), 3)
        self.assertIn("started over", out)


# ---------------------------------------------------------------- API

class FakeResp(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def http_error(url, code, message):
    body = json.dumps({"error": {"message": message, "code": 100}}).encode()
    return urllib.error.HTTPError(url, code, "Bad Request", {}, io.BytesIO(body))


class FakeGraph:
    """graph.instagram.com, enough of it: /me, paged /me/media, insights
    that refuse reels_skip_rate."""

    def __init__(self, n=120):
        self.n = n
        self.urls = []

    def __call__(self, req, timeout=None):
        url = req.full_url
        self.urls.append(url)
        assert url.startswith("https://graph.instagram.com/v25.0/"), url
        path = url.split("/v25.0/", 1)[1].split("?", 1)[0]
        q = dict(p.split("=", 1) for p in url.split("?", 1)[1].split("&"))
        if path == "me":
            return FakeResp(json.dumps({"user_id": "1", "username": "apiuser", "account_type": "MEDIA_CREATOR",
                                        "followers_count": 52000, "follows_count": 300, "media_count": self.n,
                                        "biography": "Recipes from Karachi", "website": "https://x.pk"}).encode())
        if path == "me/media":
            after = int(q.get("after", 0))
            items = []
            for i in range(after, min(after + 50, self.n)):
                mt = ["VIDEO", "CAROUSEL_ALBUM", "IMAGE"][i % 3]
                items.append({"id": str(1000 + i), "caption": f"Recipe {i} chicken karahi #food",
                              "media_type": mt, "media_product_type": "REELS" if mt == "VIDEO" else "FEED",
                              "timestamp": (dt.datetime(2026, 10, 14) - dt.timedelta(days=2 * i))
                              .strftime("%Y-%m-%dT%H:%M:%S+0000"),
                              "permalink": f"https://www.instagram.com/p/X{i}/",
                              "like_count": 100 + i, "comments_count": 5})
            page = {"data": items}
            if after + 50 < self.n:
                page["paging"] = {"cursors": {"after": str(after + 50)},
                                  "next": f"https://graph.instagram.com/v25.0/me/media?access_token={TOKEN}"
                                          f"&limit=50&after={after + 50}"}
            return FakeResp(json.dumps(page).encode())
        if path.endswith("/insights"):
            metrics = q["metric"].split("%2C")
            if "reels_skip_rate" in metrics:
                raise http_error(url, 400, f"metric reels_skip_rate not supported for token {TOKEN}")
            data = [{"name": m, "values": [{"value": 90000 if m == "ig_reels_avg_watch_time" else 10}]}
                    for m in metrics]
            return FakeResp(json.dumps({"data": data}).encode())
        raise http_error(url, 404, "unknown path")


class TestAPI(Temp):
    def test_paging_cap_and_types(self):
        fake = FakeGraph(n=120)
        with mock.patch.object(scan.urllib.request, "urlopen", fake):
            client = scan.APIClient(TOKEN, pause=0, log=lambda m: None)
            acc, posts, raw, notes = scan.from_api(client, max_posts=110)
        self.assertEqual(len(posts), 110)
        self.assertEqual(sum(1 for u in fake.urls if "/me/media" in u), 3)
        self.assertEqual(acc["account_type"], "creator")
        self.assertEqual(acc["followers"], 52000)
        self.assertEqual({p["type"] for p in posts}, {"reel", "carousel", "photo"})
        self.assertNotIn(TOKEN, json.dumps(raw))
        self.assertNotIn(TOKEN, repr(client))

    def test_insights_errors_tolerated_and_token_never_logged(self):
        fake = FakeGraph(n=6)
        os.environ["IG_ACCESS_TOKEN"] = TOKEN
        with mock.patch.object(scan.urllib.request, "urlopen", fake), \
                mock.patch.object(scan.time, "sleep", lambda s: None):
            code, out, err = self.cli("api", "--insights", "--max", "6")
        self.assertEqual(code, 0, err)
        posts = jload((os.path.join(self.data, "scan", "posts.json")))["posts"]
        reel = next(p for p in posts if p["type"] == "reel")
        self.assertEqual(reel["reach"], 10)
        self.assertEqual(reel["avg_watch_s"], 90.0)
        self.assertIsNone(reel["skip_rate"])
        self.assertIn("reels_skip_rate", out)
        # skip rate refused once, then not asked again for later reels
        asked = [u for u in fake.urls if "insights" in u and "reels_skip_rate" in u]
        self.assertEqual(len(asked), 2)          # the combined call and the single-metric retry
        self.assertNotIn(TOKEN, out + err)
        self.assertNotIn(TOKEN, self.all_files_text())

    def test_missing_token(self):
        code, out, err = self.cli("api")
        self.assertEqual(code, 2)
        self.assertIn("IG_ACCESS_TOKEN", err)

    def test_http_error_redacted(self):
        def boom(req, timeout=None):
            raise http_error(req.full_url, 400, f"Invalid OAuth access token {TOKEN}")
        os.environ["IG_ACCESS_TOKEN"] = TOKEN
        with mock.patch.object(scan.urllib.request, "urlopen", boom):
            code, out, err = self.cli("api")
        self.assertEqual(code, 2)
        self.assertIn("Invalid OAuth", err)
        self.assertNotIn(TOKEN, out + err)

    def test_refuses_foreign_paging_link(self):
        client = scan.APIClient(TOKEN, pause=0)
        with self.assertRaises(scan.APIError):
            client._open("https://evil.example.com/steal?access_token=x")


# ---------------------------------------------------------------- analysis

class TestAnalyze(Temp):
    def test_tiers(self):
        cases = [(None, "unknown"), (0, "nano"), (9999, "nano"), (10000, "micro"), (99999, "micro"),
                 (100000, "mid"), (499999, "mid"), (500000, "macro"), (999999, "macro"), (1000000, "mega")]
        for n, tier in cases:
            self.assertEqual(scan.size_tier(n), tier, n)

    def test_cadence(self):
        posts = [{"date": (TODAY - dt.timedelta(days=d)).isoformat(), "type": "reel"}
                 for d in (1, 3, 5, 20, 60)]
        c = scan.cadence(posts, TODAY)
        self.assertEqual(c["per_week_30d"], round(4 / (30 / 7), 2))
        self.assertEqual(c["per_week_90d"], round(5 / (90 / 7), 2))
        self.assertEqual(c["longest_gap_days"], 40)
        self.assertEqual(c["days_since_last"], 1)
        self.assertEqual(c["weeks_considered"], 9)
        self.assertEqual(c["consistency"], round(100 * 3 / 9))

    def test_full_analysis_on_synthetic_account(self):
        self.ingest_synth()
        a = self.analysis()
        self.assertEqual(a["size"]["tier"], "micro")
        self.assertEqual(a["n_feed"], 40)
        self.assertEqual(a["performance"]["basis"], "interactions")
        self.assertAlmostEqual(sorted(p["outlier"] for p in a["posts"])[20], 1.0, delta=0.15)
        # engagement: reels were built to beat photos
        er = a["performance"]["er_by_format"]
        self.assertGreater(er["reel"]["median"], er["photo"]["median"])
        self.assertEqual(a["what_performs"]["format"][0]["group"], "reel")
        h = a["content"]["hashtags"]
        self.assertEqual(h["cap"], 5)
        self.assertEqual(h["over_cap_posts"], 10)
        self.assertIn("hashtags", a["worst_habit"])
        self.assertEqual(a["niche_guess"]["label"], "freelancing and careers")
        self.assertEqual(a["content"]["languages"][0]["code"], "en")
        cta = a["content"]["cta"]["counts"]
        for ask in ("comment a keyword", "save this", "follow", "link in bio"):
            self.assertEqual(cta.get(ask), 8, ask)
        self.assertEqual(a["content"]["cta"]["none_pct"], 20.0)
        self.assertTrue(os.path.exists(os.path.join(self.data, "account.md")))

    def test_outliers_on_views(self):
        posts = [{"date": "2026-10-0%d" % (i + 1), "type": "reel", "caption": "x", "views": v, "likes": 1}
                 for i, v in enumerate([100, 100, 100, 400, 50])]
        perf = scan.performance(posts, 1000)
        self.assertEqual(perf["basis"], "views")
        self.assertEqual(perf["baseline"], 100)
        self.assertEqual(perf["top"][0]["outlier"], 4.0)
        self.assertEqual(perf["er_median"], 0.1)

    def test_formula_classification(self):
        fid, name = scan.classify_hook("Nobody tells you your first 30 reels are practice")
        self.assertEqual(name, "Nobody Tells You")
        self.assertEqual(fid, 3)
        self.assertEqual(scan.classify_hook("")[1], "unclassified")

    def test_languages(self):
        hindi = ["आज मैं आपको बताऊंगा कि फ्रीलांस में पैसे कैसे कमाएं", "यह तरीका सबसे आसान है दोस्तों"]
        urdu = ["آج میں آپ کو بتاؤں گا کہ کیسے کمائیں", "یہ طریقہ سب سے آسان ہے دوستوں ٹھیک ہے"]
        arabic = ["مرحبا بكم في قناتي اليوم سنتحدث عن العمل الحر"]
        hinglish = ["Yaar ye trick kya kamaal hai, aur bhi try karo bhai",
                    "Main nahi jaanta tha ki ye itna easy hai yaar"]
        self.assertEqual(scan.detect_languages(hindi)[0][0][0], "hi")
        self.assertEqual(scan.detect_languages(urdu)[0][0][0], "ur")
        self.assertEqual(scan.detect_languages(arabic)[0][0][0], "ar")
        self.assertEqual(scan.detect_languages(hinglish)[0][0][0], "hi-Latn")
        self.assertEqual(scan.detect_languages(["The best way to price your work"])[0][0][0], "en")
        mixed, shares = scan.detect_languages(["Freelance tips for everyone today", "यह तरीका सबसे आसान है"])
        codes = {c for c, _, _ in mixed}
        self.assertEqual(codes, {"en", "hi"})
        self.assertIn("DEVANAGARI", shares)

    def test_script_aware_tokens(self):
        toks = scan.tokens("फ्रीलांस कॉन्ट्रैक्ट ज़रूरी है #tag @someone https://x.com the contract")
        self.assertIn("फ्रीलांस", toks)
        self.assertIn("कॉन्ट्रैक्ट", toks)
        self.assertIn("contract", toks)
        self.assertNotIn("है", toks)
        self.assertNotIn("the", toks)
        self.assertFalse(any(t.startswith(("#", "@", "http")) for t in toks))

    def test_hashtags_any_script(self):
        self.assertEqual(scan.hashtags("hi #Freelance #भारत #a_b"), ["freelance", "भारत", "a_b"])

    def test_claude_read_survives_reanalyze(self):
        self.ingest_synth()
        self.analysis()
        md = os.path.join(self.data, "account.md")
        text = _read(md).replace(scan.CLAUDE_READ_PLACEHOLDER,
                                       "- Niche, in one line: contract law for Indian freelancers")
        _write(md, text)
        self.analysis()
        self.assertIn("contract law for Indian freelancers", _read(md))
        code, out, _ = self.cli("context")
        self.assertIn("niche: contract law for Indian freelancers", out)

    def test_small_sample_honesty(self):
        self.ingest_synth(n=5)
        a = self.analysis()
        self.assertTrue(any("only 5 posts" in n for n in a["honesty"]))
        self.assertTrue(any("missing metrics" in n for n in a["honesty"]))
        thin = [r for r in a["what_performs"]["formula"] if r["n"] < 3]
        self.assertTrue(all(r["thin"] for r in thin))

    def test_analyze_without_scan(self):
        code, _, err = self.cli("analyze")
        self.assertEqual(code, 2)
        self.assertIn("no scan yet", err)


# ---------------------------------------------------------------- context, ledger, prefill

class TestContext(Temp):
    def test_block_is_short_and_complete(self):
        self.ingest_synth()
        self.analysis()
        code, out, _ = self.cli("context")
        lines = out.strip().splitlines()
        self.assertTrue(10 <= len(lines) <= 15, len(lines))
        text = out
        for needle in ("@contractcoach", "micro", "niche:", "(guess, not confirmed)", "audience language",
                       "cadence:", "best format: reel", "best hook formula", "best theme", "worst habit",
                       "2026-10-15"):
            self.assertIn(needle, text)

    def test_confirmed_niche_from_profile(self):
        self.ingest_synth()
        self.analysis()
        with open(os.path.join(self.data, "profile.json"), "w") as f:
            json.dump({"niche": "freelance contracts", "region": "IN"}, f)
        code, out, _ = self.cli("context", "--json")
        lines = json.loads(out)["lines"]
        self.assertIn("niche: freelance contracts (confirmed)", lines)

    def test_no_profile(self):
        code, _, err = self.cli("context")
        self.assertEqual(code, 2)


class TestLedger(Temp):
    def setUp(self):
        super().setUp()
        self.ledger = scan._import_from("ig-ledger", "ledger")
        self.assertIsNotNone(self.ledger, "ig-ledger/ledger.py not found")

    def test_import_then_dedupe(self):
        cap = make_captured(n=10)
        cap["posts"][0]["views"] = None          # this scan did not see views on that post
        # one post already logged by hand with its permalink and views
        self.ledger.add_row(format="reel", date=cap["posts"][0]["date"], permalink=cap["posts"][0]["url"],
                            views=12345, theme="contracts", first_line="hand logged")
        # one logged without a link, matched by date + first line
        fl = cap["posts"][1]["caption"].splitlines()[0]
        self.ledger.add_row(format=cap["posts"][1]["type"], date=cap["posts"][1]["date"], first_line=fl)
        self.cli("ingest", "--captured", self.write("c.json", cap))
        self.analysis()
        code, out, _ = self.cli("to-ledger", "--dry-run", "--json")
        self.assertEqual(json.loads(out)["created"], 8)
        self.assertEqual(len(self.ledger.load_rows()), 2)               # dry run wrote nothing
        code, out, _ = self.cli("to-ledger", "--json")
        s = json.loads(out)
        self.assertEqual((s["created"], s["updated"]), (8, 2))
        rows = self.ledger.load_rows()
        self.assertEqual(len(rows), 10)
        hand = rows[0]
        self.assertEqual(hand["views"], "12345")                         # not blanked
        self.assertEqual(hand["theme"], "contracts")                     # text not overwritten
        self.assertEqual(hand["first_line"], "hand logged")
        self.assertNotEqual(hand["likes"], "")                           # filled in from the scan
        self.assertEqual(rows[1]["permalink"], cap["posts"][1]["url"])   # link filled in
        self.assertTrue(all(r["format"] for r in rows))
        self.assertTrue(any(r["hook_formula"] for r in rows))
        code, out, _ = self.cli("to-ledger", "--json")
        s = json.loads(out)
        self.assertEqual((s["created"], s["updated"], s["unchanged"]), (0, 0, 10))
        self.assertEqual(len(self.ledger.load_rows()), 10)


class TestPrefill(Temp):
    def test_suggestions(self):
        self.ingest_synth()
        self.analysis()
        code, out, _ = self.cli("prefill", "--json")
        pf = json.loads(out)
        self.assertEqual(pf["suggested"]["region"], "IN")
        self.assertEqual(pf["suggested"]["account_type"], "creator")
        self.assertEqual(pf["suggested"]["language"], "en")
        self.assertEqual(pf["suggested"]["niche"], "freelancing and careers")
        self.assertIn("state.py set --region IN", pf["command"])
        self.assertEqual(len(pf["typical_captions"]), 3)
        self.assertFalse(os.path.exists(os.path.join(self.data, "profile.json")))   # suggest only

    def test_region_clues(self):
        acc = {"bio": "Home cook in Lahore", "website": "", "name": ""}
        self.assertEqual(scan.guess_region(acc, {})[0], "PK")
        acc = {"bio": "", "website": "https://shop.co.uk/x", "name": ""}
        self.assertEqual(scan.guess_region(acc, {})[0], "GB")
        a = {"content": {"languages": [{"code": "ur", "share": 0.8, "label": "Urdu"}]}}
        self.assertEqual(scan.guess_region({"bio": ""}, a)[0], "PK")
        self.assertIsNone(scan.guess_region({"bio": "hello"}, {})[0])


if __name__ == "__main__":
    unittest.main()
