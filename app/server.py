#!/usr/bin/env python3
"""
IG Studio - the local web front end for the ig-* Claude Code skills.

    python3 server.py                     # start, open the browser
    python3 server.py --no-browser --port 8765

Stdlib only (Python 3.9+). Binds 127.0.0.1, prints/opens a URL that carries a
random token. The launcher opens /open?t=TOKEN once; the server swaps it for an
HttpOnly SameSite=Strict cookie and redirects to /. Every /api call needs the
token, in that cookie or in the X-IG-Token header.
Nothing here posts, likes, follows, comments or messages anyone.
"""

import argparse
import atexit
import datetime as dt
import hashlib
import hmac
import http.server
import io
import json
import mimetypes
import os
import re
import secrets
import shutil
import signal
import socket
import subprocess
import sys
import threading
import time
import unicodedata
import urllib.parse
import urllib.request
import webbrowser
import zipfile

VERSION = "1.0.0"
APP_DIR = os.path.dirname(os.path.abspath(__file__))
WEB_DIR = os.path.join(APP_DIR, "web")
DEFAULT_PORT = 8765
IS_WIN = os.name == "nt"
MB = 1024 * 1024

UPLOAD_KINDS = {
    "video": ({".mp4", ".mov", ".m4v", ".webm", ".mkv", ".avi"}, 4096 * MB),
    "image": ({".png", ".jpg", ".jpeg", ".webp", ".gif", ".heic"}, 20 * MB),
    "csv": ({".csv"}, 50 * MB),
    "zip": ({".zip"}, 4096 * MB),
    "text": ({".txt", ".srt", ".md"}, 5 * MB),
}
MAX_JSON_BODY = 2 * MB

ALLOWED_TOOLS = [
    "Skill", "Read", "Write", "Edit", "Glob", "Grep", "WebSearch", "WebFetch", "ToolSearch",
    "Task", "Agent",
    "Bash(python3:*)", "Bash(ffmpeg:*)", "Bash(ffprobe:*)",
    # harmless helpers Claude reaches for around the skill scripts
    "Bash(cd:*)", "Bash(ls:*)", "Bash(head:*)", "Bash(tail:*)", "Bash(wc:*)", "Bash(mkdir:*)", "Bash(date:*)",
    "mcp__kweo__browser_navigate", "mcp__kweo__browser_read", "mcp__kweo__browser_wait", "mcp__kweo__browser_links", "mcp__kweo__browser_text", "mcp__kweo__browser_tabs",
    "mcp__kweo__browser_new_tab", "mcp__kweo__browser_select_tab",
    "mcp__claude_ai_Google_Calendar__list_calendars", "mcp__claude_ai_Google_Calendar__list_events",
    "mcp__claude_ai_Google_Calendar__create_event", "mcp__claude_ai_Google_Calendar__update_event",
]
DISALLOWED_TOOLS = [
    "mcp__kweo__browser_run_task",
    "mcp__claude_ai_Google_Calendar__delete_event",
    "Write(~/.claude/skills/**)", "Edit(~/.claude/skills/**)",
]

KWEO_URL = "http://127.0.0.1:7333/mcp"
_KWEO_TOK = r"([A-Za-z0-9._~+/=-]{8,512})"
_KWEO_HDR = r"""--header (?:"Authorization: Bearer %s"|'Authorization: Bearer %s')""" % (_KWEO_TOK, _KWEO_TOK)
_KWEO_URL_RE = r"http://127\.0\.0\.1:7333/mcp"
KWEO_RES = [
    # what kweo's Connect panel shows (optionally with --scope user)
    re.compile(r"claude mcp add kweo --transport http %s (?:--scope user )?%s(?: --scope user)?" % (_KWEO_URL_RE, _KWEO_HDR)),
    # the order kweo itself runs it in
    re.compile(r"claude mcp add --transport http (?:--scope user )?%s kweo %s" % (_KWEO_HDR, _KWEO_URL_RE)),
    # kweo's JSON config snippet
    re.compile(r'\{ ?"mcpServers": ?\{ ?"kweo": ?\{ ?"type": ?"http", ?"url": ?"%s", ?'
               r'"headers": ?\{ ?"Authorization": ?"Bearer %s" ?\} ?\} ?\} ?\}' % (_KWEO_URL_RE, _KWEO_TOK)),
]

TEXT_FILES = ("plan.md", "trends.md", "voice.md", "account.md", "swipe.md", "log.md", "engaged.md")
PREVIEW_EXT = {".png", ".jpg", ".jpeg", ".webp", ".gif", ".mp4", ".mov", ".m4v", ".ics", ".md", ".txt", ".srt", ".zip"}
SAFE_INLINE = {
    ".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".gif": "image/gif",
    ".webp": "image/webp", ".mp4": "video/mp4", ".m4v": "video/mp4", ".mov": "video/quicktime",
    ".webm": "video/webm", ".mp3": "audio/mpeg", ".wav": "audio/wav", ".m4a": "audio/mp4",
    ".txt": "text/plain; charset=utf-8", ".md": "text/plain; charset=utf-8",
    ".srt": "text/plain; charset=utf-8", ".csv": "text/plain; charset=utf-8",
    ".json": "application/json; charset=utf-8", ".ics": "text/calendar; charset=utf-8",
}
STATIC_TYPES = {".html": "text/html; charset=utf-8", ".js": "text/javascript; charset=utf-8",
                ".css": "text/css; charset=utf-8", ".svg": "image/svg+xml", ".png": "image/png",
                ".ico": "image/x-icon", ".json": "application/json"}


# ---------------------------------------------------------------- locations

def ig_home():
    return os.path.expanduser(os.environ.get("IG_HOME") or "~/IGStudio")


def active_handle(home=None):
    home = home or ig_home()
    try:
        with open(os.path.join(home, "active-account"), encoding="utf-8") as f:
            h = f.read().strip().lstrip("@").strip().lower()
    except OSError:
        return None
    if h and re.fullmatch(r"[a-z0-9._]{1,30}", h) and ".." not in h \
            and os.path.isdir(os.path.join(home, "accounts", h)):
        return h
    return None


def data_dir():
    env = os.environ.get("IG_DATA_DIR")
    if env:
        return os.path.expanduser(env)
    home = ig_home()
    h = active_handle(home)
    return os.path.join(home, "accounts", h) if h else home


REPO_DIR = os.path.dirname(APP_DIR)
BUNDLED_SKILLS = os.path.join(REPO_DIR, "skills")
BUNDLED_AGENTS = os.path.join(REPO_DIR, "agents")


def claude_skills_dir():
    return os.path.expanduser(os.environ.get("IG_CLAUDE_SKILLS") or "~/.claude/skills")


def claude_agents_dir():
    return os.path.expanduser(os.environ.get("IG_CLAUDE_AGENTS") or "~/.claude/agents")


def skills_dir():
    """Where the scripts run from: IG_SKILLS_DIR, else Claude Code's skills folder
    if the pack is installed there, else the copy bundled with this repo, so a
    fresh download works before anything is installed."""
    env = os.environ.get("IG_SKILLS_DIR")
    if env:
        return os.path.expanduser(env)
    installed = claude_skills_dir()
    if os.path.isfile(os.path.join(installed, "ig", "state.py")):
        return installed
    if os.path.isfile(os.path.join(BUNDLED_SKILLS, "ig", "state.py")):
        return BUNDLED_SKILLS
    return installed


def _tree_digest(path):
    h = hashlib.sha256()
    for root, dirs, files in os.walk(path):
        dirs[:] = sorted(d for d in dirs if d not in ("__pycache__", "tests"))
        for f in sorted(files):
            if f.endswith(".pyc") or f == ".DS_Store":
                continue
            fp = os.path.join(root, f)
            h.update(os.path.relpath(fp, path).encode())
            try:
                with open(fp, "rb") as fh:
                    h.update(fh.read())
            except OSError:
                pass
    return h.hexdigest()


def install_status():
    """Compare the bundled skills with what Claude Code has installed."""
    if os.environ.get("IG_SKILLS_DIR") or not os.path.isdir(BUNDLED_SKILLS):
        return {"bundled": False, "needed": False, "missing": [], "outdated": []}
    inst = claude_skills_dir()
    missing, outdated = [], []
    for name in sorted(os.listdir(BUNDLED_SKILLS)):
        src = os.path.join(BUNDLED_SKILLS, name)
        if not (name.startswith("ig") and os.path.isfile(os.path.join(src, "SKILL.md"))):
            continue
        dst = os.path.join(inst, name)
        if not os.path.isdir(dst):
            missing.append(name)
        elif _tree_digest(src) != _tree_digest(dst):
            outdated.append(name)
    agents = claude_agents_dir()
    if os.path.isdir(BUNDLED_AGENTS):
        for f in sorted(os.listdir(BUNDLED_AGENTS)):
            if not f.endswith(".md"):
                continue
            dst = os.path.join(agents, f)
            try:
                with open(os.path.join(BUNDLED_AGENTS, f), "rb") as x, open(dst, "rb") as y:
                    same = x.read() == y.read()
            except OSError:
                missing.append("agent " + f[:-3])
                continue
            if not same:
                outdated.append("agent " + f[:-3])
    return {"bundled": True, "needed": bool(missing or outdated), "missing": missing,
            "outdated": outdated, "target": inst}


def install_skills():
    """Copy the bundled skills, platform.json and agents into Claude Code.
    Existing ig* skills are backed up first, never deleted."""
    inst, agents = claude_skills_dir(), claude_agents_dir()
    os.makedirs(inst, exist_ok=True)
    stamp = time.strftime("%Y%m%d-%H%M%S")
    backup = os.path.join(os.path.dirname(inst), "skills-backup", stamp)
    ignore = shutil.ignore_patterns("__pycache__", "*.pyc", ".DS_Store", "tests")
    done, backed = [], []
    for name in sorted(os.listdir(BUNDLED_SKILLS)):
        src = os.path.join(BUNDLED_SKILLS, name)
        if not (name.startswith("ig") and os.path.isfile(os.path.join(src, "SKILL.md"))):
            continue
        dst = os.path.join(inst, name)
        if os.path.isdir(dst):
            os.makedirs(backup, exist_ok=True)
            shutil.move(dst, os.path.join(backup, name))
            backed.append(name)
        shutil.copytree(src, dst, ignore=ignore)
        done.append(name)
    pj = os.path.join(REPO_DIR, "platform.json")
    if os.path.isfile(pj):
        shutil.copy2(pj, os.path.join(inst, "platform.json"))
    agent_files = []
    if os.path.isdir(BUNDLED_AGENTS):
        os.makedirs(agents, exist_ok=True)
        for f in sorted(os.listdir(BUNDLED_AGENTS)):
            if f.endswith(".md"):
                shutil.copy2(os.path.join(BUNDLED_AGENTS, f), os.path.join(agents, f))
                agent_files.append(f)
    return {"installed": done, "agents": agent_files, "target": inst,
            "backup": backup if backed else None}


def migrate_old_data_home():
    """Earlier versions kept data in ~/.claude/instagram. Claude Code protects
    ~/.claude, so runs started from IG Studio could not write there. Copy old
    data to the new home once, if the new one doesn't exist yet."""
    if os.environ.get("IG_HOME") or os.environ.get("IG_DATA_DIR"):
        return None
    old = os.path.expanduser("~/.claude/instagram")
    new = ig_home()
    if os.path.exists(new) or not os.path.isdir(old):
        return None
    try:
        shutil.copytree(old, new, ignore=shutil.ignore_patterns(".DS_Store"))
        return new
    except OSError:
        return None


def studio_home():
    return os.path.expanduser(os.environ.get("IG_STUDIO_HOME") or "~/.ig-studio")


def extra_paths():
    out = [os.path.expanduser("~/.local/bin")]
    if not IS_WIN:
        out += ["/opt/homebrew/bin", "/usr/local/bin"]
    return [p for p in out if os.path.isdir(p)]


def augment_path():
    """Apps started from Finder get a bare PATH. Add the usual tool folders."""
    cur = os.environ.get("PATH", "").split(os.pathsep)
    for p in extra_paths():
        if p not in cur:
            cur.append(p)
    os.environ["PATH"] = os.pathsep.join(x for x in cur if x)


def find_claude():
    env = os.environ.get("IG_CLAUDE_BIN")
    if env:
        return env if os.path.isfile(env) else None
    w = shutil.which("claude")
    if w:
        return w
    for p in ("~/.local/bin/claude", "~/.claude/local/claude"):
        p = os.path.expanduser(p)
        if os.path.isfile(p):
            return p
    return None


def find_chrome():
    env = os.environ.get("CHROME_PATH")
    if env and os.path.exists(env):
        return env
    cands = ["/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
             "/Applications/Chromium.app/Contents/MacOS/Chromium",
             "/Applications/Google Chrome Canary.app/Contents/MacOS/Google Chrome Canary",
             "/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge"]
    if IS_WIN:
        for base in (os.environ.get("PROGRAMFILES"), os.environ.get("PROGRAMFILES(X86)"),
                     os.environ.get("LOCALAPPDATA")):
            if base:
                cands.append(os.path.join(base, "Google", "Chrome", "Application", "chrome.exe"))
    for c in cands:
        if os.path.exists(c):
            return c
    for n in ("chromium", "google-chrome", "chromium-browser", "google-chrome-stable", "chrome"):
        w = shutil.which(n)
        if w:
            return w
    return None


def find_whisper():
    for n in ("whisper-cli", "whisper-cpp", "whisper"):
        w = shutil.which(n)
        if w:
            return w
    import importlib.util
    for mod in ("mlx_whisper", "faster_whisper"):
        try:
            if importlib.util.find_spec(mod):
                return mod + " (python)"
        except (ImportError, ValueError):
            pass
    return None


def child_env(with_data=True, extra=None):
    env = {k: v for k, v in os.environ.items() if k != "IG_ACCESS_TOKEN"}
    cur = env.get("PATH", "").split(os.pathsep)
    env["PATH"] = os.pathsep.join([x for x in cur if x] + [p for p in extra_paths() if p not in cur])
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    env["PYTHONIOENCODING"] = "utf-8"
    if with_data:
        env["IG_DATA_DIR"] = data_dir()
    else:
        env.pop("IG_DATA_DIR", None)
    if extra:
        env.update(extra)
    return env


def popen_kwargs():
    if IS_WIN:
        return {"creationflags": getattr(subprocess, "CREATE_NO_WINDOW", 0)
                | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)}
    return {"start_new_session": True}


# ---------------------------------------------------------------- safety helpers

class ApiError(Exception):
    def __init__(self, status, message, extra=None):
        super().__init__(message)
        self.status = status
        self.message = message
        self.extra = extra or {}


def within(path, root):
    """True when realpath(path) is root or inside it."""
    try:
        rp = os.path.realpath(path)
        rr = os.path.realpath(root)
    except (OSError, ValueError):
        return False
    return rp == rr or rp.startswith(rr.rstrip(os.sep) + os.sep)


def safe_data_path(path, must_exist=True):
    """Resolve a user-supplied path (absolute or relative to the data dir) inside the data dir."""
    if not isinstance(path, str) or not path or "\x00" in path:
        raise ApiError(400, "Missing or invalid path.")
    root = data_dir()
    p = os.path.expanduser(path)
    if not os.path.isabs(p):
        p = os.path.join(root, p)
    if not within(p, root):
        raise ApiError(403, "That file is outside the account's data folder.")
    rp = os.path.realpath(p)
    if must_exist and not os.path.exists(rp):
        raise ApiError(404, "File not found.")
    return rp


def sanitize_filename(name, allowed_ext=None):
    """Keep a safe basename: letters, digits, dot, dash, underscore. Returns '' if hopeless."""
    if not isinstance(name, str):
        return ""
    name = name.replace("\\", "/").split("/")[-1]
    name = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode("ascii")
    name = re.sub(r"[^A-Za-z0-9._-]+", "-", name)
    name = re.sub(r"-{2,}", "-", name).strip(".-_ ")
    name = re.sub(r"\.{2,}", ".", name)
    if not name:
        return ""
    stem, ext = os.path.splitext(name)
    ext = ext.lower()
    if allowed_ext is not None and ext not in allowed_ext:
        return ""
    stem = stem.strip(".-_")[:80] or "file"
    if stem.upper() in ("CON", "PRN", "AUX", "NUL") or re.fullmatch(r"(?i)(COM|LPT)\d", stem):
        stem = "_" + stem
    return stem + ext


def unique_path(folder, name):
    stem, ext = os.path.splitext(name)
    cand = os.path.join(folder, name)
    i = 2
    while os.path.exists(cand):
        cand = os.path.join(folder, f"{stem}-{i}{ext}")
        i += 1
    return cand


def validate_kweo_command(cmd):
    """Return the bearer token if cmd is kweo's connect command (or its JSON
    config snippet), else None. Tolerates what copy-paste does to it: smart
    quotes, line wraps, extra spaces, a leading "! ". Anything else, including
    a second command chained on, is refused. Only the token is used; the
    command itself is never run."""
    if not isinstance(cmd, str):
        return None
    cmd = cmd.strip()
    for a, b in (("\u201c", '"'), ("\u201d", '"'), ("\u2018", "'"), ("\u2019", "'"), ("\u00a0", " ")):
        cmd = cmd.replace(a, b)
    if cmd.startswith("! "):
        cmd = cmd[2:].strip()
    if any(c in cmd for c in ";&|`$<>()\\"):
        return None
    # A newline that isn't just a soft wrap (one command over several lines) is refused below
    # by the full match, since anything after the command makes it fail.
    cmd = re.sub(r"\s+", " ", cmd).strip()
    for rx in KWEO_RES:
        m = rx.fullmatch(cmd)
        if m:
            return next(g for g in m.groups() if g)
    return None


def check_id(value, what="id"):
    if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,24}", value or ""):
        raise ApiError(400, f"Invalid {what}.")
    return value


def flags(body, mapping):
    """{'views': 10} + {'views': '--views'} -> ['--views=10']. Empty values are skipped."""
    out = []
    for key, flag in mapping.items():
        v = body.get(key)
        if v is None or isinstance(v, (dict, list)):
            continue
        if isinstance(v, bool):
            if v:
                out.append(flag)
            continue
        s = str(v).strip()
        if not s:
            continue
        if len(s) > 2000 or "\x00" in s:
            raise ApiError(400, f"Value for {key} is too long.")
        out.append(f"{flag}={s}")
    return out


