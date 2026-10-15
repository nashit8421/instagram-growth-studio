import importlib.util
import os
import shutil
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
spec = importlib.util.spec_from_file_location("igs_install", os.path.join(HERE, "..", "server.py"))
server = importlib.util.module_from_spec(spec)
sys.modules["igs_install"] = server
spec.loader.exec_module(server)


class InstallTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.repo = os.path.join(self.tmp, "repo")
        for name in ("ig", "ig-reel"):
            d = os.path.join(self.repo, "skills", name)
            os.makedirs(os.path.join(d, "tests"))
            open(os.path.join(d, "SKILL.md"), "w").write("---\nname: %s\n---\n" % name)
            open(os.path.join(d, "tests", "t.py"), "w").write("x")
        open(os.path.join(self.repo, "skills", "ig", "state.py"), "w").write("# state")
        os.makedirs(os.path.join(self.repo, "agents"))
        open(os.path.join(self.repo, "agents", "a.md"), "w").write("agent")
        open(os.path.join(self.repo, "platform.json"), "w").write("{}")
        self.claude = os.path.join(self.tmp, "claude")
        self.saved = (server.REPO_DIR, server.BUNDLED_SKILLS, server.BUNDLED_AGENTS)
        server.REPO_DIR = self.repo
        server.BUNDLED_SKILLS = os.path.join(self.repo, "skills")
        server.BUNDLED_AGENTS = os.path.join(self.repo, "agents")
        self.env = {k: os.environ.get(k) for k in ("IG_SKILLS_DIR", "IG_CLAUDE_SKILLS", "IG_CLAUDE_AGENTS")}
        os.environ.pop("IG_SKILLS_DIR", None)
        os.environ["IG_CLAUDE_SKILLS"] = os.path.join(self.claude, "skills")
        os.environ["IG_CLAUDE_AGENTS"] = os.path.join(self.claude, "agents")

    def tearDown(self):
        server.REPO_DIR, server.BUNDLED_SKILLS, server.BUNDLED_AGENTS = self.saved
        for k, v in self.env.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        shutil.rmtree(self.tmp)

    def test_fresh_download_runs_bundled_skills(self):
        self.assertEqual(server.skills_dir(), server.BUNDLED_SKILLS)
        st = server.install_status()
        self.assertTrue(st["needed"])
        self.assertEqual(st["missing"], ["ig", "ig-reel"])

    def test_install_copies_skips_tests_and_switches_dir(self):
        r = server.install_skills()
        self.assertEqual(r["installed"], ["ig", "ig-reel"])
        self.assertIsNone(r["backup"])
        inst = os.environ["IG_CLAUDE_SKILLS"]
        self.assertTrue(os.path.isfile(os.path.join(inst, "ig", "state.py")))
        self.assertFalse(os.path.exists(os.path.join(inst, "ig", "tests")))
        self.assertTrue(os.path.isfile(os.path.join(inst, "platform.json")))
        self.assertTrue(os.path.isfile(os.path.join(os.environ["IG_CLAUDE_AGENTS"], "a.md")))
        self.assertFalse(server.install_status()["needed"])
        self.assertEqual(server.skills_dir(), inst)

    def test_update_backs_up_old_version(self):
        server.install_skills()
        open(os.path.join(server.BUNDLED_SKILLS, "ig-reel", "SKILL.md"), "a").write("new line\n")
        st = server.install_status()
        self.assertEqual(st["outdated"], ["ig-reel"])
        r = server.install_skills()
        self.assertTrue(os.path.isdir(os.path.join(r["backup"], "ig-reel")))
        self.assertFalse(server.install_status()["needed"])

    def test_env_override_disables_banner(self):
        os.environ["IG_SKILLS_DIR"] = self.tmp
        self.assertFalse(server.install_status()["needed"])


if __name__ == "__main__":
    unittest.main()


class OpenConfirmTests(unittest.TestCase):
    def setUp(self):
        self.calls = []
        self.saved = (server.open_browser, server.subprocess.run, server.sys.platform,
                      server.warm_up_browser, server.default_browser_id, server.app_running, server.time.sleep)
        server.open_browser = lambda url: self.calls.append(("default", url))
        server.warm_up_browser = lambda: False

    def tearDown(self):
        (server.open_browser, server.subprocess.run, server.sys.platform, server.warm_up_browser,
         server.default_browser_id, server.app_running, server.time.sleep) = self.saved

    def test_warm_up_starts_a_closed_browser_first(self):
        server.warm_up_browser = self.saved[3]
        server.sys.platform = "darwin"
        server.default_browser_id = lambda: "ai.kweo.browser"
        state = {"running": False}
        server.app_running = lambda bid: state["running"]
        server.time.sleep = lambda s: None
        ran = []
        def run(args, **kw):
            ran.append(args)
            state["running"] = True
            return type("R", (), {"returncode": 0})()
        server.subprocess.run = run
        self.assertTrue(server.warm_up_browser())
        self.assertEqual(ran[0], ["open", "-g", "-b", "ai.kweo.browser"])
        ran.clear()
        self.assertFalse(server.warm_up_browser())   # already running: nothing to do
        self.assertEqual(ran, [])

    def test_stops_once_the_browser_arrives(self):
        srv = type("S", (), {"requests_seen": 0})()
        def arrive(url):
            self.calls.append(("default", url))
            srv.requests_seen += 1
        server.open_browser = arrive
        self.assertTrue(server.open_and_confirm(srv, "http://x/open?t=a", waits=(0.5, 0.5)))
        self.assertEqual(len(self.calls), 1)

    def test_retries_then_falls_back_to_another_browser(self):
        srv = type("S", (), {"requests_seen": 0})()
        server.sys.platform = "darwin"
        ran = []
        server.subprocess.run = lambda args, **kw: (ran.append(args), type("R", (), {"returncode": 0})())[1]
        self.assertFalse(server.open_and_confirm(srv, "http://x/open?t=a", waits=(0.3, 0.3)))
        self.assertEqual(len(self.calls), 2)              # default browser tried twice
        self.assertEqual(ran[0][:3], ["open", "-a", "Google Chrome"])
