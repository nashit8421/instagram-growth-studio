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
    "mcp__kweo__browser_navigate", "mcp__kweo__browser_read", "mcp__kweo__browser_wait", "mcp__kweo__browser_tabs",
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
        "scannable: short paragraphs, lists, and fenced blocks only for copy-ready text. The app also has "
        "Today, Account, Create, Posts, Growth, Trends & Sound, Calendar and Settings screens."
    )


def tool_summary(name, inp):
    inp = inp if isinstance(inp, dict) else {}
    if name == "Bash":
        cmd = str(inp.get("command", ""))
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
        return f"Starting helper: {inp.get('subagent_type') or inp.get('description') or 'agent'}"
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


def run_chat_job(job, server, prompt, session_id):
    claude = find_claude()
    if not claude:
        job.finish("error", error="Claude Code is not installed. Install it from https://claude.com/claude-code.")
        return
    cwd = data_dir()
    os.makedirs(cwd, exist_ok=True)
    cmd = [claude, "-p", "--output-format", "stream-json", "--verbose", "--include-partial-messages",
           "--add-dir", skills_dir(),
           "--append-system-prompt", system_context(),
           "--allowedTools", ",".join(ALLOWED_TOOLS),
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
    }


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
    start_thread(run_chat_job, job, h.server, prompt, sid)
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