def parse_json_out(text):
    text = (text or "").strip()
    if not text:
        return None
    try:
        return json.loads(text)
    except ValueError:
        pass
    lines = text.splitlines()
    for i, line in enumerate(lines):
        if line.lstrip().startswith(("{", "[")):
            try:
                return json.loads("\n".join(lines[i:]))
            except ValueError:
                continue
    return None


def friendly_error(stderr, stdout=""):
    text = (stderr or "").strip() or (stdout or "").strip()
    lines = [l for l in text.splitlines() if l.strip()]
    for l in reversed(lines):
        m = re.search(r"error: (.*)$", l)
        if m:
            return m.group(1)
    return lines[-1][:400] if lines else "The script failed with no message."


# ---------------------------------------------------------------- script runner

def script_path(rel):
    p = os.path.join(skills_dir(), rel)
    return p if os.path.isfile(p) else None


def run_script(rel, args, stdin=None, timeout=90, with_data=True, env_extra=None):
    sp = script_path(rel)
    if not sp:
        raise ApiError(503, f"The skill script {rel} is not installed in {skills_dir()}.",
                       {"missing": rel})
    cwd = data_dir() if with_data else ig_home()
    try:
        os.makedirs(cwd, exist_ok=True)
    except OSError:
        cwd = None
    cmd = [sys.executable, "-I", sp] + list(args)
    try:
        r = subprocess.run(cmd, input=stdin, capture_output=True, text=True, encoding="utf-8",
                           errors="replace", timeout=timeout, cwd=cwd,
                           env=child_env(with_data, env_extra),
                           **({"creationflags": getattr(subprocess, "CREATE_NO_WINDOW", 0)} if IS_WIN else {}))
    except subprocess.TimeoutExpired:
        raise ApiError(504, f"{os.path.basename(rel)} took too long and was stopped.")
    except OSError as e:
        raise ApiError(500, f"Could not run {os.path.basename(rel)}: {e}")
    return {"rc": r.returncode, "out": r.stdout, "err": r.stderr, "json": parse_json_out(r.stdout)}


def script_json(rel, args, **kw):
    r = run_script(rel, args, **kw)
    if r["json"] is None:
        if r["rc"] != 0:
            raise ApiError(400, friendly_error(r["err"], r["out"]))
        raise ApiError(500, f"{os.path.basename(rel)} did not return JSON.")
    return r["json"]


def script_text(rel, args, **kw):
    r = run_script(rel, args, **kw)
    if r["rc"] != 0:
        raise ApiError(400, friendly_error(r["err"], r["out"]), {"output": (r["out"] + r["err"])[-4000:]})
    return {"ok": True, "output": (r["out"] or "").strip(), "log": (r["err"] or "").strip()[-4000:]}


# ---------------------------------------------------------------- jobs

class Job:
    def __init__(self, kind, title=""):
        self.id = secrets.token_hex(8)
        self.kind = kind
        self.title = title
        self.events = []
        self.cond = threading.Condition()
        self.done = False
        self.status = "running"
        self.proc = None
        self.cancelled = False
        self.created = time.time()
        self.result = None

    def emit(self, etype, **data):
        with self.cond:
            ev = {"seq": len(self.events), "type": etype}
            ev.update(data)
            self.events.append(ev)
            self.cond.notify_all()

    def finish(self, status, **data):
        with self.cond:
            if self.done:
                return
        self.status = status
        self.emit("end", status=status, **data)
        with self.cond:
            self.done = True
            self.cond.notify_all()

    def snapshot(self):
        return {"id": self.id, "kind": self.kind, "title": self.title, "status": self.status,
                "done": self.done, "result": self.result, "events": len(self.events)}


class JobRegistry:
    def __init__(self):
        self.jobs = {}
        self.lock = threading.Lock()

    def add(self, job):
        with self.lock:
            self.jobs[job.id] = job
            done = sorted((j for j in self.jobs.values() if j.done), key=lambda j: j.created)
            for j in done[:-60]:
                self.jobs.pop(j.id, None)
        return job

    def get(self, jid):
        with self.lock:
            return self.jobs.get(jid)

    def all(self):
        with self.lock:
            return list(self.jobs.values())


