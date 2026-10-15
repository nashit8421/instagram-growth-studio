"""Tests for account.py. Stdlib only.

Run from the skill folder:  python3 -m unittest discover -s tests
Every test points IG_HOME at a fresh temp dir and unsets IG_DATA_DIR. The real
~/IGStudio is never touched.
"""

import contextlib
import io
import json
import os
import shutil
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))

import account  # noqa: E402


class Base(unittest.TestCase):
    def setUp(self):
        self.home = tempfile.mkdtemp(prefix="ig-account-test-")
        self._env = {k: os.environ.get(k) for k in ("IG_HOME", "IG_DATA_DIR")}
        os.environ["IG_HOME"] = self.home
        os.environ.pop("IG_DATA_DIR", None)
        self._tpl = account.TEMPLATE_CANDIDATES
        self.tpldir = tempfile.mkdtemp(prefix="ig-account-tpl-")
        self.tpl = os.path.join(self.tpldir, "voice.md")
        with open(self.tpl, "w") as f:
            f.write("# voice.md template\n")
        account.TEMPLATE_CANDIDATES = [self.tpl]

    def tearDown(self):
        account.TEMPLATE_CANDIDATES = self._tpl
        for k, v in self._env.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        shutil.rmtree(self.home, ignore_errors=True)
        shutil.rmtree(self.tpldir, ignore_errors=True)

    def run_cli(self, *argv):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = account.main(list(argv))
        return code, out.getvalue(), err.getvalue()

    def write(self, rel, text="x"):
        p = os.path.join(self.home, rel)
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with open(p, "w") as f:
            f.write(text)
        return p

    def backups(self):
        return sorted(n for n in os.listdir(self.home) if n.startswith("backup-"))


class Resolver(Base):
    def test_default_is_ig_home(self):
        self.assertEqual(account.resolve_data_dir(), self.home)

    def test_ig_home_default_when_unset(self):
        os.environ.pop("IG_HOME")
        self.assertEqual(account.ig_home(), os.path.expanduser("~/IGStudio"))

    def test_active_account_with_folder(self):
        os.makedirs(os.path.join(self.home, "accounts", "acme.co"))
        self.write("active-account", "  @Acme.Co \n")
        self.assertEqual(account.resolve_data_dir(), os.path.join(self.home, "accounts", "acme.co"))

    def test_active_account_without_folder_falls_back(self):
        self.write("active-account", "ghost")
        self.assertEqual(account.resolve_data_dir(), self.home)

    def test_invalid_active_handle_falls_back(self):
        os.makedirs(os.path.join(self.home, "accounts", "..", "evil"), exist_ok=True)
        self.write("active-account", "../evil")
        self.assertEqual(account.resolve_data_dir(), self.home)

    def test_ig_data_dir_wins(self):
        os.makedirs(os.path.join(self.home, "accounts", "acme"))
        self.write("active-account", "acme")
        os.environ["IG_DATA_DIR"] = "/somewhere/else"
        self.assertEqual(account.resolve_data_dir(), "/somewhere/else")


class Handles(unittest.TestCase):
    def test_valid(self):
        for h in ("a", "jake.s", "jake_s", "@Jake99", "a" * 30, "_x_"):
            with self.subTest(h=h):
                self.assertIsNone(account.handle_error(h))

    def test_invalid(self):
        for h in ("", "@", "a" * 31, "has space", "dash-ed", "émile", ".lead", "trail.",
                  "dou..ble", "../x", "a/b"):
            with self.subTest(h=h):
                self.assertIsNotNone(account.handle_error(h))


