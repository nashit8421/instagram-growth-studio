"""Tests for kweo_check.py. Stdlib only, nothing real is probed.

Run from the skill folder:  python3 -m unittest discover -s tests
subprocess, urlopen, shutil.which and the app path are all mocked.
"""

import contextlib
import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
import urllib.error
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))

import kweo_check as kc  # noqa: E402


class FakeResp:
    status = 200

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def http_error(code):
    return urllib.error.HTTPError(kc.MCP_URL, code, "x", {}, None)


def proc(rc=0, out=""):
    return subprocess.CompletedProcess([], rc, stdout=out, stderr="")


class ServerCheck(unittest.TestCase):
    def test_401_means_running_needs_token(self):
        with mock.patch("urllib.request.urlopen", side_effect=http_error(401)):
            self.assertEqual(kc.check_server(), ("auth", 401))

    def test_200_means_open(self):
        with mock.patch("urllib.request.urlopen", return_value=FakeResp()):
            self.assertEqual(kc.check_server(), ("open", 200))

    def test_refused_means_toggle_off(self):
        err = urllib.error.URLError(ConnectionRefusedError(61, "Connection refused"))
        with mock.patch("urllib.request.urlopen", side_effect=err):
            self.assertEqual(kc.check_server(), ("off", None))

    def test_other_http_code_is_error(self):
        with mock.patch("urllib.request.urlopen", side_effect=http_error(500)):
            self.assertEqual(kc.check_server(), ("error", 500))

    def test_sends_initialize_without_auth(self):
        with mock.patch("urllib.request.urlopen", side_effect=http_error(401)) as m:
            kc.check_server()
        req = m.call_args[0][0]
        self.assertEqual(req.get_method(), "POST")
        self.assertIn(b'"initialize"', req.data)
        self.assertIsNone(req.get_header("Authorization"))


class ProcessAndApp(unittest.TestCase):
    def test_pgrep_found(self):
        with mock.patch("subprocess.run", return_value=proc(0, "43382\n")):
            self.assertTrue(kc.check_process())

    def test_pgrep_not_found(self):
        with mock.patch("subprocess.run", return_value=proc(1, "")):
            self.assertFalse(kc.check_process())

    def test_pgrep_missing(self):
        with mock.patch("subprocess.run", side_effect=FileNotFoundError):
            self.assertIsNone(kc.check_process())

    def test_app_found_in_second_path(self):
        with tempfile.TemporaryDirectory() as d:
            app = os.path.join(d, "kweo.app")
            os.mkdir(app)
            self.assertEqual(kc.check_app(("/nope/kweo.app", app)), (True, app))
            self.assertEqual(kc.check_app(("/nope/kweo.app",)), (False, None))


class ClaudeCheck(unittest.TestCase):
    LIST = ("Checking MCP server health...\n\n"
            "gmail: https://x/mcp - ✔ Connected\n"
            "kweo: http://127.0.0.1:7333/mcp (HTTP) - ✔ Connected\n")

    def test_registered(self):
        with mock.patch("shutil.which", return_value="/bin/claude"), \
             mock.patch("subprocess.run", return_value=proc(0, self.LIST)):
            self.assertEqual(kc.check_claude(), ("yes", "connected"))

    def test_registered_but_failing(self):
        out = "kweo: http://127.0.0.1:7333/mcp (HTTP) - ✗ Failed to connect\n"
        with mock.patch("shutil.which", return_value="/bin/claude"), \
             mock.patch("subprocess.run", return_value=proc(0, out)):
            self.assertEqual(kc.check_claude(), ("yes", "registered"))

    def test_not_registered(self):
        out = "gmail: https://x/mcp - ok\nkweofake: http://x - ok\n"
        with mock.patch("shutil.which", return_value="/bin/claude"), \
             mock.patch("subprocess.run", return_value=proc(0, out)):
            self.assertEqual(kc.check_claude(), ("no", None))

    def test_claude_missing(self):
        with mock.patch("shutil.which", return_value=None):
            self.assertEqual(kc.check_claude(), ("missing", None))

    def test_claude_timeout(self):
        with mock.patch("shutil.which", return_value="/bin/claude"), \
             mock.patch("subprocess.run",
                        side_effect=subprocess.TimeoutExpired("claude", 60)):
            self.assertEqual(kc.check_claude()[0], "error")


class Verdict(unittest.TestCase):
    def state(self, **kw):
        s = {"app": True, "app_path": "/Applications/kweo.app", "process": True,
             "server": "auth", "http_code": 401, "claude": "yes",
             "claude_detail": "connected"}
        s.update(kw)
        return s

    def test_not_installed(self):
        ready, msg = kc.next_step(self.state(app=False, process=False, server="off"))
        self.assertFalse(ready)
        self.assertIn("https://kweo.ai", msg)

    def test_not_running(self):
        ready, msg = kc.next_step(self.state(process=False, server="off"))
        self.assertIn("not running", msg)

    def test_toggle_off(self):
        ready, msg = kc.next_step(self.state(server="off", http_code=None))
        self.assertFalse(ready)
        self.assertIn("Let Claude control kweo", msg)

    def test_needs_registering(self):
        ready, msg = kc.next_step(self.state(claude="no", claude_detail=None))
        self.assertFalse(ready)
        self.assertIn("claude mcp add kweo", msg)
        self.assertIn("<token>", msg)
        self.assertIn("restart Claude Code", msg)

    def test_ready(self):
        ready, msg = kc.next_step(self.state())
        self.assertTrue(ready)

    def test_cli_json_and_exit_code(self):
        s = self.state(claude="no", claude_detail=None)
        with mock.patch.object(kc, "check_app", return_value=(True, s["app_path"])), \
             mock.patch.object(kc, "check_process", return_value=True), \
             mock.patch.object(kc, "check_server", return_value=("auth", 401)), \
             mock.patch.object(kc, "check_claude", return_value=("no", None)):
            out = io.StringIO()
            with contextlib.redirect_stdout(out):
                rc = kc.main(["--json"])
            d = json.loads(out.getvalue())
            self.assertEqual(rc, 1)
            self.assertEqual(d["server"], "auth")
            self.assertFalse(d["ready"])
            out = io.StringIO()
            with contextlib.redirect_stdout(out):
                kc.main([])
            self.assertIn("KWEO CHECK", out.getvalue())
            self.assertIn("NEXT:", out.getvalue())
            self.assertNotIn("Bearer ey", out.getvalue())


if __name__ == "__main__":
    unittest.main()