def kill_tree(proc):
    if proc is None or proc.poll() is not None:
        return
    try:
        if IS_WIN:
            subprocess.run(["taskkill", "/PID", str(proc.pid), "/T", "/F"], capture_output=True,
                           creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        else:
            try:
                os.killpg(proc.pid, signal.SIGTERM)
            except (ProcessLookupError, PermissionError):
                proc.terminate()
            for _ in range(30):
                if proc.poll() is not None:
                    return
                time.sleep(0.1)
            try:
                os.killpg(proc.pid, signal.SIGKILL)
            except (ProcessLookupError, PermissionError):
                proc.kill()
    except OSError:
        pass


def start_thread(fn, *a):
    t = threading.Thread(target=fn, args=a, daemon=True)
    t.start()
    return t


def run_process(job, cmd, env, cwd, timeout, stdin_text=None, redact=None, on_stdout_line=None):
    """Run cmd for a job, streaming stderr (and stdout if no handler) as log events.
    Returns (rc, stdout_text, stderr_text)."""
    def clean(s):
        for r in (redact or []):
            if r:
                s = s.replace(r, "***")
        return s

    try:
        proc = subprocess.Popen(cmd, stdin=subprocess.PIPE if stdin_text is not None else subprocess.DEVNULL,
                                stdout=subprocess.PIPE, stderr=subprocess.PIPE, cwd=cwd, env=env,
                                text=True, encoding="utf-8", errors="replace", bufsize=1, **popen_kwargs())
    except OSError as e:
        return -1, "", f"could not start: {e}"
    job.proc = proc
    if stdin_text is not None:
        def feed():
            try:
                proc.stdin.write(stdin_text)
                proc.stdin.close()
            except OSError:
                pass
        start_thread(feed)
    err_lines = []

    def read_err():
        for line in proc.stderr:
            line = clean(line.rstrip("\n"))
            err_lines.append(line)
            if line.strip():
                job.emit("log", line=line[:500])
    t_err = start_thread(read_err)

    timer = threading.Timer(timeout, lambda: (job.emit("log", line="Timed out, stopping."), kill_tree(proc)))
    timer.daemon = True
    timer.start()
    out = []
    for line in proc.stdout:
        line = clean(line)
        out.append(line)
        if on_stdout_line:
            on_stdout_line(line)
    proc.wait()
    timer.cancel()
    t_err.join(2)
    return proc.returncode, "".join(out), "\n".join(err_lines)


def run_script_job(job, rel, args, timeout=3600, env_extra=None, redact=None, after=None):
    """Background: run one skill script as a job. `after(rc, out, err)` -> result dict."""
    sp = script_path(rel)
    if not sp:
        job.finish("error", error=f"{rel} is not installed.")
        return
    os.makedirs(data_dir(), exist_ok=True)
    cmd = [sys.executable, "-I", sp] + list(args)
    job.emit("log", line=f"Running {os.path.basename(rel)}…")
    rc, out, err = run_process(job, cmd, child_env(True, env_extra), data_dir(), timeout, redact=redact)
    if job.cancelled:
        job.finish("cancelled")
        return
    try:
        result = after(rc, out, err) if after else {"output": out}
    except ApiError as e:
        job.finish("error", error=e.message)
        return
    except Exception as e:  # noqa: BLE001
        job.finish("error", error=f"{type(e).__name__}: {e}")
        return
    if rc != 0 and not (result or {}).get("ok_despite_rc"):
        job.result = result
        job.finish("error", error=friendly_error(err, out), result=result)
        return
    job.result = result
    job.emit("result", data=result)
    job.finish("done")


# ---------------------------------------------------------------- claude runs

def system_context():
    acct = active_handle()
    return (
        "You are running inside IG Studio, a local web app that is the front end for the ig- "
        "Instagram skills. The user reads your replies in a chat panel and answers there. Each of "
        "their messages arrives as a new turn of this same session, so when you need input or "
        "approval, ask clearly in one message and stop; they will reply (for example \"yes\") next turn. "
        "Follow the ig- skills' rules exactly. Never post, like, follow, unfollow, comment, reply, DM, "
        "save, share or send anything on Instagram or anywhere else. Browsing is read only. "
        "Ask before any calendar change and only act after the user said yes in a later message. "
        "Never write to ~/.claude/skills. "
        "Shell access is limited: run skill scripts as one plain command, `python3 /absolute/path/script.py ...` "
        "(or after `cd`), plus ffmpeg/ffprobe, ls, head, tail, wc, mkdir and date. Other commands are denied, so "
        "use the Read tool to read files and the Write tool to put text in a file in the data folder, then pass "
        "that file's path to the script instead of piping text into it. "
        f"The active account is {'@' + acct if acct else 'the single default account'}; its data folder is "
        f"{data_dir()} and every file you make goes there. When you create files (images, videos, .ics, "
        "markdown), mention their full absolute paths so the app can preview them. Keep replies short and "
        "scannable: short paragraphs, lists, and fenced blocks only for copy-ready text. The app's home is the "
        "Week screen, drawn from week.json (see the ig skill's Autopilot section): when the user asks to change "
        "a planned post, edit that post in week.json and run week.py check --fix. Every planned post copies a "
        "reel that went viral in the niche (its `model`, an id in viral.json): write in that reel's shape and "
        "tone, never in the style of the account's own old posts. Every day the app also adds one trend reel "
        "that rides what everyone is talking about (the ig skill's Daily section). There is also a Results "
        "screen (account scan, posts, growth, trends and what's going viral) and Settings."
    )


DIRECT_STEPS = {"analyze": "Watching the footage: transcript, pauses, frames",
                "merge": "Merging the edit plan", "check": "Scoring the virality checklist",
                "storyboard": "Rendering the storyboard", "render": "Rendering the Reel",
                "fonts": "Getting caption fonts"}
DIRECT_AGENTS = {"ig-cut-editor": "Cut editor: picking shots, hook and pacing",
                 "ig-caption-designer": "Caption designer: style, size, placement",
                 "ig-look-designer": "Look designer: grade and mood",
                 "ig-sound-designer": "Sound designer: SFX and trending sounds",
                 "ig-retention-critic": "Critic: watching it like a scroller"}


def tool_summary(name, inp):
    inp = inp if isinstance(inp, dict) else {}
    if name == "Bash":
        cmd = str(inp.get("command", ""))
        d = re.search(r"direct\.py\s+(analyze|merge|check|storyboard|render|fonts)\b", cmd)
        if d:
            return DIRECT_STEPS[d.group(1)]
        m = re.search(r"([\w.-]+\.py)\b", cmd)
        if m:
            return f"Running {m.group(1)}"
        if re.search(r"\bffmpeg\b", cmd):
            return "Running ffmpeg"
        if re.search(r"\bffprobe\b", cmd):
            return "Running ffprobe"
        return (inp.get("description") or cmd)[:80]
    if name in ("Read", "Write", "Edit"):
        verb = {"Read": "Reading", "Write": "Writing", "Edit": "Editing"}[name]
        return f"{verb} {os.path.basename(str(inp.get('file_path', '')))}"
    if name in ("Glob", "Grep"):
        return "Searching files"
    if name == "WebSearch":
        return f"Searching the web: {str(inp.get('query', ''))[:60]}"
    if name == "WebFetch":
        host = urllib.parse.urlparse(str(inp.get("url", ""))).netloc
        return f"Reading {host or 'a web page'}"
    if name == "Skill":
        return f"Using /{inp.get('skill') or inp.get('command') or 'skill'}"
    if name in ("Task", "Agent"):
        sub = inp.get("subagent_type") or ""
        if sub in DIRECT_AGENTS:
            return DIRECT_AGENTS[sub]
        return f"Starting helper: {sub or inp.get('description') or 'agent'}"
    if name == "ToolSearch":
        return "Loading tools"
    if name.startswith("mcp__kweo__"):
        return f"Browsing with kweo ({name.split('__')[-1].replace('browser_', '').replace('_', ' ')})"
    if name.startswith("mcp__claude_ai_Google_Calendar__"):
        return f"Google Calendar: {name.split('__')[-1].replace('_', ' ')}"
    return name


PATH_RE = re.compile(r"((?:~|/)[^\s`'\"<>|*?()\[\]]+?\.(?:png|jpe?g|webp|gif|mp4|mov|m4v|ics|md|txt|srt|zip))\b",
                     re.IGNORECASE)


def file_kind(path):
    ext = os.path.splitext(path)[1].lower()
    if ext in (".png", ".jpg", ".jpeg", ".webp", ".gif"):
        return "image"
    if ext in (".mp4", ".mov", ".m4v", ".webm"):
        return "video"
    if ext == ".ics":
        return "calendar"
    return "file"


class ChatRun:
    """Translate claude's stream-json into UI events."""

    def __init__(self, job, server, started):
        self.job = job
        self.server = server
        self.started = started
        self.session_id = None
        self.delta_msgs = set()
        self.cur_msg = None
        self.files = set()
        self.final = None
        self.is_error = False

    def offer_file(self, raw):
        if len(self.files) >= 24:
            return
        p = os.path.expanduser(raw.rstrip(".,:;"))
        if not os.path.isabs(p):
            return
        try:
            if not within(p, data_dir()) or not os.path.isfile(p):
                return
        except OSError:
            return
        rp = os.path.realpath(p)
        if rp in self.files:
            return
        self.files.add(rp)
        self.job.emit("file", path=rp, name=os.path.basename(rp), kind=file_kind(rp),
                      url=self.server.file_url(rp), download=self.server.file_url(rp, download=True))

    def scan_text(self, text):
        for m in PATH_RE.finditer(text or ""):
            self.offer_file(m.group(1))

    def line(self, raw):
        raw = raw.strip()
        if not raw:
            return
        try:
            d = json.loads(raw)
        except ValueError:
            return
        t = d.get("type")
        if d.get("session_id") and not self.session_id:
            self.session_id = d["session_id"]
            self.job.emit("session", session_id=self.session_id)
        if t == "stream_event":
            ev = d.get("event") or {}
            et = ev.get("type")
            if et == "message_start":
                self.cur_msg = (ev.get("message") or {}).get("id")
            elif et == "content_block_delta":
                delta = ev.get("delta") or {}
                if delta.get("type") == "text_delta" and delta.get("text") and not d.get("parent_tool_use_id"):
                    self.delta_msgs.add(self.cur_msg)
                    self.job.emit("text", text=delta["text"])
            elif et == "content_block_start":
                cb = ev.get("content_block") or {}
                if cb.get("type") == "text" and not d.get("parent_tool_use_id") and self.cur_msg in self.delta_msgs:
                    self.job.emit("text", text="\n\n")
        elif t == "assistant":
            msg = d.get("message") or {}
            sub = bool(d.get("parent_tool_use_id"))
            for block in msg.get("content") or []:
                bt = block.get("type")
                if bt == "text":
                    if not sub and msg.get("id") not in self.delta_msgs:
                        self.job.emit("text", text=block.get("text", ""))
                    self.scan_text(block.get("text", ""))
                elif bt == "tool_use":
                    name = block.get("name", "")
                    inp = block.get("input") or {}
                    self.job.emit("tool", id=block.get("id"), name=name, summary=tool_summary(name, inp),
                                  sub=sub)
                    for k in ("file_path", "path"):
                        if isinstance(inp.get(k), str):
                            self.scan_text(inp[k] if "." in inp[k] else "")
                    if name == "Bash":
                        self.scan_text(str(inp.get("command", "")))
        elif t == "user":
            msg = d.get("message") or {}
            for block in msg.get("content") or [] if isinstance(msg.get("content"), list) else []:
                if block.get("type") == "tool_result":
                    self.job.emit("tool_done", id=block.get("tool_use_id"), error=bool(block.get("is_error")))
                    c = block.get("content")
                    if isinstance(c, str):
                        self.scan_text(c[:20000])
                    elif isinstance(c, list):
                        for part in c:
                            if isinstance(part, dict) and part.get("type") == "text":
                                self.scan_text(str(part.get("text", ""))[:20000])
        elif t == "result":
            self.final = d
            self.is_error = bool(d.get("is_error"))
            if d.get("session_id"):
                self.session_id = d["session_id"]
            self.scan_text(str(d.get("result") or ""))

    def sweep_new_files(self):
        """Files the run made in the data folder (render output etc.)."""
        root = data_dir()
        found = []
        try:
            for dirpath, dirnames, filenames in os.walk(root):
                depth = os.path.relpath(dirpath, root).count(os.sep)
                dirnames[:] = [x for x in dirnames if not x.startswith(".") and x != "uploads"
                               and x != "backup" and depth < 3]
                for fn in filenames:
                    ext = os.path.splitext(fn)[1].lower()
                    if ext not in PREVIEW_EXT:
                        continue
                    p = os.path.join(dirpath, fn)
                    try:
                        if os.path.getmtime(p) >= self.started - 1:
                            found.append(p)
                    except OSError:
                        pass
                if len(found) > 200:
                    break
        except OSError:
            return
        for p in sorted(found)[:24]:
            self.offer_file(p)


def run_chat_job(job, server, prompt, session_id, extra_tools=None, after_ok=None):
    claude = find_claude()
    if not claude:
        job.finish("error", error="Claude Code is not installed. Install it from https://claude.com/claude-code.")
        return
    cwd = data_dir()
    os.makedirs(cwd, exist_ok=True)
    cmd = [claude, "-p", "--output-format", "stream-json", "--verbose", "--include-partial-messages",
           "--add-dir", skills_dir(),
           "--append-system-prompt", system_context(),
           "--allowedTools", ",".join(ALLOWED_TOOLS + list(extra_tools or [])),
           "--disallowedTools", ",".join(DISALLOWED_TOOLS),
           "--permission-mode", "dontAsk"]
    if session_id:
        cmd += ["--resume", session_id]
    started = time.time()
    run = ChatRun(job, server, started)
    rc, out, err = run_process(job, cmd, child_env(True), cwd, timeout=3 * 3600, stdin_text=prompt,
                               on_stdout_line=run.line)
    if job.cancelled:
        job.finish("cancelled", session_id=run.session_id)
        return
    run.sweep_new_files()
    if rc != 0 or run.final is None or run.is_error:
        msg = ""
        if run.final:
            msg = str(run.final.get("result") or "")
        if not msg:
            msg = friendly_error(err, "") if err.strip() else f"Claude stopped (exit code {rc})."
        if "login" in msg.lower() or "logged in" in msg.lower():
            msg += " Open a terminal and run `claude` once to log in."
        job.finish("error", error=msg[:2000], session_id=run.session_id)
        return
    job.result = {"session_id": run.session_id, "cost_usd": run.final.get("total_cost_usd"),
                  "turns": run.final.get("num_turns")}
    if after_ok:
        try:
            after_ok(job, run)
        except ApiError as e:
            job.finish("cancelled" if job.cancelled else "error", error=e.message, session_id=run.session_id)
            return
        except Exception as e:  # noqa: BLE001
            job.finish("error", error=f"{type(e).__name__}: {e}", session_id=run.session_id)
            return
    job.emit("result", data=job.result)
    job.finish("done", session_id=run.session_id)


# ---------------------------------------------------------------- lock (single instance)

def lock_file():
    return os.path.join(studio_home(), "lock.json")


def read_lock():
    try:
        with open(lock_file(), encoding="utf-8") as f:
            d = json.load(f)
        if isinstance(d, dict) and isinstance(d.get("port"), int) and isinstance(d.get("token"), str):
            return d
    except (OSError, ValueError):
        pass
    return None


def pid_alive(pid):
    if not isinstance(pid, int) or pid <= 0:
        return False
    if IS_WIN:
        return True  # rely on the ping
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except OSError:
        return False


def ping(port, token, timeout=1.5):
    try:
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        req = urllib.request.Request(f"http://127.0.0.1:{port}/api/ping", headers={"X-IG-Token": token})
        with opener.open(req, timeout=timeout) as r:
            return json.loads(r.read().decode()).get("app") == "ig-studio"
    except Exception:  # noqa: BLE001
        return False


def running_instance():
    lk = read_lock()
    if lk and pid_alive(lk.get("pid")) and ping(lk["port"], lk["token"]):
        return lk
    return None


def write_lock(port, token):
    home = studio_home()
    os.makedirs(home, exist_ok=True)
    try:
        os.chmod(home, 0o700)
    except OSError:
        pass
    tmp = lock_file() + f".{os.getpid()}.tmp"
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        json.dump({"pid": os.getpid(), "port": port, "token": token,
                   "started": dt.datetime.now().isoformat(timespec="seconds")}, f)
    os.replace(tmp, lock_file())


def release_lock(token):
    lk = read_lock()
    if lk and lk.get("token") == token:
        try:
            os.remove(lock_file())
        except OSError:
            pass


# ---------------------------------------------------------------- HTTP

class StudioServer(http.server.ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = False

    def __init__(self, port, token):
        super().__init__(("127.0.0.1", port), Handler)
        self.port = self.server_address[1]
        self.token = token
        self.jobs = JobRegistry()
        self.allowed_hosts = {f"127.0.0.1:{self.port}", f"localhost:{self.port}"}
        self.allowed_origins = {f"http://{h}" for h in self.allowed_hosts}
        self._claude_version = None

    def sign(self, path):
        return hmac.new(self.token.encode(), ("file:" + path).encode(), hashlib.sha256).hexdigest()[:32]

    def file_url(self, path, download=False):
        rp = os.path.realpath(path)
        q = {"path": rp, "sig": self.sign(rp)}
        if download:
            q["download"] = "1"
        return "/api/file?" + urllib.parse.urlencode(q)

    def zip_url(self, folder):
        rp = os.path.realpath(folder)
        return "/api/zip?" + urllib.parse.urlencode({"dir": rp, "sig": self.sign("zip:" + rp)})

    def url(self):
        return f"http://127.0.0.1:{self.port}/"

    def shutdown_all(self):
        for j in self.jobs.all():
            if not j.done:
                j.cancelled = True
                kill_tree(j.proc)


def open_browser(url):
    """Open the default browser. On macOS use `open` (LaunchServices): Python's
    webbrowser sends an AppleScript 'open location' that some browsers, kweo
    among them, ignore until they are brought to the front."""
    if sys.platform == "darwin":
        try:
            subprocess.run(["open", url], timeout=15, check=False,
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            return
        except (OSError, subprocess.SubprocessError):
            pass
    webbrowser.open(url)


def default_browser_id():
    """macOS: bundle id of the default http handler, e.g. ai.kweo.browser."""
    import plistlib
    p = os.path.expanduser("~/Library/Preferences/com.apple.LaunchServices/"
                           "com.apple.launchservices.secure.plist")
    try:
        with open(p, "rb") as f:
            for h in plistlib.load(f).get("LSHandlers", []):
                if h.get("LSHandlerURLScheme") in ("http", "https"):
                    return h.get("LSHandlerRoleAll")
    except (OSError, ValueError, plistlib.InvalidFileException):
        pass
    return None


def app_running(bundle_id):
    try:
        r = subprocess.run(["osascript", "-e", f'application id "{bundle_id}" is running'],
                           capture_output=True, text=True, timeout=10)
        return r.stdout.strip() == "true"
    except (OSError, subprocess.SubprocessError):
        return None


def warm_up_browser(timeout=25, settle=4):
    """macOS: if the default browser is closed, start it first and give it time
    to finish launching. Several browsers (kweo among them) drop a link handed
    to them while they are still starting, leaving a tab that never loads.
    Returns True when a cold start happened."""
    if sys.platform != "darwin":
        return False
    bid = default_browser_id()
    if not bid or not re.fullmatch(r"[A-Za-z0-9.\-]+", bid) or app_running(bid) is not False:
        return False
    try:
        subprocess.run(["open", "-g", "-b", bid], timeout=15,
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except (OSError, subprocess.SubprocessError):
        return False
    deadline = time.time() + timeout
    while time.time() < deadline and not app_running(bid):
        time.sleep(0.5)
    time.sleep(settle)
    return True


def open_and_confirm(srv, url, waits=(6, 6)):
    """Open the browser, then make sure it really arrived. Some browsers (kweo
    in testing) occasionally create the tab but never send the request. If no
    request reaches the server, open again; if that fails too, use another
    installed browser on macOS and say so in the console."""
    start = getattr(srv, "requests_seen", 0)
    if warm_up_browser():
        waits = tuple(w + 4 for w in waits)
    open_browser(url)
    for i, wait in enumerate(waits):
        deadline = time.time() + wait
        while time.time() < deadline:
            if getattr(srv, "requests_seen", 0) > start:
                return True
            time.sleep(0.25)
        if i + 1 < len(waits):
            open_browser(url)
    if sys.platform == "darwin":
        for app in ("Google Chrome", "Safari", "Firefox", "Arc", "Microsoft Edge", "Brave Browser"):
            try:
                r = subprocess.run(["open", "-a", app, url], timeout=15,
                                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            except (OSError, subprocess.SubprocessError):
                continue
            if r.returncode == 0:
                try:
                    print(f"Your default browser did not load IG Studio, so it opened in {app}.")
                    sys.stdout.flush()
                except (OSError, ValueError):
                    pass
                return False
    try:
        print("If no page opened, paste the address above into your browser.")
        sys.stdout.flush()
    except (OSError, ValueError):
        pass
    return False


# ---------------------------------------------------------------- whisper setup
#
# Word-timed captions need a local Whisper. On every start IG Studio checks for
# one and, if missing, installs it in the background so the app stays usable:
#   macOS with Homebrew : brew install whisper-cpp + the multilingual base model
#   everything else     : a private venv in ~/.ig-studio with faster-whisper
# Nothing needs admin rights. Progress goes to /api/status and setup.log.

WHISPER_MODEL_URL = "https://huggingface.co/ggerganov/whisper.cpp/resolve/main/ggml-base.bin"
WHISPER_MODEL_MIN_BYTES = 100 * 1024 * 1024


class WhisperSetup:
    def __init__(self):
        self.state = "idle"        # idle | checking | installing | ready | failed | skipped
        self.step = ""
        self.error = ""
        self.method = ""
        self.progress = None       # 0-100 while downloading
        self._lock = threading.Lock()

    def snapshot(self):
        return {"state": self.state, "step": self.step, "error": self.error,
                "method": self.method, "progress": self.progress}

    def _log(self, msg):
        try:
            os.makedirs(studio_home(), exist_ok=True)
            with open(os.path.join(studio_home(), "setup.log"), "a", encoding="utf-8") as f:
                f.write(time.strftime("%F %T ") + msg.rstrip() + "\n")
        except OSError:
            pass

    def _set(self, state=None, step=None, **kw):
        if state:
            self.state = state
        if step is not None:
            self.step = step
            self._log(f"[{self.state}] {step}")
        for k, v in kw.items():
            setattr(self, k, v)

    def check(self):
        script = script_path("ig-edit/edit.py")
        if not script:
            return None
        try:
            r = subprocess.run([sys.executable, "-I", script, "--whisper-check"], capture_output=True,
                               text=True, timeout=60, env=child_env(False))
            return json.loads(r.stdout.strip().splitlines()[-1]) if r.stdout.strip() else None
        except (OSError, subprocess.SubprocessError, ValueError, IndexError):
            return None

    def _run(self, cmd, timeout=1800, env_extra=None):
        env = child_env(False, env_extra)
        self._log("$ " + " ".join(cmd))
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, env=env)
        self._log((r.stdout or "")[-2000:] + (r.stderr or "")[-2000:])
        return r

    def _download_model(self):
        dest_dir = os.path.join(studio_home(), "models")
        os.makedirs(dest_dir, exist_ok=True)
        dest = os.path.join(dest_dir, "ggml-base.bin")
        if os.path.exists(dest) and os.path.getsize(dest) >= WHISPER_MODEL_MIN_BYTES:
            return dest
        tmp = dest + ".part"
        self._set(step="Downloading the speech model (about 150 MB)", progress=0)
        req = urllib.request.Request(WHISPER_MODEL_URL, headers={"User-Agent": "IG-Studio"})
        with urllib.request.urlopen(req, timeout=60) as r, open(tmp, "wb") as f:
            total = int(r.headers.get("Content-Length") or 0)
            done = 0
            while True:
                chunk = r.read(1 << 20)
                if not chunk:
                    break
                f.write(chunk)
                done += len(chunk)
                if total:
                    self.progress = int(done * 100 / total)
        if os.path.getsize(tmp) < WHISPER_MODEL_MIN_BYTES:
            os.remove(tmp)
            raise RuntimeError("the speech model download was incomplete")
        os.replace(tmp, dest)
        self.progress = None
        return dest

    def _brew(self):
        for b in (shutil.which("brew"), "/opt/homebrew/bin/brew", "/usr/local/bin/brew"):
            if b and os.path.exists(b):
                return b
        return None

    def _install_brew(self, brew):
        self.method = "whisper.cpp (Homebrew)"
        st = self.check() or {}
        if not st.get("whisper_cpp_without_model"):
            self._set(step="Installing whisper.cpp with Homebrew (a few minutes)")
            r = self._run([brew, "install", "whisper-cpp"], env_extra={
                "HOMEBREW_NO_AUTO_UPDATE": "1", "NONINTERACTIVE": "1", "HOMEBREW_NO_INSTALL_CLEANUP": "1"})
            if r.returncode != 0:
                raise RuntimeError("brew install whisper-cpp failed: " + (r.stderr or r.stdout or "").strip()[-300:])
        self._download_model()

    def _install_venv(self):
        self.method = "faster-whisper (private Python env)"
        venv = os.path.join(studio_home(), "whisper-venv")
        py = os.path.join(venv, "Scripts", "python.exe") if IS_WIN else os.path.join(venv, "bin", "python")
        if not os.path.exists(py):
            self._set(step="Creating a private Python environment")
            r = self._run([sys.executable, "-m", "venv", venv], timeout=300)
            if r.returncode != 0:
                raise RuntimeError("could not create the Python environment: " + (r.stderr or "").strip()[-300:])
        self._set(step="Installing faster-whisper (a few minutes)")
        r = self._run([py, "-m", "pip", "install", "--disable-pip-version-check", "--quiet", "faster-whisper"])
        if r.returncode != 0:
            raise RuntimeError("pip install faster-whisper failed: " + (r.stderr or "").strip()[-300:])
        self._set(step="Downloading the speech model (about 150 MB)")
        r = self._run([py, "-c", "from faster_whisper import WhisperModel; "
                       "WhisperModel('base', device='cpu', compute_type='int8')"])
        if r.returncode != 0:
            raise RuntimeError("could not download the speech model: " + (r.stderr or "").strip()[-300:])

    def run(self):
        if not self._lock.acquire(blocking=False):
            return
        try:
            self._set("checking", "Checking for Whisper", error="")
            st = self.check()
            if st is None:
                self._set("skipped", "The video editor skill isn't installed yet")
                return
            if st.get("ready"):
                self._set("ready", "Whisper is ready", method=(st.get("transcriber") or {}).get("kind", ""))
                return
            self._set("installing", "Starting Whisper setup")
            brew = self._brew() if sys.platform == "darwin" else None
            if brew:
                try:
                    self._install_brew(brew)
                except Exception as e:  # noqa: BLE001 - fall back to the venv route
                    self._log(f"Homebrew route failed, trying the private env: {e}")
                    self._install_venv()
            else:
                self._install_venv()
            st = self.check() or {}
            if st.get("ready"):
                self._set("ready", "Whisper is ready. Captions follow your exact words now.")
            else:
                self._set("failed", "Whisper was installed but the editor can't use it yet",
                          error="See ~/.ig-studio/setup.log")
        except Exception as e:  # noqa: BLE001 - report any failure to the page
            self._set("failed", "Whisper setup failed", error=str(e)[:400], progress=None)
        finally:
            self._lock.release()


WHISPER = WhisperSetup()


def launch_url(port, token):
    """The one-time link the launcher opens. The page itself ends up at a clean /."""
    return f"http://127.0.0.1:{port}/open?t={token}"


ROUTES = {}


def route(method, path):
    def deco(fn):
        ROUTES[(method, path)] = fn
        return fn
    return deco


class Handler(http.server.BaseHTTPRequestHandler):
    server_version = "IGStudio/" + VERSION
    sys_version = ""

    def log_message(self, fmt, *args):  # quiet; never log query strings (tokens, paths)
        line = "%s %s %s" % (time.strftime("%H:%M:%S"), self.command, self.path.split("?")[0].split("#")[0])
        if os.environ.get("IG_STUDIO_DEBUG"):
            sys.stderr.write("[ig-studio] %s\n" % line)
        try:  # small rolling access log for troubleshooting: paths only, never tokens
            lp = os.path.join(studio_home(), "access.log")
            if os.path.exists(lp) and os.path.getsize(lp) > 256 * 1024:
                os.replace(lp, lp + ".1")
            with open(lp, "a", encoding="utf-8") as f:
                f.write(line + " " + " ".join(str(a) for a in args[1:2]) + "\n")
        except OSError:
            pass

    # ---- responses
    def _common_headers(self):
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("Cache-Control", "no-store")

    def send_json(self, obj, status=200):
        data = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self._common_headers()
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(data)

    def send_err(self, status, message, extra=None):
        body = {"error": message}
        body.update(extra or {})
        self.send_json(body, status)

    # ---- request plumbing
    def handle_one_request(self):
        try:
            super().handle_one_request()
        except (BrokenPipeError, ConnectionResetError):
            self.close_connection = True

    def do_GET(self):
        self.dispatch("GET")

    def do_HEAD(self):
        self.dispatch("GET")

    def do_POST(self):
        self.dispatch("POST")

    def do_PUT(self):
        self.send_err(405, "Method not allowed.")

    do_DELETE = do_PUT
    do_PATCH = do_PUT
    do_OPTIONS = do_PUT

    def host_ok(self):
        return self.headers.get("Host", "") in self.server.allowed_hosts

    def _cookie_token(self):
        raw = self.headers.get("Cookie", "")
        for part in raw.split(";"):
            k, _, v = part.strip().partition("=")
            if k == "igt":
                return v
        return ""

    def token_ok(self, method="GET"):
        want = self.server.token.encode()
        tok = self.headers.get("X-IG-Token", "")
        if tok and hmac.compare_digest(tok.encode(), want):
            return True
        ck = self._cookie_token()
        if not (ck and hmac.compare_digest(ck.encode(), want)):
            return False
        # Cookie-only auth on a write must come from this page: SameSite=Strict
        # already blocks other sites, and this rejects a write with no Origin.
        if method != "GET" and self.headers.get("Origin") not in self.server.allowed_origins:
            return False
        return True

    def open_with_token(self):
        """/open?t=TOKEN: swap the launch token for a cookie, then go to a clean URL."""
        tok = self.query.get("t", "")
        if not (tok and hmac.compare_digest(tok.encode(), self.server.token.encode())):
            body = ("<!doctype html><meta charset=utf-8><title>IG Studio</title>"
                    "<p style='font:16px system-ui;margin:40px'>This IG Studio link has expired. "
                    "Open IG Studio again from its launcher.</p>").encode()
            self.send_response(403)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)
            return
        self.send_response(303)
        self.send_header("Set-Cookie", "igt=%s; Path=/; Max-Age=2592000; HttpOnly; SameSite=Strict" % self.server.token)
        self.send_header("Location", "/")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("Content-Length", "0")
        self.end_headers()

    def dispatch(self, method):
        self.server.requests_seen = getattr(self.server, "requests_seen", 0) + 1
        if not self.host_ok():
            self.send_err(403, "Bad host.")
            return
        parsed = urllib.parse.urlsplit(self.path)
        path = parsed.path
        self.query = {k: v[-1] for k, v in urllib.parse.parse_qs(parsed.query, keep_blank_values=True).items()}
        if path == "/open" and method == "GET":
            self.open_with_token()
            return
        if not path.startswith("/api/"):
            if method != "GET":
                self.send_err(405, "Method not allowed.")
                return
            self.serve_static(path)
            return
        origin = self.headers.get("Origin")
        if origin and origin not in self.server.allowed_origins:
            self.send_err(403, "Cross-origin requests are not allowed.")
            return
        signed = path in ("/api/file", "/api/zip") and method == "GET"
        if not self.token_ok(method) and not (signed and self.sig_ok(path)):
            self.send_err(401, "Missing or wrong token. Open IG Studio from its launcher.")
            return
        try:
            if path.startswith("/api/jobs/"):
                self.job_route(method, path)
                return
            fn = ROUTES.get((method, path))
            if not fn:
                self.send_err(404, "Unknown endpoint.")
                return
            body = {}
            if method == "POST" and path != "/api/upload":
                body = self.read_json()
            res = fn(self, body)
            if res is not None:
                self.send_json(res)
        except ApiError as e:
            self.send_err(e.status, e.message, e.extra)
        except (BrokenPipeError, ConnectionResetError):
            pass
        except Exception as e:  # noqa: BLE001
            if os.environ.get("IG_STUDIO_DEBUG"):
                import traceback
                traceback.print_exc()
            try:
                self.send_err(500, f"Something went wrong: {type(e).__name__}: {e}")
            except OSError:
                pass

    def sig_ok(self, path):
        sig = self.query.get("sig", "")
        if path == "/api/file":
            p = self.query.get("path", "")
            target = os.path.realpath(p) if p else ""
        else:
            p = self.query.get("dir", "")
            target = "zip:" + os.path.realpath(p) if p else ""
        if not sig or not target:
            return False
        return hmac.compare_digest(sig, self.server.sign(target))

    def read_json(self):
        try:
            n = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            raise ApiError(400, "Bad Content-Length.")
        if n > MAX_JSON_BODY:
            raise ApiError(413, "Request too large.")
        if n == 0:
            return {}
        ctype = self.headers.get("Content-Type", "")
        if "application/json" not in ctype:
            raise ApiError(415, "Send JSON.")
        raw = self.rfile.read(n)
        try:
            data = json.loads(raw.decode("utf-8"))
        except (ValueError, UnicodeDecodeError):
            raise ApiError(400, "Invalid JSON.")
        if not isinstance(data, dict):
            raise ApiError(400, "Expected a JSON object.")
        return data

    # ---- static
    def serve_static(self, path):
        if path in ("", "/"):
            path = "/index.html"
        rel = urllib.parse.unquote(path).lstrip("/")
        full = os.path.join(WEB_DIR, rel)
        if not within(full, WEB_DIR) or not os.path.isfile(full):
            self.send_err(404, "Not found.")
            return
        ext = os.path.splitext(full)[1].lower()
        with open(full, "rb") as f:
            data = f.read()
        self.send_response(200)
        self.send_header("Content-Type", STATIC_TYPES.get(ext, "application/octet-stream"))
        self.send_header("Content-Length", str(len(data)))
        self._common_headers()
        if ext == ".html":
            self.send_header("Content-Security-Policy",
                             "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; "
                             "img-src 'self' data: blob:; media-src 'self' blob:; connect-src 'self'; "
                             "object-src 'none'; base-uri 'none'; frame-ancestors 'none'; form-action 'none'")
            self.send_header("X-Frame-Options", "DENY")
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(data)

    # ---- jobs + SSE
    def job_route(self, method, path):
        m = re.fullmatch(r"/api/jobs/([0-9a-f]{16})(/events|/cancel)?", path)
        if not m:
            raise ApiError(404, "Unknown job endpoint.")
        job = self.server.jobs.get(m.group(1))
        if not job:
            raise ApiError(404, "That job is gone. It may have finished a while ago.")
        what = m.group(2)
        if what == "/events" and method == "GET":
            self.stream_job(job)
        elif what == "/cancel" and method == "POST":
            job.cancelled = True
            kill_tree(job.proc)
            if job.proc is None:
                job.finish("cancelled")
            self.send_json({"ok": True})
        elif what is None and method == "GET":
            self.send_json(job.snapshot())
        else:
            raise ApiError(405, "Method not allowed.")

    def stream_job(self, job):
        try:
            if "from" in self.query:
                i = int(self.query["from"])
            else:
                i = int(self.headers.get("Last-Event-ID", "-1")) + 1
        except ValueError:
            i = 0
        i = max(0, i)
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream; charset=utf-8")
        self.send_header("X-Accel-Buffering", "no")
        self._common_headers()
        self.end_headers()
        self.close_connection = True
        try:
            while True:
                with job.cond:
                    if i >= len(job.events) and not job.done:
                        job.cond.wait(15)
                    evs = job.events[i:]
                    done = job.done
                if evs:
                    buf = "".join(f"id: {e['seq']}\nevent: {e['type']}\ndata: {json.dumps(e, ensure_ascii=False)}\n\n"
                                  for e in evs)
                    self.wfile.write(buf.encode("utf-8"))
                    i += len(evs)
                else:
                    self.wfile.write(b": ping\n\n")
                self.wfile.flush()
                if done and i >= len(job.events):
                    break
        except (BrokenPipeError, ConnectionResetError, OSError):
            pass

    def new_job(self, kind, title=""):
        return self.server.jobs.add(Job(kind, title))

    # ---- file serving
    def serve_file(self, path, download):
        rp = safe_data_path(path)
        if not os.path.isfile(rp):
            raise ApiError(404, "Not a file.")
        ext = os.path.splitext(rp)[1].lower()
        ctype = SAFE_INLINE.get(ext)
        attach = download or ctype is None
        if ctype is None:
            ctype = "application/octet-stream"
        size = os.path.getsize(rp)
        start, end = 0, size - 1
        status = 200
        rng = self.headers.get("Range")
        if rng and size > 0:
            m = re.fullmatch(r"bytes=(\d*)-(\d*)", rng.strip())
            if not m or (m.group(1) == "" and m.group(2) == ""):
                self.send_response(416)
                self.send_header("Content-Range", f"bytes */{size}")
                self.send_header("Content-Length", "0")
                self.end_headers()
                return
            if m.group(1) == "":
                start = max(0, size - int(m.group(2)))
            else:
                start = int(m.group(1))
                if m.group(2):
                    end = min(int(m.group(2)), size - 1)
            if start > end or start >= size:
                self.send_response(416)
                self.send_header("Content-Range", f"bytes */{size}")
                self.send_header("Content-Length", "0")
                self.end_headers()
                return
            status = 206
        length = end - start + 1 if size else 0
        self.send_response(status)
        self.send_header("Content-Type", ctype)
        self.send_header("Accept-Ranges", "bytes")
        self.send_header("Content-Length", str(length))
        if status == 206:
            self.send_header("Content-Range", f"bytes {start}-{end}/{size}")
        name = os.path.basename(rp)
        disp = "attachment" if attach else "inline"
        self.send_header("Content-Disposition", f"{disp}; filename=\"{sanitize_filename(name) or 'file'}\"")
        self.send_header("Content-Security-Policy", "default-src 'none'; sandbox")
        self._common_headers()
        self.end_headers()
        if self.command == "HEAD":
            return
        with open(rp, "rb") as f:
            f.seek(start)
            left = length
            while left > 0:
                chunk = f.read(min(256 * 1024, left))
                if not chunk:
                    break
                self.wfile.write(chunk)
                left -= len(chunk)


# ---------------------------------------------------------------- endpoints: basics

@route("GET", "/api/ping")
def api_ping(h, body):
    return {"app": "ig-studio", "version": VERSION}


@route("GET", "/api/status")
def api_status(h, body):
    claude = find_claude()
    if claude and h.server._claude_version is None:
        try:
            r = subprocess.run([claude, "--version"], capture_output=True, text=True, timeout=15,
                               env=child_env(False))
            h.server._claude_version = (r.stdout or r.stderr).strip().splitlines()[0][:80] if (r.stdout or r.stderr) else ""
        except (OSError, subprocess.SubprocessError, IndexError):
            h.server._claude_version = ""
    sd = skills_dir()
    skills = sorted(d for d in os.listdir(sd) if d.startswith("ig")) if os.path.isdir(sd) else []
    return {
        "version": VERSION, "python": sys.version.split()[0], "platform": sys.platform,
        "claude": {"found": bool(claude), "path": claude, "version": h.server._claude_version if claude else None},
        "skills": {"dir": sd, "found": bool(script_path("ig/state.py")), "list": skills},
        "ffmpeg": shutil.which("ffmpeg"), "ffprobe": shutil.which("ffprobe"),
        "whisper": find_whisper(), "chrome": find_chrome(),
        "data_dir": data_dir(), "ig_home": ig_home(), "account": active_handle(),
        "scan_available": bool(script_path("ig-scan/scan.py")),
        "install": install_status(),
        "whisper_setup": WHISPER.snapshot(),
    }


@route("POST", "/api/setup/whisper")
def api_setup_whisper(h, body):
    start_thread(WHISPER.run)
    return WHISPER.snapshot()


@route("POST", "/api/reopen")
def api_reopen(h, body):
    """The launcher calls this when IG Studio is already running: open the
    browser again, with the same warm-up and arrival check as a fresh start."""
    url = launch_url(h.server.port, h.server.token)
    start_thread(lambda: open_and_confirm(h.server, url))
    return {"ok": True}


@route("POST", "/api/install-skills")
def api_install_skills(h, body):
    if not install_status()["bundled"]:
        raise ApiError(400, "There are no bundled skills next to this app to install.")
    try:
        return install_skills()
    except OSError as e:
        raise ApiError(500, f"Could not install the skills: {e}")


@route("GET", "/api/state")
def api_state(h, body):
    args = ["--json"]
    if h.query.get("quick"):
        args.append("--no-checks")
    st = script_json("ig/state.py", args, timeout=60)
    return st


@route("POST", "/api/profile")
def api_profile(h, body):
    at = body.get("account_type")
    if at not in (None, "", "creator", "business"):
        raise ApiError(400, "Account type must be creator or business.")
    args = ["set"] + flags(body, {"region": "--region", "niche": "--niche", "account_type": "--account-type",
                                  "language": "--language", "goal": "--goal"})
    if len(args) == 1:
        raise ApiError(400, "Fill in at least one field.")
    return {"profile": script_json("ig/state.py", args)}


# ---------------------------------------------------------------- profile: fix all with kweo

# The only run that may click and type on Instagram: the user ticked each change first.
PROFILE_EDIT_TOOLS = ["mcp__kweo__browser_click", "mcp__kweo__browser_type"]
PROFILE_FIELDS = {"name": 30, "bio": 150}


def profile_dir():
    return os.path.join(data_dir(), "profile")


def read_json_file(path):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


@route("GET", "/api/profile/changes")
def api_profile_changes(h, body):
    d = read_json_file(os.path.join(profile_dir(), "changes.json")) or {}
    res = read_json_file(os.path.join(profile_dir(), "apply-result.json"))
    return {"changes": d.get("changes") or [], "handle": d.get("handle"), "made_at": d.get("made_at"),
            "score_now": d.get("score_now"), "score_after": d.get("score_after"), "result": res}


def approved_changes(body):
    d = read_json_file(os.path.join(profile_dir(), "changes.json")) or {}
    by_id = {c.get("id"): c for c in d.get("changes") or [] if isinstance(c, dict)}
    items = body.get("items")
    if not isinstance(items, list) or not items:
        raise ApiError(400, "Tick at least one change.")
    out = []
    for it in items[:10]:
        c = by_id.get(it.get("id")) if isinstance(it, dict) else None
        if not c:
            raise ApiError(400, "That change is not in the list. Refresh the page.")
        if c.get("app_only"):
            raise ApiError(400, f"{c.get('field')} can only be changed in the Instagram app.")
        field = c.get("field")
        if field in PROFILE_FIELDS:
            value = it.get("value", c.get("value"))
            if not isinstance(value, str) or not value.strip():
                raise ApiError(400, f"The new {field} is empty.")
            value = value.replace("\r\n", "\n").strip()
            if len(value) > PROFILE_FIELDS[field]:
                raise ApiError(400, f"The {field} is {len(value)} characters. Instagram allows {PROFILE_FIELDS[field]}.")
            if field == "name" and "\n" in value:
                raise ApiError(400, "The name is one line.")
            out.append({"id": c["id"], "field": field, "value": value})
        else:
            raise ApiError(400, f"kweo can't change {field} on the web.")
    return d.get("handle"), out


@route("POST", "/api/profile/apply")
def api_profile_apply(h, body):
    handle, changes = approved_changes(body)
    handle = str(handle or active_handle() or "").lstrip("@")
    if not re.fullmatch(r"[A-Za-z0-9._]{1,30}", handle):
        raise ApiError(400, "The change list has no account handle. Run /ig-profile again.")
    if not find_claude():
        raise ApiError(503, "Claude Code is not installed.", {"install": "https://claude.com/claude-code"})
    dry = bool(body.get("dry_run"))
    folder = profile_dir()
    os.makedirs(folder, exist_ok=True)
    apply_path = os.path.join(folder, "apply.json")
    result_path = os.path.join(folder, "apply-result.json")
    with open(apply_path, "w", encoding="utf-8") as f:
        json.dump({"handle": handle, "dry_run": dry, "changes": changes}, f, indent=2, ensure_ascii=False)
    try:
        os.remove(result_path)
    except OSError:
        pass
    prompt = (("Dry run. " if dry else "") +
              f"Apply my approved Instagram profile changes to @{handle}. Use the ig-profile-editor agent "
              f"(Agent tool, subagent_type ig-profile-editor) with this prompt: \"apply.json is {apply_path}. "
              f"Write the result to {result_path}.\" Do nothing on Instagram yourself. When it is done, read "
              f"{result_path} and tell me in a short list what changed, what did not and why, and what is left "
              "to do in the Instagram app.")
    job = h.new_job("chat", ("Dry run: " if dry else "") + f"Fixing @{handle} with kweo")
    log_path = chat_log_path()
    try:
        chat_log_put(log_path, {"job": job.id, "started": time.time(), "status": "running", "attachments": [],
                                "prompt": ("Dry run: " if dry else "") + "Fix all with kweo: " +
                                          ", ".join(c["field"] for c in changes)})
    except OSError:
        pass
    start_thread(run_chat_job_logged, job, h.server, prompt, None, log_path, PROFILE_EDIT_TOOLS)
    return {"job": job.id, "changes": changes, "dry_run": dry}


@route("GET", "/api/text")
def api_text(h, body):
    name = h.query.get("name", "")
    if name not in TEXT_FILES:
        raise ApiError(400, "Unknown file.")
    p = os.path.join(data_dir(), name)
    try:
        with open(p, encoding="utf-8", errors="replace") as f:
            text = f.read(400_000)
        mtime = dt.datetime.fromtimestamp(os.path.getmtime(p)).isoformat(timespec="minutes")
    except OSError:
        return {"name": name, "exists": False, "text": "", "path": p}
    return {"name": name, "exists": True, "text": text, "path": p, "modified": mtime,
            "url": h.server.file_url(p, download=True)}


@route("POST", "/api/sign")
def api_sign(h, body):
    out = {}
    for p in (body.get("paths") or [])[:100]:
        try:
            rp = safe_data_path(p)
        except ApiError:
            continue
        out[p] = {"url": h.server.file_url(rp), "download": h.server.file_url(rp, download=True)}
    return {"urls": out}


@route("GET", "/api/file")
def api_file(h, body):
    h.serve_file(h.query.get("path", ""), h.query.get("download") == "1")


@route("GET", "/api/zip")
def api_zip(h, body):
    folder = safe_data_path(h.query.get("dir", ""))
    if not os.path.isdir(folder):
        raise ApiError(400, "Not a folder.")
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for fn in sorted(os.listdir(folder)):
            fp = os.path.join(folder, fn)
            if os.path.isfile(fp) and not os.path.islink(fp) and os.path.splitext(fn)[1].lower() in (
                    ".png", ".jpg", ".jpeg", ".txt", ".json", ".mp4", ".srt"):
                z.write(fp, fn)
    data = buf.getvalue()
    name = sanitize_filename(os.path.basename(folder)) or "files"
    h.send_response(200)
    h.send_header("Content-Type", "application/zip")
    h.send_header("Content-Length", str(len(data)))
    h.send_header("Content-Disposition", f'attachment; filename="{name}.zip"')
    h._common_headers()
    h.end_headers()
    h.wfile.write(data)


@route("POST", "/api/upload")
def api_upload(h, body):
    kind = h.query.get("kind", "")
    if kind not in UPLOAD_KINDS:
        raise ApiError(400, "Unknown upload kind.")
    exts, limit = UPLOAD_KINDS[kind]
    name = sanitize_filename(urllib.parse.unquote(h.query.get("name", "")), exts)
    if not name:
        raise ApiError(400, f"That file type is not accepted here. Use: {', '.join(sorted(exts))}.")
    try:
        n = int(h.headers.get("Content-Length") or -1)
    except ValueError:
        n = -1
    if n < 0:
        raise ApiError(411, "Upload needs a Content-Length.")
    if n > limit:
        raise ApiError(413, f"Too big. The limit for {kind} files is {limit // MB} MB.")
    folder = os.path.join(data_dir(), "uploads")
    os.makedirs(folder, exist_ok=True)
    dest = unique_path(folder, name)
    tmp = dest + ".part"
    left = n
    try:
        with open(tmp, "wb") as f:
            while left > 0:
                chunk = h.rfile.read(min(1024 * 1024, left))
                if not chunk:
                    raise ApiError(400, "Upload was cut off.")
                f.write(chunk)
                left -= len(chunk)
        os.replace(tmp, dest)
    finally:
        if os.path.exists(tmp):
            try:
                os.remove(tmp)
            except OSError:
                pass
    return {"path": dest, "name": os.path.basename(dest), "size": n, "kind": kind,
            "url": h.server.file_url(dest), "download": h.server.file_url(dest, download=True)}


@route("POST", "/api/open-folder")
def api_open_folder(h, body):
    folder = data_dir()
    os.makedirs(folder, exist_ok=True)
    if IS_WIN:
        cmd = ["explorer", folder]
    elif sys.platform == "darwin":
        cmd = ["open", folder]
    else:
        cmd = ["xdg-open", folder]
    if os.environ.get("IG_STUDIO_NO_OPEN"):
        return {"ok": True, "path": folder, "dry_run": True}
    try:
        subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, **popen_kwargs())
    except OSError as e:
        raise ApiError(500, f"Could not open the folder: {e}")
    return {"ok": True, "path": folder}


@route("POST", "/api/quit")
def api_quit(h, body):
    def stop():
        time.sleep(0.3)
        h.server.shutdown_all()
        h.server.shutdown()
    start_thread(stop)
    return {"ok": True}


# ---------------------------------------------------------------- accounts

HANDLE_RE = re.compile(r"@?[A-Za-z0-9._]{1,30}")


@route("GET", "/api/accounts")
def api_accounts(h, body):
    return script_json("ig-account/account.py", ["list", "--json"], with_data=False)


@route("POST", "/api/accounts/new")
def api_accounts_new(h, body):
    handle = str(body.get("handle") or "").strip()
    if not HANDLE_RE.fullmatch(handle) or ".." in handle:
        raise ApiError(400, "Handles use letters, digits, . and _ (30 max).")
    res = script_json("ig-account/account.py", ["new", handle, "--json"], with_data=False)
    if body.get("use", True):
        script_text("ig-account/account.py", ["use", handle], with_data=False)
    return res


@route("POST", "/api/accounts/use")
def api_accounts_use(h, body):
    if body.get("none"):
        return script_text("ig-account/account.py", ["use", "--none"], with_data=False)
    handle = str(body.get("handle") or "").strip()
    if not HANDLE_RE.fullmatch(handle) or ".." in handle:
        raise ApiError(400, "Invalid handle.")
    return script_text("ig-account/account.py", ["use", handle], with_data=False)


# ---------------------------------------------------------------- ledger, audit, perf

LEDGER_META = {"date": "--date", "format": "--format", "theme": "--theme", "hook_formula": "--hook-formula",
               "first_line": "--first-line", "length": "--length", "permalink": "--permalink",
               "test_id": "--test-id", "variant": "--variant", "notes": "--notes"}
METRICS = {"views": "--views", "reach": "--reach", "likes": "--likes", "comments": "--comments",
           "shares": "--shares", "saves": "--saves", "follows": "--follows", "skip_rate": "--skip-rate",
           "nonfollower_pct": "--nonfollower-pct", "avg_watch": "--avg-watch"}


@route("GET", "/api/ledger")
def api_ledger(h, body):
    rows = script_json("ig-ledger/ledger.py", ["list", "--json"])
    return {"posts": rows if isinstance(rows, list) else []}


@route("POST", "/api/ledger/add")
def api_ledger_add(h, body):
    if body.get("format") not in ("reel", "carousel", "story", "photo"):
        raise ApiError(400, "Pick a format: reel, carousel, story or photo.")
    args = ["add"] + flags(body, LEDGER_META)
    if body.get("trial"):
        args.append("--trial")
    r = script_text("ig-ledger/ledger.py", args)
    m = re.search(r"\bP\d{3,}\b", r["output"])
    return {"id": m.group(0) if m else r["output"], "output": r["output"]}


@route("POST", "/api/ledger/update")
def api_ledger_update(h, body):
    pid = check_id(str(body.get("id") or ""), "post id")
    m = dict(METRICS)
    m["avg_watch"] = "--avg-watch"
    args = ["update", pid] + flags(body, m) + flags(body, LEDGER_META)
    if len(args) == 2:
        raise ApiError(400, "Nothing to update.")
    return script_text("ig-ledger/ledger.py", args)


@route("POST", "/api/ledger/import")
def api_ledger_import(h, body):
    p = safe_data_path(body.get("path"))
    if not p.lower().endswith(".csv"):
        raise ApiError(400, "Import needs a .csv file.")
    args = ["import", p] + (["--dry-run"] if body.get("dry_run", True) else [])
    return script_text("ig-ledger/ledger.py", args, timeout=120)


@route("GET", "/api/audit")
def api_audit(h, body):
    args = ["--json"]
    fmt = h.query.get("format")
    if fmt in ("reel", "carousel", "story", "photo"):
        args += ["--format", fmt]
    since = h.query.get("since", "")
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", since):
        args += ["--since", since]
    return script_json("ig-ledger/audit.py", args)


@route("GET", "/api/perf/due")
def api_perf_due(h, body):
    r = script_json("ig-perf/perf.py", ["due", "--json"])
    return {"due": r if isinstance(r, list) else []}


@route("GET", "/api/perf/status")
def api_perf_status(h, body):
    pid = check_id(h.query.get("id", ""), "post id")
    return script_json("ig-perf/perf.py", ["status", pid, "--json"])


@route("POST", "/api/perf/check")
def api_perf_check(h, body):
    pid = check_id(str(body.get("id") or ""), "post id")
    m = dict(METRICS)
    m.update({"hours": "--hours", "at": "--at", "posted_at": "--posted-at", "notes": "--notes"})
    args = ["check", pid] + flags(body, m) + ["--source=manual", "--json", "--quiet"]
    return script_json("ig-perf/perf.py", args)


@route("POST", "/api/perf/retention")
def api_perf_retention(h, body):
    pid = check_id(str(body.get("id") or ""), "post id")
    pts = str(body.get("points") or "").replace(" ", "")
    if not re.fullmatch(r"\d+(\.\d+)?:\d+(\.\d+)?(,\d+(\.\d+)?:\d+(\.\d+)?)*", pts):
        raise ApiError(400, 'Points look like "0:100,3:61,10:40".')
    args = ["retention", pid, f"--points={pts}", "--json"] + flags(body, {"length": "--length"})
    return script_json("ig-perf/perf.py", args)


# ---------------------------------------------------------------- growth

@route("POST", "/api/grow/checkin")
def api_grow_checkin(h, body):
    try:
        n = int(str(body.get("followers", "")).replace(",", "").strip())
        if n < 0:
            raise ValueError
    except ValueError:
        raise ApiError(400, "Enter your follower count as a number.")
    b = dict(body)
    b["followers"] = n
    args = ["checkin"] + flags(b, {"followers": "--followers", "following": "--following", "posts": "--posts",
                                   "date": "--date", "notes": "--notes"}) + ["--json"]
    return script_json("ig-grow/grow.py", args)


@route("GET", "/api/grow/report")
def api_grow_report(h, body):
    return script_json("ig-grow/grow.py", ["report", "--json"])


@route("GET", "/api/grow/plan")
def api_grow_plan(h, body):
    return script_json("ig-grow/grow.py", ["plan", "--json"])


@route("GET", "/api/grow/milestones")
def api_grow_milestones(h, body):
    r = script_json("ig-grow/grow.py", ["milestones", "--json"])
    return {"milestones": r if isinstance(r, list) else []}


@route("GET", "/api/grow/series")
def api_grow_series(h, body):
    pts = {}
    try:
        with open(os.path.join(data_dir(), "followers.csv"), encoding="utf-8") as f:
            for i, line in enumerate(f):
                parts = line.strip().split(",")
                if i == 0 or len(parts) < 2:
                    continue
                try:
                    d = dt.date.fromisoformat(parts[0])
                    pts[d.isoformat()] = int(float(parts[1]))
                except ValueError:
                    continue
    except OSError:
        pass
    return {"points": [{"date": k, "followers": pts[k]} for k in sorted(pts)]}


# ---------------------------------------------------------------- trends, audio

def profile_value(key):
    try:
        with open(os.path.join(data_dir(), "profile.json"), encoding="utf-8") as f:
            return (json.load(f) or {}).get(key)
    except (OSError, ValueError, AttributeError):
        return None


@route("GET", "/api/trends")
def api_trends(h, body):
    r = script_json("ig-trends/trends.py", ["list", "--json"])
    return {"trends": r if isinstance(r, list) else []}


@route("POST", "/api/trends/add")
def api_trends_add(h, body):
    for k in ("source", "region", "kind", "name"):
        if not str(body.get(k) or "").strip():
            raise ApiError(400, f"{k.capitalize()} is required.")
    args = ["add"] + flags(body, {"source": "--source", "region": "--region", "kind": "--kind", "name": "--name",
                                  "scope": "--scope", "rank": "--rank", "growth": "--growth",
                                  "first_seen": "--first-seen", "niche_match": "--niche-match",
                                  "safety": "--safety", "url": "--url", "notes": "--notes"}) + ["--json"]
    return script_json("ig-trends/trends.py", args)


@route("POST", "/api/trends/blend")
def api_trends_blend(h, body):
    niche = str(body.get("niche") or profile_value("niche") or "").strip()
    if not niche:
        raise ApiError(400, "Set your niche first (Today → profile).")
    b = {"niche": niche, "region": body.get("region") or profile_value("region") or "", "top": body.get("top")}
    args = ["blend"] + flags(b, {"niche": "--niche", "region": "--region", "top": "--top"}) + ["--json"]
    for a in (body.get("angles") or [])[:10]:
        if isinstance(a, str) and a.strip():
            args.append(f"--angle={a.strip()[:200]}")
    if body.get("no_write"):
        args.append("--no-write")
    return script_json("ig-trends/trends.py", args)


@route("POST", "/api/trends/prune")
def api_trends_prune(h, body):
    return script_json("ig-trends/trends.py", ["prune", "--json"])


AUDIO_ADD = {"name": "--name", "artist": "--artist", "source": "--source", "region": "--region",
             "reels_count": "--reels-count", "trend": "--trend", "bpm": "--bpm", "mood": "--mood",
             "business_ok": "--business-ok", "url": "--url", "notes": "--notes", "seen": "--seen"}


@route("GET", "/api/audio")
def api_audio(h, body):
    r = script_json("ig-audio/audio.py", ["list", "--json"])
    return {"sounds": r if isinstance(r, list) else []}


@route("POST", "/api/audio/add")
def api_audio_add(h, body):
    for k in ("name", "source", "region"):
        if not str(body.get(k) or "").strip():
            raise ApiError(400, f"{k.capitalize()} is required.")
    return script_text("ig-audio/audio.py", ["add"] + flags(body, AUDIO_ADD))


@route("POST", "/api/audio/suggest")
def api_audio_suggest(h, body):
    b = dict(body)
    b.setdefault("account", profile_value("account_type"))
    if not b.get("region"):
        b["region"] = profile_value("region")
    args = ["suggest"] + flags(b, {"reel_length": "--reel-length", "mood": "--mood", "account": "--account",
                                   "voiceover": "--voiceover", "region": "--region", "top": "--top"}) + ["--json"]
    if not body.get("reel_length"):
        raise ApiError(400, "Reel length (seconds) is required.")
    return script_json("ig-audio/audio.py", args)


# ---------------------------------------------------------------- calendar

def cal_flags(body):
    b = {k: body.get(k) for k in ("week_of", "tz")}
    if b.get("week_of") and not re.fullmatch(r"\d{4}-\d{2}-\d{2}", str(b["week_of"])):
        raise ApiError(400, "Week of must be YYYY-MM-DD.")
    if b.get("tz") and not re.fullmatch(r"[A-Za-z_]+(/[A-Za-z0-9_+-]+){0,2}", str(b["tz"])):
        raise ApiError(400, "Time zone looks wrong (e.g. Europe/London).")
    out = flags(b, {"week_of": "--week-of", "tz": "--tz"})
    for s in body.get("skip") or []:
        if s in ("post", "prep", "engage", "stories"):
            out.append(f"--skip={s}")
    return out


@route("GET", "/api/calendar")
def api_calendar(h, body):
    q = {"week_of": h.query.get("week_of"), "tz": h.query.get("tz")}
    plan = os.path.join(data_dir(), "plan.md")
    if not os.path.isfile(plan):
        return {"exists": False}
    r = run_script("ig-calendar/schedule.py", ["parse", "--json"] + cal_flags(q))
    if r["json"] is None:
        return {"exists": True, "error": friendly_error(r["err"], r["out"])}
    return {"exists": True, "parsed": r["json"]}


@route("POST", "/api/calendar/ics")
def api_calendar_ics(h, body):
    out = os.path.join(data_dir(), "ig-week.ics")
    res = script_json("ig-calendar/schedule.py", ["ics", f"--out={out}", "--json"] + cal_flags(body))
    path = res.get("path") or out
    res["url"] = h.server.file_url(path, download=True)
    return res


# ---------------------------------------------------------------- create tools

def text_arg(body, key, limit=20000, required=True):
    v = body.get(key)
    if not isinstance(v, str) or (required and not v.strip()):
        if required:
            raise ApiError(400, f"Type some {key} first.")
        return ""
    if len(v) > limit:
        raise ApiError(400, f"That {key} is too long.")
    return v


@route("POST", "/api/tools/hookscore")
def api_hookscore(h, body):
    hooks = body.get("hooks")
    if isinstance(hooks, str):
        hooks = hooks.splitlines()
    hooks = [x.strip() for x in (hooks or []) if isinstance(x, str) and x.strip()][:40]
    if not hooks:
        raise ApiError(400, "Type at least one hook.")
    r = script_json("ig-reel/hookscore.py", ["-", "--json"], stdin="\n".join(hooks) + "\n")
    rows = r if isinstance(r, list) else [r]
    rows.sort(key=lambda x: -(x.get("score") or 0))
    return {"hooks": rows}


@route("POST", "/api/tools/beats")
def api_beats(h, body):
    script = text_arg(body, "script")
    args = ["-", "--json"] + flags(body, {"target": "--target", "wpm": "--wpm"})
    return script_json("ig-reel/beats.py", args, stdin=script)


@route("POST", "/api/tools/caption")
def api_caption(h, body):
    cap = text_arg(body, "caption")
    args = ["-", "--json"] + flags(body, {"keywords": "--keywords", "truncate": "--truncate"})
    return script_json("ig-caption/caption.py", args, stdin=cap)


@route("POST", "/api/tools/humanize")
def api_humanize(h, body):
    text = text_arg(body, "text")
    hum = script_json("ig-human/humanize.py", ["-", "--json"], stdin=text)
    before = script_json("ig-human/detect.py", ["-", "--json"], stdin=text)
    after = script_json("ig-human/detect.py", ["-", "--json"], stdin=hum.get("text", ""))
    return {"text": hum.get("text", ""), "report": hum.get("report", {}), "before": before, "after": after}


def stamp():
    return dt.datetime.now().strftime("%Y%m%d-%H%M%S")


def clean_spec(spec):
    if not isinstance(spec, dict):
        raise ApiError(400, "Spec must be an object.")
    kind = spec.get("kind", "carousel")
    if kind not in ("carousel", "story"):
        raise ApiError(400, "Kind must be carousel or story.")
    key = "slides" if kind == "carousel" else "frames"
    items = spec.get(key)
    if not isinstance(items, list) or not items:
        raise ApiError(400, "Add at least one slide.")
    if len(items) > 20:
        raise ApiError(400, "Instagram allows 20 slides at most.")
    out_items = []
    for it in items:
        if not isinstance(it, dict):
            raise ApiError(400, "Each slide must be an object.")
        o = {}
        for k in ("role", "title", "body", "note", "sticker"):
            v = it.get(k)
            if isinstance(v, str) and v.strip():
                o[k] = v.strip()[:600]
        if o.get("role") not in (None, "cover", "recap", "cta"):
            o.pop("role", None)
        if isinstance(it.get("list"), list):
            lst = [str(x).strip()[:200] for x in it["list"] if str(x).strip()][:10]
            if lst:
                o["list"] = lst
        if not o.get("title") and not o.get("body") and not o.get("list"):
            raise ApiError(400, "Every slide needs a title or some text.")
        out_items.append(o)
    clean = {"kind": kind, key: out_items}
    for k in ("handle", "alt"):
        if isinstance(spec.get(k), str) and spec[k].strip():
            clean[k] = spec[k].strip()[:300]
    return clean


@route("POST", "/api/render")
def api_render(h, body):
    spec = clean_spec(body.get("spec"))
    out = os.path.join(data_dir(), "renders", f"{spec['kind']}-{stamp()}")
    os.makedirs(out, exist_ok=True)
    spec_path = os.path.join(out, "spec.json")
    with open(spec_path, "w", encoding="utf-8") as f:
        json.dump(spec, f, indent=2, ensure_ascii=False)
    job = h.new_job("render", f"Render {spec['kind']}")
    srv = h.server

    def after(rc, stdout, err):
        files = sorted((fn for fn in os.listdir(out) if fn.lower().endswith(".png")),
                       key=lambda fn: (fn.startswith("grid-preview"), fn))
        alt = ""
        try:
            with open(os.path.join(out, "alt-text.txt"), encoding="utf-8") as f:
                alt = f.read()
        except OSError:
            pass
        return {"folder": out, "report": stdout.strip()[-4000:], "alt_text": alt,
                "files": [{"name": fn, "url": srv.file_url(os.path.join(out, fn)),
                           "download": srv.file_url(os.path.join(out, fn), download=True)} for fn in files],
                "zip": srv.zip_url(out)}
    start_thread(run_script_job, job, "ig-render/render.py", [spec_path, f"--out={out}", f"--kind={spec['kind']}"],
                 600, None, None, after)
    return {"job": job.id}


EDIT_PRESETS = ("superfast", "veryfast", "faster", "fast", "medium", "slow", "slower")
TIME_RE = re.compile(r"\d{1,2}:\d{2}(:\d{2})?(\.\d+)?|\d+(\.\d+)?")


@route("POST", "/api/video/edit")
def api_video_edit(h, body):
    src = safe_data_path(body.get("path"))
    if os.path.splitext(src)[1].lower() not in UPLOAD_KINDS["video"][0]:
        raise ApiError(400, "Pick a video file.")
    stem = sanitize_filename(os.path.splitext(os.path.basename(src))[0] + ".x")[:-2] or "reel"
    out_dir = os.path.join(data_dir(), "edits", f"{stem}-{stamp()}")
    os.makedirs(out_dir, exist_ok=True)
    out = os.path.join(out_dir, "reel.mp4")
    args = [src, f"--out={out}", "--json"]
    if body.get("cut_silence"):
        args.append("--cut-silence")
    crop = body.get("crop") or "auto"
    if crop not in ("auto", "center", "none"):
        raise ApiError(400, "Crop must be auto, center or none.")
    args.append(f"--crop={crop}")
    caps = body.get("captions") or "burn"
    if caps not in ("burn", "srt", "none"):
        raise ApiError(400, "Captions must be burn, srt or none.")
    args.append(f"--captions={caps}")
    hook = str(body.get("hook_text") or "").strip()
    if hook:
        if len(hook) > 120 or "\n" in hook:
            raise ApiError(400, "Keep the hook card to one short line.")
        args.append(f"--hook-text={hook}")
    for k, flag in (("start", "--start"), ("end", "--end")):
        v = str(body.get(k) or "").strip()
        if v:
            if not TIME_RE.fullmatch(v):
                raise ApiError(400, f"{k.capitalize()} must look like 00:01:20.")
            args.append(f"{flag}={v}")
    for k, flag in (("max_length", "--max-length"), ("silence_db", "--silence-db"), ("pad", "--pad"),
                    ("min_silence", "--min-silence")):
        v = body.get(k)
        if v not in (None, ""):
            try:
                args.append(f"{flag}={float(v)}")
            except (TypeError, ValueError):
                raise ApiError(400, f"{k} must be a number.")
    preset = body.get("preset") or "fast"
    if preset not in EDIT_PRESETS:
        raise ApiError(400, "Unknown preset.")
    args.append(f"--preset={preset}")
    lang = str(body.get("lang") or "").strip()
    if lang:
        if not re.fullmatch(r"[a-z]{2,3}", lang):
            raise ApiError(400, "Language is a code like en or hi.")
        args.append(f"--lang={lang}")
    script = body.get("script")
    if isinstance(script, str) and script.strip():
        sp = os.path.join(out_dir, "script.txt")
        with open(sp, "w", encoding="utf-8") as f:
            f.write(script.strip()[:20000] + "\n")
        args.append(f"--script={sp}")
    if body.get("dry_run"):
        args.append("--dry-run")
    job = h.new_job("edit", f"Edit {os.path.basename(src)}")
    srv = h.server

    def after(rc, stdout, err):
        rep = parse_json_out(stdout)
        if rep is None:
            raise ApiError(400, friendly_error(err, stdout))
        res = {"report": rep, "folder": out_dir}
        if os.path.isfile(out):
            res["video"] = {"path": out, "url": srv.file_url(out), "download": srv.file_url(out, download=True)}
        srt = os.path.join(out_dir, "reel.srt")
        if os.path.isfile(srt):
            res["srt"] = {"path": srt, "download": srv.file_url(srt, download=True)}
        chk = os.path.join(out_dir, "check")
        if os.path.isdir(chk):
            res["checks"] = [{"name": fn, "url": srv.file_url(os.path.join(chk, fn))}
                             for fn in sorted(os.listdir(chk)) if fn.lower().endswith(".png")]
        return res
    start_thread(run_script_job, job, "ig-edit/edit.py", args, 4 * 3600, None, None, after)
    return {"job": job.id}


# ---------------------------------------------------------------- video: Claude directs (ig-direct)

DIRECT_MOODS = ("auto", "energetic", "calm", "funny", "dramatic", "warm", "premium", "story")


def direct_dir(value):
    d = safe_data_path(value)
    if not os.path.isdir(d) or not within(d, os.path.join(data_dir(), "edits")):
        raise ApiError(400, "That is not an edit folder.")
    return d


def direct_prompt(src, folder, body, auto_render=False):
    mood = body.get("mood") or "auto"
    if mood not in DIRECT_MOODS:
        raise ApiError(400, "Unknown mood.")
    length = body.get("length") or "auto"
    if length != "auto":
        try:
            length = int(length)
        except (TypeError, ValueError):
            raise ApiError(400, "Length is a number of seconds.")
        if not 7 <= length <= 90:
            raise ApiError(400, "Length must be 7 to 90 seconds.")
    lang = str(body.get("lang") or "auto").strip()
    if not re.fullmatch(r"auto|[a-z]{2,3}", lang):
        raise ApiError(400, "Language is a code like en or hi.")
    notes = str(body.get("notes") or "").strip()[:2000]
    return (
        "/ig-direct Direct this video into a Reel.\n"
        f"Video: {src}\n"
        f"Edit folder: {folder}  (run analyze with --dir set to exactly this folder)\n"
        f"Mood: {mood if mood != 'auto' else 'you decide from the footage and the account'}\n"
        f"Target length: {str(length) + ' seconds' if length != 'auto' else 'you decide'}\n"
        f"Language: {lang}\n"
        f"What I want: {notes or '(nothing extra; make it as watchable as you can)'}\n\n"
        "Do steps 1 to 5: analyze, write the brief, fire up the section agents, merge, "
        "storyboard with --preview, the critic and one revision round. Then STOP at step 6. "
        + ("Do not render: IG Studio's auto-render renders the Reel right after you finish, so make the "
           "storyboard final. Ask me nothing. "
           if auto_render else "Do not render: I approve the storyboard in IG Studio first. ")
        + "End with a short summary for me: the concept, mood, length, hook, checklist score and "
        "anything I should know.")


@route("POST", "/api/video/direct")
def api_video_direct(h, body):
    src = safe_data_path(body.get("path"))
    if os.path.splitext(src)[1].lower() not in UPLOAD_KINDS["video"][0]:
        raise ApiError(400, "Pick a video file.")
    body = dict(body)
    post, week_of = None, None
    if body.get("post_id"):
        week_of, post = week_post(body.get("week_of"), body.get("post_id"))
        body.update(post_brief(post))
    auto_render = bool(body.get("auto_render", post is not None))
    if post is not None:
        stem = f"{week_of}-{post['id']}"
    else:
        stem = sanitize_filename(os.path.splitext(os.path.basename(src))[0] + ".x")[:-2][:40] or "reel"
    folder = os.path.join(data_dir(), "edits", f"{stem}-direct-{stamp()}")
    prompt = direct_prompt(src, folder, body, auto_render)
    if not find_claude():
        raise ApiError(503, "Claude Code is not installed.", {"install": "https://claude.com/claude-code"})
    if not script_path("ig-direct/direct.py"):
        raise ApiError(503, "The director skill (ig-direct) is not installed yet. Install the skills first.")
    os.makedirs(folder, exist_ok=True)
    job = h.new_job("chat", "Directing " + os.path.basename(src))
    if post is not None:
        week_status_put(week_of, post["id"], edit_dir=folder, edit_job=job.id, footage=src,
                        stage=max_stage(week_status_get(week_of, post["id"]).get("stage"), "filmed"))
    start_thread(run_chat_job, job, h.server, prompt, None, None,
                 direct_auto_render(folder) if auto_render else None)
    return {"job": job.id, "dir": folder, "auto_render": auto_render}


def direct_auto_render(folder):
    """After the director's run: render the Reel straight away (IG Studio's auto-render)."""
    def after(job, run):
        if not os.path.isfile(os.path.join(folder, "storyboard.json")):
            raise ApiError(400, "The director finished without a storyboard, so nothing was rendered. "
                                "Try again, or ask Claude what went wrong.")
        sp = script_path("ig-direct/direct.py")
        if not sp:
            raise ApiError(503, "ig-direct is not installed.")
        job.emit("tool", id="auto-render", summary=DIRECT_STEPS["render"], sub=False)
        rc, out, err = run_process(job, [sys.executable, "-I", sp, "render", folder, "--json"],
                                   child_env(True), data_dir(), 4 * 3600)
        if job.cancelled:
            raise ApiError(499, "Cancelled.")
        rep = parse_json_out(out)
        ok = rc == 0 and isinstance(rep, dict) and not rep.get("error")
        job.emit("tool_done", id="auto-render", error=not ok)
        if not ok:
            raise ApiError(400, (rep or {}).get("error") if isinstance(rep, dict) and rep.get("error")
                           else friendly_error(err, out))
    return after


@route("POST", "/api/video/direct/revise")
def api_video_direct_revise(h, body):
    folder = direct_dir(body.get("dir"))
    change = str(body.get("change") or "").strip()
    if not change:
        raise ApiError(400, "Say what to change.")
    sid = body.get("session_id")
    if sid is not None and (not isinstance(sid, str) or not SID_RE.fullmatch(sid)):
        sid = None
    prompt = (f"/ig-direct Change the storyboard in {folder}: {change[:3000]}\n"
              "Apply it (edit the section JSON yourself, or send it back to the agent that owns it), "
              "then merge and storyboard with --preview again. Do not render. "
              "End with a two-line summary of what changed and the new checklist score.")
    job = h.new_job("chat", "Changing the storyboard")
    start_thread(run_chat_job, job, h.server, prompt, sid)
    return {"job": job.id, "dir": folder}


def direct_state(srv, folder):
    def url(rel):
        p = os.path.join(folder, rel)
        return srv.file_url(p) if os.path.isfile(p) else None

    def rj(name):
        try:
            with open(os.path.join(folder, name), encoding="utf-8") as f:
                return json.load(f)
        except (OSError, ValueError):
            return None
    sb = rj("storyboard.json")
    plan = rj("plan.json") or {}
    res = {"dir": folder, "name": os.path.basename(folder), "ready": bool(sb), "brief": plan.get("brief") or {},
           "look": {k: (plan.get("look") or {}).get(k) for k in ("grade", "vignette", "progress_bar")},
           "captions": {k: (plan.get("captions") or {}).get(k) for k in ("style", "font", "size", "highlight")},
           "sound": {k: (plan.get("sound") or {}).get(k) for k in ("brief", "suggested_audio", "sfx")},
           "critic": rj("critic.json"), "html": url("storyboard.html")}
    try:   # a critic score from before the latest storyboard was the first cut: its fixes came after
        res["critic_stale"] = bool(res["critic"]) and os.path.getmtime(os.path.join(folder, "critic.json")) < \
            os.path.getmtime(os.path.join(folder, "storyboard.json"))
    except OSError:
        res["critic_stale"] = False
    if sb:
        res.update({"length": sb.get("length"), "score": sb.get("score"), "checklist": sb.get("checklist"),
                    "made_at": sb.get("made_at"), "preview": url(sb["preview"]) if sb.get("preview") else None,
                    "panels": [{"t": p.get("t"), "shot": p.get("shot"), "role": p.get("role"), "said": p.get("said"),
                                "note": (p.get("shot_info") or {}).get("note"),
                                "image": url(p["image"]) if p.get("image") else None}
                               for p in sb.get("panels") or []]})
    rep = rj("render-report.json")
    out = os.path.join(folder, "reel.mp4")
    if rep and os.path.isfile(out):
        res["render"] = {"report": rep, "video": {"path": out, "url": srv.file_url(out),
                                                  "download": srv.file_url(out, download=True)}}
        cov = rep.get("cover")
        if cov and os.path.isfile(cov):
            res["render"]["cover"] = {"url": srv.file_url(cov), "download": srv.file_url(cov, download=True)}
        chk = os.path.join(folder, "check")
        if os.path.isdir(chk):
            res["render"]["checks"] = [{"name": fn, "url": srv.file_url(os.path.join(chk, fn))}
                                       for fn in sorted(os.listdir(chk)) if fn.lower().endswith(".png")]
    return res


@route("GET", "/api/video/direct")
def api_video_direct_get(h, body):
    if h.query.get("dir"):
        return direct_state(h.server, direct_dir(h.query.get("dir")))
    root = os.path.join(data_dir(), "edits")
    items = []
    if os.path.isdir(root):
        for name in sorted(os.listdir(root), reverse=True):
            d = os.path.join(root, name)
            if "-direct-" in name and os.path.isfile(os.path.join(d, "storyboard.json")):
                items.append({"dir": d, "name": name, "rendered": os.path.isfile(os.path.join(d, "reel.mp4"))})
            if len(items) >= 12:
                break
    return {"edits": items}


@route("POST", "/api/video/direct/render")
def api_video_direct_render(h, body):
    folder = direct_dir(body.get("dir"))
    if not os.path.isfile(os.path.join(folder, "storyboard.json")):
        raise ApiError(400, "There is no storyboard to render yet.")
    job = h.new_job("edit", "Rendering the Reel")
    srv = h.server

    def after(rc, stdout, err):
        rep = parse_json_out(stdout)
        if rep is None or rep.get("error"):
            raise ApiError(400, (rep or {}).get("error") or friendly_error(err, stdout))
        return direct_state(srv, folder)
    start_thread(run_script_job, job, "ig-direct/direct.py", ["render", folder, "--json"], 4 * 3600,
                 None, None, after)
    return {"job": job.id}


@route("POST", "/api/video/cover")
def api_video_cover(h, body):
    video = safe_data_path(body.get("video"))
    try:
        at = round(max(0.0, float(body.get("at", 0))), 2)
    except (TypeError, ValueError):
        raise ApiError(400, "Pick a time in seconds.")
    out = os.path.join(os.path.dirname(video), "cover-%s.jpg" % str(at).replace(".", "_"))
    res = script_json("ig-edit/cover.py", [video, f"--at={at}", f"--out={out}", "--json"], timeout=120)
    p = res.get("cover") or out
    if within(p, data_dir()) and os.path.isfile(p):
        res["url"] = h.server.file_url(p)
        res["download"] = h.server.file_url(p, download=True)
    return res


# ---------------------------------------------------------------- A/B tests

# ---------------------------------------------------------------- the week: autopilot and post kits
#
# Claude (the ig skill's Autopilot section) writes week.json: every post as a kit
# (hook, script, the director's filming notes, caption, sound). IG Studio keeps a
# copy of each week in .studio/weeks/ so planning next week never loses this one,
# and tracks each post's progress (filmed, edited, posted) in .studio/week-status.json.

WEEK_STAGES = ("script", "filmed", "edited", "posted")
AUTOPILOT_RETRY_S = 6 * 3600   # a failed automatic run waits this long before the page tries again
_week_lock = threading.Lock()


def studio_path(*parts):
    return os.path.join(data_dir(), ".studio", *parts)


def write_json_atomic(path, obj):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + f".{os.getpid()}.tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, indent=1)
    os.replace(tmp, path)


def plan_monday(today):
    """The week to prepare: this week Mon-Wed, next week Thu-Sun (same rule as ig/week.py)."""
    start = today - dt.timedelta(days=today.weekday())
    return start if today.weekday() <= 2 else start + dt.timedelta(days=7)


def _valid_week(w):
    if not isinstance(w, dict) or not isinstance(w.get("posts"), list):
        return False
    try:
        return dt.date.fromisoformat(str(w.get("week_of"))).weekday() == 0
    except ValueError:
        return False


def weeks_sync():
    """Copy week.json into .studio/weeks/<week_of>.json when it is newer. Returns {week_of: path}."""
    root = studio_path("weeks")
    latest = os.path.join(data_dir(), "week.json")
    w = read_json_file(latest)
    if _valid_week(w):
        dst = os.path.join(root, w["week_of"] + ".json")
        try:
            if not os.path.isfile(dst) or os.path.getmtime(latest) > os.path.getmtime(dst):
                os.makedirs(root, exist_ok=True)
                shutil.copy2(latest, dst)
        except OSError:
            pass
    out = {}
    if os.path.isdir(root):
        for fn in os.listdir(root):
            m = re.fullmatch(r"(\d{4}-\d{2}-\d{2})\.json", fn)
            if m:
                out[m.group(1)] = os.path.join(root, fn)
    return out


def week_file(week_of):
    if not isinstance(week_of, str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", week_of):
        raise ApiError(400, "Pick a week.")
    p = weeks_sync().get(week_of)
    if not p:
        raise ApiError(404, "There is no plan for that week.")
    return p


def week_post(week_of, post_id):
    w = read_json_file(week_file(week_of))
    for p in (w or {}).get("posts") or []:
        if isinstance(p, dict) and p.get("id") == post_id:
            return week_of, p
    raise ApiError(404, "That post is not in this week's plan.")


def week_status_all():
    d = read_json_file(studio_path("week-status.json"))
    return d if isinstance(d, dict) else {}


def week_status_get(week_of, pid):
    return week_status_all().get(f"{week_of}/{pid}") or {}


def week_status_put(week_of, pid, **fields):
    with _week_lock:
        d = week_status_all()
        row = d.get(f"{week_of}/{pid}") or {}
        row.update(fields)
        row["updated"] = time.time()
        d[f"{week_of}/{pid}"] = row
        write_json_atomic(studio_path("week-status.json"), d)
        return row


def max_stage(a, b):
    rank = {k: i for i, k in enumerate(WEEK_STAGES)}
    return a if rank.get(a, -1) >= rank.get(b, -1) else b


def post_brief(post):
    """A planned post as the director's brief: mood, length, language and the kit as notes."""
    d = post.get("direction") if isinstance(post.get("direction"), dict) else {}
    hook = post.get("hook") if isinstance(post.get("hook"), dict) else {}
    mood = d.get("mood") if d.get("mood") in DIRECT_MOODS else "auto"
    try:
        length = int(post.get("length_s"))
        length = length if 7 <= length <= 90 else "auto"
    except (TypeError, ValueError):
        length = "auto"
    beats = []
    for b in (post.get("script") or [])[:20]:
        if isinstance(b, dict):
            beats.append(f"- {b.get('t', '')} say: {b.get('say', '')} | on screen: {b.get('on_screen', '')}")
    model = post.get("model") if isinstance(post.get("model"), dict) else {}
    copies = ""
    if model.get("ref"):
        copies = (f"It copies a reel that went viral: {model.get('account', '')} {model.get('url', '')} "
                  f"({model.get('structure', '')}). Cut to its pace and look. Copied: "
                  + "; ".join(str(c) for c in (model.get("copy") or [])[:6]) + "\n")
    notes = (f"This is the planned post \"{post.get('title', '')}\" ({post.get('type', '')}). "
             f"Concept: {d.get('concept', '')}\n" + copies +
             f"Hook, spoken: {hook.get('spoken', '')}\nHook, on screen: {hook.get('on_screen', '')}\n"
             "Beats:\n" + "\n".join(beats))
    return {"mood": mood, "length": length, "lang": "auto", "notes": notes[:2000]}


def edit_summary(srv, folder, job_id):
    if not folder or not os.path.isdir(folder):
        return None
    j = srv.jobs.get(job_id) if job_id else None
    out = {"dir": folder, "running": bool(j and not j.done), "job": job_id if j and not j.done else None,
           "error": None, "storyboard": os.path.isfile(os.path.join(folder, "storyboard.json"))}
    if j and j.done and j.status not in ("done",):
        out["error"] = next((e.get("error") for e in reversed(j.events) if e.get("type") == "end"), None) \
            or "The director stopped."
    reel = os.path.join(folder, "reel.mp4")
    if os.path.isfile(reel):
        out["video"] = {"url": srv.file_url(reel), "download": srv.file_url(reel, download=True)}
        cov = os.path.join(folder, "reel-cover.jpg")
        if os.path.isfile(cov):
            out["cover"] = {"url": srv.file_url(cov), "download": srv.file_url(cov, download=True)}
    return out


def autopilot_record():
    d = read_json_file(studio_path("autopilot.json"))
    return d if isinstance(d, dict) else {}


def autopilot_state(srv):
    rec = autopilot_record()
    j = srv.jobs.get(rec.get("job")) if rec.get("job") else None
    running = bool(j and not j.done)
    if rec.get("status") == "running" and not running:
        if j is not None:      # just ended; the record is written a moment after the job's end event
            err = next((e.get("error") for e in reversed(j.events) if e.get("type") == "end"), None)
            rec.update(status=j.status, error=None if j.status == "done" else err,
                       ended=rec.get("ended") or time.time())
        else:
            rec.update(status="error", error=rec.get("error") or "IG Studio was restarted before the week was ready.")
    blocked = bool(rec.get("status") == "error" and rec.get("auto")
                   and time.time() - (rec.get("ended") or rec.get("started") or 0) < AUTOPILOT_RETRY_S)
    return {"running": running, "job": rec.get("job") if running else None, "started": rec.get("started"),
            "ended": rec.get("ended"), "status": "running" if running else rec.get("status"),
            "error": None if running else rec.get("error"), "week_of": rec.get("week_of"),
            "auto_blocked": blocked}


@route("GET", "/api/week")
def api_week(h, body):
    today = dt.date.fromisoformat(h.query["today"]) if re.fullmatch(r"\d{4}-\d{2}-\d{2}", h.query.get("today", "")) \
        else dt.date.today()
    this_monday = today - dt.timedelta(days=today.weekday())
    target = plan_monday(today)
    weeks = weeks_sync()
    have = sorted(weeks)
    want = h.query.get("week_of")
    if want not in weeks:
        want = (this_monday.isoformat() if this_monday.isoformat() in weeks
                else target.isoformat() if target.isoformat() in weeks else (have[-1] if have else None))
    week = read_json_file(weeks[want]) if want else None
    if week is not None and not _valid_week(week):
        week = None
    statuses = week_status_all()
    if week:
        for p in week.get("posts") or []:
            if not isinstance(p, dict):
                continue
            st = statuses.get(f"{week['week_of']}/{p.get('id')}") or {}
            edit = edit_summary(h.server, st.get("edit_dir"), st.get("edit_job"))
            stage = st.get("stage") or "script"
            if edit and edit.get("video"):
                stage = max_stage(stage, "edited")
            footage = st.get("footage") if st.get("footage") and os.path.isfile(st.get("footage")) else None
            p["progress"] = {"stage": stage, "ledger_id": st.get("ledger_id"), "posted_at": st.get("posted_at"),
                             "edit": edit, "footage": footage}
    acc = read_json_file(os.path.join(data_dir(), "account.json"))
    return {"today": today.isoformat(), "this_monday": this_monday.isoformat(), "target": target.isoformat(),
            "weeks": have, "week": week, "needs_prepare": target.isoformat() not in weeks,
            "autopilot": autopilot_state(h.server), "claude": bool(find_claude()),
            "daily": daily_state(h.server, daily_target()),
            "handle": active_handle(), "scanned": bool(acc),
            "name": (acc or {}).get("name") if isinstance(acc, dict) else None}


VIRAL_STALE_DAYS = 14     # same as state.py: what is going viral is redone every fortnight


def viral_age_days():
    try:
        return int((time.time() - os.path.getmtime(os.path.join(data_dir(), "viral.json"))) // 86400)
    except OSError:
        return None


def autopilot_prompt(target, handle, note, scanned):
    week_py = script_path("ig/week.py") or os.path.join(skills_dir(), "ig", "week.py")
    data = data_dir()
    vage = viral_age_days()
    sunday = target + dt.timedelta(days=6)
    who = "@" + handle if handle else "this account"
    lines = [
        f"/ig Autopilot. Prepare the week of Monday {target.isoformat()} to Sunday {sunday.isoformat()} "
        f"for {who}, end to end, and ask me nothing.",
        f"Today is {dt.date.today().isoformat()} ({dt.date.today().strftime('%A')}). Data folder: {data}",
        "Follow the ig skill's \"Autopilot\" section exactly: every post gets its full kit "
        "(hook, script, the director's filming notes, caption, sound, cover).",
        "Every post copies a reel that went viral in this niche (its model in viral.json): its hook shape, "
        "structure, pace and tone. Not my own old posts, my old captions or voice.md's tone: those are what "
        "didn't go viral.",
        "Run ig-trends/moments.py first: the biggest moment everyone is talking about right now gets a post "
        "when it has an honest bridge to my niche, as a `now` post before Monday if it can't wait.",
    ]
    if vage is None or vage > VIRAL_STALE_DAYS:
        lines.append(("There is no viral.json yet" if vage is None else f"viral.json is {vage} days old")
                     + ": do the ig-viral skill's Autopilot section first.")
    if not scanned:
        lines.append(f"There is no account scan yet: scan {who} with kweo first (the ig-scan skill) and save "
                     "the profile, voice, ledger and follower baseline without asking.")
    if note:
        lines.append(f"What I want this week: {note}")
    lines += [
        f"Write {os.path.join(data, 'week.json')} with week_of \"{target.isoformat()}\", then run",
        f"  python3 {week_py} check {os.path.join(data, 'week.json')} --fix --json   (until ok is true)",
        f"  python3 {week_py} plan-md {os.path.join(data, 'week.json')}",
        "Finish with three short lines: the headline, the first thing to do and when, and what you assumed.",
    ]
    return "\n".join(lines)


def autopilot_check(target):
    def after(job, run):
        w = read_json_file(os.path.join(data_dir(), "week.json"))
        if not _valid_week(w) or w.get("week_of") != target.isoformat():
            raise ApiError(400, "Claude finished without writing this week's plan (week.json). "
                                "Open Ask Claude to see what happened, or press Prepare again.")
        weeks_sync()
    return after


def run_autopilot(job, server, prompt, log_path, target, auto):
    try:
        run_chat_job_logged(job, server, prompt, None, log_path, None, autopilot_check(target))
    finally:
        err = next((e.get("error") for e in reversed(job.events) if e.get("type") == "end"), None)
        with _week_lock:
            rec = autopilot_record()
            if rec.get("job") == job.id:
                rec.update(status=job.status if job.status in ("done", "error", "cancelled") else "error",
                           ended=time.time(), error=err if job.status != "done" else None)
                try:
                    write_json_atomic(studio_path("autopilot.json"), rec)
                except OSError:
                    pass


@route("POST", "/api/week/prepare")
def api_week_prepare(h, body):
    auto = bool(body.get("auto"))
    note = str(body.get("note") or "").strip()[:1500]
    st = autopilot_state(h.server)
    if st["running"]:
        return {"job": st["job"], "already": True}
    if daily_state(h.server, daily_target()).get("running"):
        raise ApiError(409, "Claude is writing today's trend reel. Prepare the week when it's done.")
    today = dt.date.today()
    target = plan_monday(today)
    if auto:
        if target.isoformat() in weeks_sync():
            raise ApiError(409, "This week is already prepared.")
        if st["auto_blocked"]:
            raise ApiError(409, "The last automatic run failed: " + (st["error"] or "unknown error") +
                           " Press Prepare my week to try again.")
    if not find_claude():
        raise ApiError(503, "Claude Code is not installed.", {"install": "https://claude.com/claude-code"})
    handle = str(body.get("handle") or "").strip().lstrip("@").lower() or active_handle()
    if handle and not re.fullmatch(r"[a-z0-9._]{1,30}", handle):
        raise ApiError(400, "That doesn't look like an Instagram handle.")
    scanned = os.path.isfile(os.path.join(data_dir(), "account.json"))
    prompt = autopilot_prompt(target, handle, note, scanned)
    job = h.new_job("chat", "Preparing your week")
    log_path = chat_log_path()
    shown = "Prepare my week" + (f": {note}" if note else "") + (" (automatic)" if auto else "")
    try:
        chat_log_put(log_path, {"job": job.id, "started": time.time(), "prompt": shown, "attachments": [],
                                "status": "running"})
        with _week_lock:
            write_json_atomic(studio_path("autopilot.json"), {"job": job.id, "started": time.time(),
                                                              "status": "running", "week_of": target.isoformat(),
                                                              "auto": auto})
    except OSError:
        pass
    start_thread(run_autopilot, job, h.server, prompt, log_path, target, auto)
    return {"job": job.id, "week_of": target.isoformat()}


@route("GET", "/api/viral")
def api_viral(h, body):
    """viral.json: the reels going viral in the niche that the week's posts copy."""
    v = read_json_file(os.path.join(data_dir(), "viral.json"))
    reels = [r for r in (v or {}).get("reels") or [] if isinstance(r, dict)] if isinstance(v, dict) else []
    return {"reels": reels, "made": (v or {}).get("made") if isinstance(v, dict) else None,
            "accounts": (v or {}).get("accounts") if isinstance(v, dict) else None,
            "top_formulas": (v or {}).get("top_formulas") if isinstance(v, dict) else [],
            "age_days": viral_age_days(), "stale_days": VIRAL_STALE_DAYS}


@route("POST", "/api/week/post")
def api_week_post(h, body):
    week_of, post = week_post(body.get("week_of"), body.get("id"))
    stage = body.get("stage")
    if stage not in WEEK_STAGES:
        raise ApiError(400, "Stage must be one of " + ", ".join(WEEK_STAGES) + ".")
    cur = week_status_get(week_of, post["id"])
    fields = {"stage": stage}
    if stage == "posted" and not cur.get("ledger_id"):
        hook = post.get("hook") if isinstance(post.get("hook"), dict) else {}
        fmt = post.get("format") if post.get("format") in ("reel", "carousel", "story", "photo") else "reel"
        row = {"format": fmt, "date": dt.date.today().isoformat(), "theme": post.get("type"),
               "first_line": (hook.get("on_screen") or hook.get("spoken") or post.get("title") or "")[:200],
               "length": post.get("length_s"), "notes": f"week {week_of} {post['id']}"}
        if isinstance(hook.get("formula"), int):
            row["hook_formula"] = hook["formula"]
        args = ["add"] + flags(row, LEDGER_META) + (["--trial"] if post.get("trial") else [])
        try:
            r = script_text("ig-ledger/ledger.py", args)
            m = re.search(r"\bP\d{3,}\b", r["output"])
            if m:
                fields["ledger_id"] = m.group(0)
        except ApiError as e:
            fields["ledger_error"] = e.message
        fields["posted_at"] = time.time()
    return {"progress": week_status_put(week_of, post["id"], **fields)}


@route("POST", "/api/week/redo")
def api_week_redo(h, body):
    week_of, post = week_post(body.get("week_of"), body.get("id"))
    note = str(body.get("note") or "").strip()[:1500]
    if not find_claude():
        raise ApiError(503, "Claude Code is not installed.", {"install": "https://claude.com/claude-code"})
    path = week_file(week_of)
    latest = os.path.join(data_dir(), "week.json")
    is_latest = (read_json_file(latest) or {}).get("week_of") == week_of
    target = latest if is_latest else path
    week_py = script_path("ig/week.py") or os.path.join(skills_dir(), "ig", "week.py")
    prompt = (f"/ig Autopilot, one post only. Rewrite the post with id \"{post['id']}\" ({post.get('day')}, "
              f"\"{post.get('title', '')}\") in {target}, with its full kit, following the ig skill's Autopilot "
              f"section. Keep every other post exactly as it is. Ask me nothing. It still copies a reel from "
              f"viral.json in that reel's shape and tone (pick another one if it fits the change better).\n"
              f"What I want changed: {note or 'make it stronger: a better hook and a sharper angle'}\n"
              f"Then run: python3 {week_py} check {target} --fix --json (until ok is true)"
              + (f" and python3 {week_py} plan-md {target}" if is_latest else "") +
              ".\nEnd with one line on what changed.")
    job = h.new_job("chat", "Redoing " + str(post.get("day")))
    log_path = chat_log_path()
    try:
        chat_log_put(log_path, {"job": job.id, "started": time.time(), "attachments": [], "status": "running",
                                "prompt": f"Redo {post.get('day')} \"{post.get('title', '')}\"" + (f": {note}" if note else "")})
    except OSError:
        pass

    def synced(job_, run):
        if target != latest:
            return
        weeks_sync()
    start_thread(run_chat_job_logged, job, h.server, prompt, None, log_path, None, synced)
    return {"job": job.id}


# ---------------------------------------------------------------- the daily trend reel
#
# Every day the app checks what everyone is talking about (ig-trends/moments.py)
# and, when one moment has an honest bridge to the niche, Claude adds one reel
# for that day to the week, with its full kit. After 6pm it is tomorrow's reel.
# .studio/daily.json keeps one record per post date: done, skipped (with why),
# running or error.

DAILY_EVENING_HOUR = 18
DAILY_RETRY_S = 6 * 3600
DAY_IDS = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")


def daily_records():
    d = read_json_file(studio_path("daily.json"))
    return d if isinstance(d, dict) else {}


def daily_put(date, **fields):
    with _week_lock:
        recs = daily_records()
        rec = recs.get(date) if isinstance(recs.get(date), dict) else {}
        rec.update(fields)
        recs[date] = rec
        for k in sorted(recs)[:-60]:          # keep two months
            recs.pop(k, None)
        write_json_atomic(studio_path("daily.json"), recs)
        return rec


def daily_target(now=None):
    """Where today's trend reel goes: {date, week_of, path, latest, id}, or None when no planned week covers it."""
    now = now or dt.datetime.now()
    day = now.date() + dt.timedelta(days=1 if now.hour >= DAILY_EVENING_HOUR else 0)
    weeks = weeks_sync()
    latest = os.path.join(data_dir(), "week.json")
    lw = read_json_file(latest)
    lw = lw if _valid_week(lw) else {}
    monday = (day - dt.timedelta(days=day.weekday())).isoformat()
    if lw.get("week_of") == monday:
        week_of, path = monday, latest
    elif monday in weeks:
        week_of, path = monday, weeks[monday]
    elif lw and day < dt.date.fromisoformat(lw["week_of"]) <= day + dt.timedelta(days=6):
        week_of, path = lw["week_of"], latest            # a `now` post before that week starts
    else:
        return None
    w = read_json_file(path) or {}
    taken = {p.get("id") for p in w.get("posts") or [] if isinstance(p, dict)}
    base = "now" if day.isoformat() < week_of else DAY_IDS[day.weekday()]
    pid = next((c for c in [base] + [f"{base}-{n}" for n in range(2, 10)] if c not in taken), None)
    moment_post = next((p.get("id") for p in w.get("posts") or [] if isinstance(p, dict)
                        and p.get("date") == day.isoformat() and isinstance(p.get("moment"), dict)), None)
    return {"date": day.isoformat(), "week_of": week_of, "path": path, "latest": path == latest,
            "id": pid, "has_moment_post": moment_post}


def daily_state(srv, tgt):
    if not tgt:
        return {"available": False}
    rec = daily_records().get(tgt["date"]) or {}
    j = srv.jobs.get(rec.get("job")) if rec.get("job") else None
    running = bool(j and not j.done)
    status = "running" if running else rec.get("status")
    if rec.get("status") == "running" and not running:
        if j is not None:
            status = j.status                  # just ended; run_daily writes the record a moment later
        else:
            status = "error"
            rec["error"] = rec.get("error") or "IG Studio was restarted before today's reel was ready."
    blocked = bool(status in ("error", "cancelled") and rec.get("auto")
                   and time.time() - (rec.get("ended") or rec.get("started") or 0) < DAILY_RETRY_S)
    return {"available": True, "date": tgt["date"], "week_of": rec.get("week_of") or tgt["week_of"],
            "running": running, "job": rec.get("job") if running else None, "status": status,
            "post_id": rec.get("post_id") or tgt["has_moment_post"], "moment": rec.get("moment"),
            "reason": rec.get("reason"), "error": None if running else rec.get("error"),
            "needs": not rec and not tgt["has_moment_post"] and bool(tgt["id"]), "auto_blocked": blocked}


def daily_prompt(tgt, handle, note=""):
    week_py = script_path("ig/week.py") or os.path.join(skills_dir(), "ig", "week.py")
    moments = script_path("ig-trends/moments.py") or os.path.join(skills_dir(), "ig-trends", "moments.py")
    prof = read_json_file(os.path.join(data_dir(), "profile.json")) or {}
    region = str(prof.get("region") or "IN").upper()[:3] if isinstance(prof, dict) else "IN"
    day = dt.date.fromisoformat(tgt["date"])
    who = "@" + handle if handle else "this account"
    return "\n".join([
        f"/ig Daily. Today's trend reel for {who}, to post on {day.strftime('%A')} {tgt['date']}. Ask me nothing.",
        f"Today is {dt.date.today().isoformat()}. Data folder: {data_dir()}",
        "Follow the ig skill's \"Daily\" section.",
        f"1. Run: python3 {moments} --region {region}",
        "   Pick the one moment everyone is talking about that has an honest bridge to my niche "
        "(never deaths, attacks or disasters).",
        f"2. If one fits, add ONE post to {tgt['path']} with id \"{tgt['id']}\", day \"{day.strftime('%a').upper()}\", "
        f"date \"{tgt['date']}\", type \"trend\", a `moment` object (name, hours_on_x, headline, and reel: a link "
        "to a reel already riffing on it, if you saw one), and the full kit like an Autopilot post. Keep every "
        "other post exactly as it is. Add a todo to film it.",
        f"3. Run: python3 {week_py} check {tgt['path']} --fix --json   (until ok is true)"
        + (f"\n   then: python3 {week_py} plan-md {tgt['path']}" if tgt["latest"] else ""),
        "4. If nothing fits, change nothing and end with one line that starts with \"SKIP:\" and says why, "
        "naming the top moments you passed on.",
        "Otherwise end with one line: the reel, the moment it rides, and when to post it.",
    ] + ([f"What I want today: {note}"] if note else []))


def daily_after(tgt):
    def after(job, run):
        w = read_json_file(tgt["path"]) or {}
        post = next((p for p in w.get("posts") or [] if isinstance(p, dict) and p.get("id") == tgt["id"]), None)
        reply = str((run.final or {}).get("result") or "")
        if post:
            m = post.get("moment") if isinstance(post.get("moment"), dict) else {}
            daily_put(tgt["date"], status="done", post_id=tgt["id"], moment=m.get("name"), ended=time.time())
            weeks_sync()
            return
        skip = re.search(r"SKIP:\s*(.+)", reply)
        if skip:
            daily_put(tgt["date"], status="skipped", reason=skip.group(1).strip()[:400], ended=time.time())
            return
        raise ApiError(400, "Claude finished without adding today's reel. Open Ask Claude to see what happened.")
    return after


def run_daily(job, server, prompt, log_path, tgt):
    try:
        run_chat_job_logged(job, server, prompt, None, log_path, None, daily_after(tgt))
    finally:
        rec = daily_records().get(tgt["date"]) or {}
        if rec.get("job") == job.id and rec.get("status") == "running":
            err = next((e.get("error") for e in reversed(job.events) if e.get("type") == "end"), None)
            try:
                daily_put(tgt["date"], status=job.status if job.status in ("error", "cancelled") else "error",
                          error=err or "Claude stopped.", ended=time.time())
            except OSError:
                pass


@route("POST", "/api/daily")
def api_daily(h, body):
    auto = bool(body.get("auto"))
    note = str(body.get("note") or "").strip()[:1000]
    tgt = daily_target()
    if not tgt:
        raise ApiError(409, "Plan the week first: today's trend reel goes into it.")
    st = daily_state(h.server, tgt)
    if st["running"]:
        return {"job": st["job"], "already": True}
    if autopilot_state(h.server)["running"]:
        raise ApiError(409, "Claude is preparing the week. Today's trend reel comes after.")
    if tgt["has_moment_post"]:
        daily_put(tgt["date"], status="done", post_id=tgt["has_moment_post"], week_of=tgt["week_of"],
                  ended=time.time(), note="the week already rides a moment that day")
        raise ApiError(409, "The week already has a trend reel for that day.")
    if not tgt["id"]:
        raise ApiError(409, "That day already has ten posts.")
    if auto and (st["status"] in ("done", "skipped") or st["auto_blocked"]):
        raise ApiError(409, "Today's trend reel is already " + ("done." if st["status"] != "error" else
                                                              "being retried later."))
    if not find_claude():
        raise ApiError(503, "Claude Code is not installed.", {"install": "https://claude.com/claude-code"})
    job = h.new_job("chat", "Today's trend reel")
    log_path = chat_log_path()
    try:
        chat_log_put(log_path, {"job": job.id, "started": time.time(), "attachments": [], "status": "running",
                                "prompt": "Today's trend reel" + (f": {note}" if note else "")
                                + (" (automatic)" if auto else "")})
        daily_put(tgt["date"], job=job.id, status="running", started=time.time(), auto=auto,
                  week_of=tgt["week_of"], post_id=None, reason=None, error=None, ended=None)
    except OSError:
        pass
    start_thread(run_daily, job, h.server, daily_prompt(tgt, active_handle(), note), log_path, tgt)
    return {"job": job.id, "date": tgt["date"], "id": tgt["id"], "week_of": tgt["week_of"]}


@route("GET", "/api/abtest")
def api_abtest(h, body):
    r = script_json("ig-test/abtest.py", ["list", "--json"])
    return {"tests": r if isinstance(r, list) else []}


@route("POST", "/api/abtest/new")
def api_abtest_new(h, body):
    if not str(body.get("a") or "").strip() or not str(body.get("b") or "").strip():
        raise ApiError(400, "Both hooks are needed.")
    args = ["new"] + flags(body, {"a": "--a", "b": "--b", "formula_a": "--formula-a", "formula_b": "--formula-b",
                                  "theme": "--theme", "length": "--length"}) + ["--json"]
    return script_json("ig-test/abtest.py", args)


@route("POST", "/api/abtest/record")
def api_abtest_record(h, body):
    tid = check_id(str(body.get("test_id") or ""), "test id")
    var = str(body.get("variant") or "").upper()
    if var not in ("A", "B"):
        raise ApiError(400, "Variant is A or B.")
    if body.get("views") in (None, ""):
        raise ApiError(400, "Views are required.")
    args = ["record", tid, var] + flags(body, {"views": "--views", "shares": "--shares", "likes": "--likes",
                                               "comments": "--comments", "saves": "--saves",
                                               "follows": "--follows", "skip_rate": "--skip-rate",
                                               "avg_watch": "--avg-watch"}) + ["--json"]
    return script_json("ig-test/abtest.py", args)


@route("GET", "/api/abtest/report")
def api_abtest_report(h, body):
    tid = check_id(h.query.get("id", ""), "test id")
    return script_json("ig-test/abtest.py", ["report", tid, "--json"])


# ---------------------------------------------------------------- kweo

@route("GET", "/api/kweo")
def api_kweo(h, body):
    r = run_script("ig-kweo/kweo_check.py", ["--json"], timeout=30, with_data=False)
    if r["json"] is None:
        raise ApiError(500, friendly_error(r["err"], r["out"]))
    return r["json"]


KWEO_CONNECT_LINK = "kweo://connect/claude-code?app=IG%20Studio"


@route("POST", "/api/kweo/one-click")
def api_kweo_one_click(h, body):
    """Ask kweo to connect itself to Claude Code. kweo shows its own confirm
    dialog and runs `claude mcp add` with its token, so the token never passes
    through IG Studio. Older kweo versions don't know the link: then
    launched is False and the page falls back to the toggle instructions."""
    if os.environ.get("IG_STUDIO_NO_OPEN"):
        return {"launched": False, "skipped": True}
    try:
        if sys.platform == "darwin":
            r = subprocess.run(["open", KWEO_CONNECT_LINK], capture_output=True, text=True, timeout=15)
            ok = r.returncode == 0
        elif IS_WIN:
            os.startfile(KWEO_CONNECT_LINK)  # noqa: S606 (fixed, local URL scheme)
            ok = True
        else:
            r = subprocess.run(["xdg-open", KWEO_CONNECT_LINK], capture_output=True, text=True, timeout=15)
            ok = r.returncode == 0
    except (OSError, subprocess.SubprocessError, AttributeError):
        ok = False
    return {"launched": ok}


@route("POST", "/api/kweo/connect")
def api_kweo_connect(h, body):
    token = validate_kweo_command(body.get("command"))
    if not token:
        raise ApiError(400, "That is not the kweo command. Copy it exactly from kweo: ⌘J → Connect a model. "
                            "It starts with: claude mcp add kweo --transport http http://127.0.0.1:7333/mcp")
    claude = find_claude()
    if not claude:
        raise ApiError(503, "Claude Code is not installed.")
    cmd = [claude, "mcp", "add", "--scope", "user", "kweo", "--transport", "http", KWEO_URL,
           "--header", f"Authorization: Bearer {token}"]
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=60, env=child_env(False),
                           cwd=os.path.expanduser("~"),
                           **({"creationflags": getattr(subprocess, "CREATE_NO_WINDOW", 0)} if IS_WIN else {}))
    except (OSError, subprocess.SubprocessError) as e:
        raise ApiError(500, f"Could not run claude: {e}")
    out = ((r.stdout or "") + (r.stderr or "")).replace(token, "***").strip()
    if r.returncode != 0:
        msg = out[-600:] or "claude mcp add failed."
        if "already exists" in out:
            msg = ("A server named kweo is already set up. If it stopped working, remove it with "
                   "`claude mcp remove kweo -s user` in a terminal, then paste the new command here.")
        raise ApiError(400, msg)
    return {"ok": True, "output": out[-600:], "restart": True}


# ---------------------------------------------------------------- scan (ig-scan)

def scan_available():
    return bool(script_path("ig-scan/scan.py"))


def read_json_file(p):
    try:
        with open(p, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


@route("GET", "/api/scan")
def api_scan(h, body):
    d = data_dir()
    acc = read_json_file(os.path.join(d, "account.json"))
    md = ""
    try:
        with open(os.path.join(d, "account.md"), encoding="utf-8", errors="replace") as f:
            md = f.read(300_000)
    except OSError:
        pass
    context = None
    if scan_available() and acc is not None:
        try:
            r = run_script("ig-scan/scan.py", ["context", "--json"], timeout=30)
            context = r["json"] if r["json"] is not None else ((r["out"] or "").strip() or None)
        except ApiError:
            context = None
    return {"available": scan_available(), "has_analysis": acc is not None, "account": acc, "md": md,
            "context": context, "modified": dt.datetime.fromtimestamp(os.path.getmtime(os.path.join(d, "account.json"))).isoformat(timespec="minutes") if acc is not None else None}


def need_scan():
    if not scan_available():
        raise ApiError(503, "The account scanner (ig-scan) is not installed yet.")


def scan_after_analyze(rc, out, err):
    res = {"output": out.strip()[-4000:]}
    if rc == 0:
        r = run_script("ig-scan/scan.py", ["analyze", "--json"], timeout=300)
        res["analysis"] = r["json"]
        if r["rc"] != 0:
            res["analyze_error"] = friendly_error(r["err"], r["out"])
    return res


@route("POST", "/api/scan/api")
def api_scan_api(h, body):
    need_scan()
    token = str(body.get("token") or "").strip()
    if not re.fullmatch(r"[A-Za-z0-9._|:-]{10,2048}", token):
        raise ApiError(400, "That does not look like an Instagram access token.")
    args = ["api"]
    try:
        mx = int(body.get("max") or 200)
    except (TypeError, ValueError):
        raise ApiError(400, "Max posts must be a number.")
    args.append(f"--max={max(1, min(mx, 2000))}")
    if body.get("insights"):
        args.append("--insights")
    job = h.new_job("scan", "Scan with the Instagram API")
    start_thread(run_script_job, job, "ig-scan/scan.py", args, 1800, {"IG_ACCESS_TOKEN": token}, [token],
                 scan_after_analyze)
    return {"job": job.id}


@route("POST", "/api/scan/dyi")
def api_scan_dyi(h, body):
    need_scan()
    p = safe_data_path(body.get("path"))
    args = ["dyi", p]
    handle = str(body.get("handle") or "").strip().lstrip("@")
    if handle:
        if not HANDLE_RE.fullmatch(handle):
            raise ApiError(400, "Invalid handle.")
        args.append(f"--handle={handle}")
    fol = str(body.get("followers") or "").replace(",", "").strip()
    if fol:
        if not fol.isdigit():
            raise ApiError(400, "Followers must be a number.")
        args.append(f"--followers={fol}")
    job = h.new_job("scan", "Read your Instagram data download")
    start_thread(run_script_job, job, "ig-scan/scan.py", args, 1800, None, None, scan_after_analyze)
    return {"job": job.id}


@route("POST", "/api/scan/analyze")
def api_scan_analyze(h, body):
    need_scan()
    r = run_script("ig-scan/scan.py", ["analyze", "--json"], timeout=300)
    if r["rc"] != 0:
        raise ApiError(400, friendly_error(r["err"], r["out"]))
    return {"analysis": r["json"], "output": r["out"][-4000:] if r["json"] is None else ""}


@route("POST", "/api/scan/to-ledger")
def api_scan_to_ledger(h, body):
    need_scan()
    args = ["to-ledger", "--json"] + (["--dry-run"] if body.get("dry_run", True) else [])
    r = run_script("ig-scan/scan.py", args, timeout=120)
    if r["rc"] != 0:
        raise ApiError(400, friendly_error(r["err"], r["out"]))
    return {"result": r["json"], "output": (r["out"] or "").strip()[-3000:] if r["json"] is None else ""}


@route("POST", "/api/scan/prefill")
def api_scan_prefill(h, body):
    need_scan()
    r = run_script("ig-scan/scan.py", ["prefill", "--json"], timeout=60)
    if r["rc"] != 0 or not isinstance(r["json"], dict):
        raise ApiError(400, friendly_error(r["err"], r["out"]))
    d = r["json"]
    sug = d.get("suggested") if isinstance(d.get("suggested"), dict) else {}
    fields = {k: v for k, v in sug.items() if k in ("region", "niche", "account_type", "language", "goal")
              and v not in (None, "")}
    return {"fields": fields, "why": d.get("why") or {}, "typical_captions": d.get("typical_captions") or []}


# ---------------------------------------------------------------- chat

SID_RE = re.compile(r"[0-9a-fA-F-]{8,64}")


# Assistant history lives with the account, not only in one browser: a run started from
# anywhere (another browser, a script, a page that was closed mid-run) still shows up.
CHAT_LOG_MAX = 60
_chat_log_lock = threading.Lock()


def chat_log_path():
    return os.path.join(data_dir(), ".studio", "chat.json")


def chat_log_read(path):
    try:
        with open(path, encoding="utf-8") as f:
            d = json.load(f)
        return d if isinstance(d, list) else []
    except (OSError, ValueError):
        return []


def chat_log_put(path, entry):
    with _chat_log_lock:
        current = chat_log_read(path)
        rows = [r for r in current if r.get("job") != entry["job"]]
        old = next((r for r in current if r.get("job") == entry["job"]), {})
        rows.append({**old, **entry})
        rows.sort(key=lambda r: r.get("started") or 0)
        rows = rows[-CHAT_LOG_MAX:]
        os.makedirs(os.path.dirname(path), exist_ok=True)
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(rows, f, ensure_ascii=False)
        os.replace(tmp, path)


def chat_summary(job):
    """The finished run as the Assistant shows it: reply text, steps, files."""
    text, tools, files, sid, status, error = [], [], [], None, job.status, None
    for ev in list(job.events):
        t = ev.get("type")
        if t == "text":
            text.append(ev.get("text") or "")
        elif t == "tool":
            tools.append({"id": ev.get("id"), "summary": ev.get("summary"), "sub": ev.get("sub")})
        elif t == "tool_done":
            for x in tools:
                if x["id"] == ev.get("id"):
                    x["done"], x["error"] = True, bool(ev.get("error"))
        elif t == "file":
            if not any(f["path"] == ev.get("path") for f in files):
                files.append({"path": ev.get("path"), "name": ev.get("name"), "kind": ev.get("kind")})
        elif t == "session":
            sid = ev.get("session_id") or sid
        elif t == "end":
            sid = ev.get("session_id") or sid
            status = ev.get("status") or status
            error = ev.get("error")
    return {"text": "".join(text), "tools": tools, "files": files, "session_id": sid, "status": status,
            "error": error, "ended": time.time()}


def run_chat_job_logged(job, server, prompt, session_id, log_path, extra_tools=None, after_ok=None):
    try:
        run_chat_job(job, server, prompt, session_id, extra_tools, after_ok)
    finally:
        try:
            chat_log_put(log_path, {"job": job.id, **chat_summary(job)})
        except OSError:
            pass


@route("GET", "/api/chat/history")
def api_chat_history(h, body):
    rows = chat_log_read(chat_log_path())
    for r in rows:
        if r.get("status") == "running":
            j = h.server.jobs.get(r.get("job"))
            if j is None:
                r.update(status="error", error="IG Studio was restarted before this reply finished.")
            elif j.done:
                r.update(chat_summary(j))
    return {"entries": rows}


@route("POST", "/api/chat")
def api_chat(h, body):
    prompt = body.get("prompt")
    if not isinstance(prompt, str) or not prompt.strip():
        raise ApiError(400, "Type a message.")
    if len(prompt) > 20000:
        raise ApiError(400, "That message is too long.")
    sid = body.get("session_id")
    if sid is not None and (not isinstance(sid, str) or not SID_RE.fullmatch(sid)):
        sid = None
    files = []
    for p in (body.get("attachments") or [])[:10]:
        files.append(safe_data_path(p))
    if files:
        prompt = prompt.rstrip() + "\n\nAttached files (look at them with the Read tool):\n" + \
            "\n".join(f"- {p}" for p in files)
    if not find_claude():
        raise ApiError(503, "Claude Code is not installed.", {"install": "https://claude.com/claude-code"})
    job = h.new_job("chat", prompt[:60])
    log_path = chat_log_path()
    try:
        chat_log_put(log_path, {"job": job.id, "started": time.time(), "prompt": str(body.get("prompt")).strip(),
                                "attachments": [{"path": p, "name": os.path.basename(p)} for p in files],
                                "status": "running"})
    except OSError:
        pass
    start_thread(run_chat_job_logged, job, h.server, prompt, sid, log_path)
    return {"job": job.id}


@route("GET", "/api/jobs")
def api_jobs(h, body):
    return {"jobs": [j.snapshot() for j in h.server.jobs.all() if not j.done]}


# ---------------------------------------------------------------- startup

def make_server(port=0, token=None):
    token = token or secrets.token_urlsafe(24)
    return StudioServer(port, token)


def bind_server(port):
    if port:
        return make_server(port)
    try:
        return make_server(DEFAULT_PORT)
    except OSError:
        return make_server(0)


def main(argv=None):
    ap = argparse.ArgumentParser(description="IG Studio: the local web app for the ig- skills.")
    ap.add_argument("--port", type=int, default=0, help=f"port (default {DEFAULT_PORT}, else any free port)")
    ap.add_argument("--no-browser", action="store_true", help="do not open a browser")
    args = ap.parse_args(argv)
    augment_path()

    migrate_old_data_home()
    existing = running_instance()
    if existing:
        url = launch_url(existing['port'], existing['token'])
        print(f"IG Studio is already running at http://127.0.0.1:{existing['port']}/")
        if not args.no_browser:
            warm_up_browser()
            open_browser(url)
        return 0

    try:
        srv = bind_server(args.port)
    except OSError as e:
        print(f"Could not start on port {args.port}: {e}", file=sys.stderr)
        return 1
    write_lock(srv.port, srv.token)
    if not os.environ.get("IG_STUDIO_NO_SETUP"):
        start_thread(WHISPER.run)
    atexit.register(release_lock, srv.token)

    def on_signal(signum, frame):
        start_thread(lambda: (srv.shutdown_all(), srv.shutdown()))
    for s in (getattr(signal, "SIGTERM", None), getattr(signal, "SIGHUP", None)):
        if s is not None:
            try:
                signal.signal(s, on_signal)
            except (ValueError, OSError):
                pass

    url = launch_url(srv.port, srv.token)
    if sys.stdout:
        try:
            print(f"IG Studio is running: {url}")
            print("Keep this window open. Press Ctrl+C (or use Settings > Quit) to stop.")
            sys.stdout.flush()
        except (OSError, ValueError):
            pass
    if not args.no_browser:
        start_thread(lambda: (time.sleep(0.4), open_and_confirm(srv, url)))
    try:
        srv.serve_forever(poll_interval=0.5)
    except KeyboardInterrupt:
        pass
    finally:
        srv.shutdown_all()
        srv.server_close()
        release_lock(srv.token)
    return 0


if __name__ == "__main__":
    sys.exit(main())
