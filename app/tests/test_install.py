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
