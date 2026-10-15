#!/usr/bin/env python3
"""
kweo_check.py - is kweo ready for Claude to browse with, and if not, what next.

Four checks, in order. Each one only matters if the one before it passed.

  1. app        /Applications/kweo.app or ~/Applications/kweo.app exists
  2. process    a process named kweo is running (pgrep)
  3. server     POST an MCP initialize to http://127.0.0.1:7333/mcp
                  401          running, needs the bearer token (normal)
                  200          running and open
                  refused      "Let Claude control kweo" is off
  4. claude     `claude mcp list` has a server named kweo

Nothing secret is read or printed. No token is sent, so a running server
answers 401, which is the healthy answer.

Usage
  python3 kweo_check.py
  python3 kweo_check.py --json
Exit code 0 when everything is ready, 1 otherwise.
"""

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import urllib.error
import urllib.request

HOST, PORT = "127.0.0.1", 7333
MCP_URL = f"http://{HOST}:{PORT}/mcp"
INSTALL_URL = "https://kweo.ai"
APP_PATHS = ("/Applications/kweo.app", "~/Applications/kweo.app")
ADD_CMD = (f'claude mcp add kweo --transport http {MCP_URL} '
           f'--header "Authorization: Bearer <token>"')

INIT_BODY = json.dumps({
    "jsonrpc": "2.0", "id": 1, "method": "initialize",
    "params": {"protocolVersion": "2025-03-26", "capabilities": {},
               "clientInfo": {"name": "kweo_check", "version": "1"}},
}).encode()


# ---------------------------------------------------------------- checks

def check_app(paths=APP_PATHS):
    for p in paths:
        full = os.path.expanduser(p)
        if os.path.isdir(full):
            return True, full
    return False, None


def check_process():
    """True if a process called exactly kweo (not only helpers) is running."""
    try:
        r = subprocess.run(["pgrep", "-x", "kweo"], capture_output=True,
                           text=True, timeout=5)
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
        return None
    return r.returncode == 0 and bool(r.stdout.strip())


def check_server(url=MCP_URL, timeout=3):
    """Returns (state, http_code). state: auth | open | off | error."""
    req = urllib.request.Request(url, data=INIT_BODY, method="POST", headers={
        "Content-Type": "application/json",
        "Accept": "application/json, text/event-stream",
    })
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return "open", resp.status
    except urllib.error.HTTPError as e:
        if e.code in (401, 403):
            return "auth", e.code
        return "error", e.code
    except urllib.error.URLError as e:
        reason = getattr(e, "reason", e)
        if isinstance(reason, ConnectionRefusedError) or "refused" in str(reason).lower():
            return "off", None
        return "error", None
    except ConnectionRefusedError:
        return "off", None
    except OSError:
        return "error", None


def check_claude():
    """Returns (state, detail). state: yes | no | missing | error.

    Only the server name is looked at. The line itself can carry a header
    with the token, so it is never printed or returned.
    """
    exe = shutil.which("claude")
    if not exe:
        return "missing", None
    try:
        r = subprocess.run([exe, "mcp", "list"], capture_output=True,
                           text=True, timeout=60)
    except subprocess.TimeoutExpired:
        return "error", "claude mcp list timed out"
    except OSError:
        return "error", "could not run claude"
    for line in (r.stdout or "").splitlines():
        if re.match(r"^\s*kweo\s*:", line):
            ok = "connected" in line.lower() or "✔" in line
            return "yes", "connected" if ok else "registered"
    return "no", None


# ---------------------------------------------------------------- verdict

def run_checks():
    s = {"app": None, "app_path": None, "process": None, "server": None,
         "http_code": None, "claude": None, "claude_detail": None}
    s["app"], s["app_path"] = check_app()
    s["process"] = check_process()
    s["server"], s["http_code"] = check_server()
    s["claude"], s["claude_detail"] = check_claude()
    s["ready"], s["next"] = next_step(s)
    return s


def next_step(s):
    if not s["app"]:
        return False, (f"kweo is not installed. Install it from {INSTALL_URL}, "
                       "open it, then run this again.")
    if s["server"] in ("auth", "open"):
        if s["claude"] == "yes":
            return True, ("Ready. If the mcp__kweo__ tools are not in this session, "
                          "restart Claude Code.")
        if s["claude"] == "missing":
            return False, ("kweo's server is on, but the claude command is not on "
                           "PATH. Add it in Claude Desktop as a custom connector, "
                           f"or install Claude Code. URL: {MCP_URL}")
        return False, ("kweo's server is on but Claude Code does not know it. In kweo "
                       "press Cmd+J, model picker, Connect a model. Copy the command "
                       "it shows. It looks like:\n    " + ADD_CMD + "\n"
                       "Run it yourself with `! <command>` in Claude Code, or paste it "
                       "and Claude runs it. Then restart Claude Code.")
    if s["process"] is False:
        return False, "kweo is installed but not running. Open kweo, then run this again."
    if s["server"] == "off":
        return False, ("kweo is running but its Claude server is off. Press Cmd+J, "
                       "model picker, Connect a model, and turn on "
                       "\"Let Claude control kweo\". Then run this again.")
    return False, (f"Port {PORT} answered something unexpected"
                   f"{' (HTTP ' + str(s['http_code']) + ')' if s['http_code'] else ''}. "
                   "Quit and reopen kweo, toggle \"Let Claude control kweo\" off and "
                   "on, then run this again.")


def render(s, out=None):
    out = out or sys.stdout
    def mark(ok):
        return "ok " if ok else ("-- " if ok is None else "NO ")
    server_txt = {"auth": f"on, needs token (HTTP {s['http_code']}), normal",
                  "open": f"on, open (HTTP {s['http_code']})",
                  "off": "off, connection refused",
                  "error": "unexpected answer"}.get(s["server"], "?")
    claude_txt = {"yes": f"kweo registered ({s['claude_detail']})",
                  "no": "no kweo server registered",
                  "missing": "claude command not found",
                  "error": s["claude_detail"] or "error"}.get(s["claude"], "?")
    print("KWEO CHECK", file=out)
    print(f"  {mark(s['app'])} app       {s['app_path'] or 'not found'}", file=out)
    proc = {True: "running", False: "not running", None: "could not check"}[s["process"]]
    print(f"  {mark(s['process'])} process   {proc}", file=out)
    print(f"  {mark(s['server'] in ('auth', 'open'))} server    {MCP_URL}  {server_txt}",
          file=out)
    print(f"  {mark(s['claude'] == 'yes')} claude    {claude_txt}", file=out)
    print("", file=out)
    print(("READY. " if s["ready"] else "NEXT: ") + s["next"], file=out)


def main(argv=None):
    ap = argparse.ArgumentParser(description="Check kweo is ready for Claude to browse with.")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)
    s = run_checks()
    if args.json:
        print(json.dumps(s, indent=2))
    else:
        render(s)
    return 0 if s["ready"] else 1


if __name__ == "__main__":
    sys.exit(main())