class Commands(Base):
    def test_new_use_current_path_list(self):
        code, out, _ = self.run_cli("new", "@Client.One")
        self.assertEqual(code, 0)
        d = os.path.join(self.home, "accounts", "client.one")
        self.assertTrue(os.path.isdir(d))
        with open(os.path.join(d, "voice.md")) as f:
            self.assertIn("template", f.read())
        # not active until `use`
        self.assertEqual(self.run_cli("path")[1].strip(), self.home)

        self.assertEqual(self.run_cli("use", "client.one")[0], 0)
        self.assertEqual(self.run_cli("path")[1].strip(), d)
        code, out, _ = self.run_cli("current")
        self.assertIn("@client.one", out)
        self.assertIn(d, out)
        cur = json.loads(self.run_cli("current", "--json")[1])
        self.assertEqual(cur["handle"], "client.one")
        self.assertEqual(cur["source"], "account")

        self.run_cli("new", "other")
        code, out, _ = self.run_cli("list")
        self.assertIn("* @client.one", out)
        self.assertIn("  @other", out)
        data = json.loads(self.run_cli("list", "--json")[1])
        self.assertEqual([(a["handle"], a["active"]) for a in data["accounts"]],
                         [("client.one", True), ("other", False)])

    def test_use_none(self):
        self.run_cli("new", "a1")
        self.run_cli("use", "a1")
        self.assertEqual(self.run_cli("use", "--none")[0], 0)
        self.assertFalse(os.path.exists(os.path.join(self.home, "active-account")))
        self.assertEqual(self.run_cli("path")[1].strip(), self.home)
        self.assertIn("no active account", self.run_cli("current")[1])

    def test_use_unknown(self):
        code, _, err = self.run_cli("use", "nobody")
        self.assertEqual(code, 1)
        self.assertIn("account.py new nobody", err)
        self.assertFalse(os.path.exists(os.path.join(self.home, "active-account")))

    def test_new_duplicate(self):
        self.run_cli("new", "dup")
        self.assertEqual(self.run_cli("new", "DUP")[0], 1)

    def test_invalid_handles_rejected(self):
        for h in ("bad handle", "x" * 31, "a..b", "nope!"):
            with self.subTest(h=h):
                code, _, err = self.run_cli("new", h)
                self.assertEqual(code, 1)
                self.assertIn("invalid handle", err)
        self.assertFalse(os.path.exists(os.path.join(self.home, "accounts")))
        self.assertEqual(self.run_cli("use", "bad handle")[0], 1)
        self.assertEqual(self.run_cli("remove", "a..b", "--yes")[0], 1)

    def test_current_with_override(self):
        os.environ["IG_DATA_DIR"] = os.path.join(self.home, "elsewhere")
        cur = json.loads(self.run_cli("current", "--json")[1])
        self.assertEqual(cur["source"], "IG_DATA_DIR")
        self.assertEqual(cur["data_dir"], os.path.join(self.home, "elsewhere"))

    def test_remove_moves_to_backup(self):
        self.run_cli("new", "gone")
        self.write("accounts/gone/posts.csv", "id\nP001\n")
        self.run_cli("use", "gone")
        self.assertEqual(self.run_cli("remove", "gone")[0], 2)          # needs --yes
        self.assertTrue(os.path.isdir(os.path.join(self.home, "accounts", "gone")))
        code, out, _ = self.run_cli("remove", "gone", "--yes")
        self.assertEqual(code, 0)
        self.assertFalse(os.path.exists(os.path.join(self.home, "accounts", "gone")))
        [b] = self.backups()
        with open(os.path.join(self.home, b, "accounts", "gone", "posts.csv")) as f:
            self.assertIn("P001", f.read())
        self.assertFalse(os.path.exists(os.path.join(self.home, "active-account")))
        self.assertEqual(account.resolve_data_dir(), self.home)

    def test_remove_unknown(self):
        self.assertEqual(self.run_cli("remove", "nobody", "--yes")[0], 1)


class Migration(Base):
    def setUp(self):
        super().setUp()
        self.write("voice.md", "my real voice")
        self.write("posts.csv", "id\nP001\n")
        self.write("swipe.md", "swipe")
        self.write("renders/x.png", "png")

    def test_needs_yes(self):
        code, out, _ = self.run_cli("new", "me", "--from-current")
        self.assertEqual(code, 2)
        self.assertIn("posts.csv", out)
        self.assertFalse(os.path.exists(os.path.join(self.home, "accounts")))
        self.assertTrue(os.path.exists(os.path.join(self.home, "posts.csv")))
        self.assertEqual(self.backups(), [])

    def test_moves_with_backup(self):
        code, out, _ = self.run_cli("new", "me", "--from-current", "--yes", "--json")
        self.assertEqual(code, 0)
        res = json.loads(out)
        self.assertEqual(sorted(res["moved"]), ["posts.csv", "renders", "swipe.md", "voice.md"])
        d = os.path.join(self.home, "accounts", "me")
        for n in ("voice.md", "posts.csv", "swipe.md", "renders/x.png"):
            self.assertTrue(os.path.exists(os.path.join(d, n)), n)
            self.assertFalse(os.path.exists(os.path.join(self.home, n)), n)
            self.assertTrue(os.path.exists(os.path.join(res["backup"], n)), n)
        with open(os.path.join(d, "voice.md")) as f:
            self.assertEqual(f.read(), "my real voice")       # template did not clobber it
        self.assertEqual(self.backups(), [os.path.basename(res["backup"])])
        # a second account and a switch keep data apart
        self.run_cli("new", "client")
        self.run_cli("use", "me")
        self.assertEqual(account.resolve_data_dir(), d)
        self.run_cli("use", "client")
        self.assertFalse(os.path.exists(os.path.join(account.resolve_data_dir(), "posts.csv")))

    def test_migration_skips_bookkeeping(self):
        self.run_cli("new", "first")
        self.write("active-account", "first")
        os.makedirs(os.path.join(self.home, "backup-20200101-000000"))
        self.run_cli("new", "me", "--from-current", "--yes")
        left = sorted(os.listdir(self.home))
        self.assertIn("accounts", left)
        self.assertIn("active-account", left)
        self.assertIn("backup-20200101-000000", left)
        self.assertTrue(os.path.isdir(os.path.join(self.home, "accounts", "first")))

    def test_nothing_to_move(self):
        for n in ("voice.md", "posts.csv", "swipe.md"):
            os.remove(os.path.join(self.home, n))
        shutil.rmtree(os.path.join(self.home, "renders"))
        self.assertEqual(self.run_cli("new", "me", "--from-current", "--yes")[0], 1)


if __name__ == "__main__":
    unittest.main()
