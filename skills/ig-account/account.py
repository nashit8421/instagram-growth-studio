#!/usr/bin/env python3
"""
account.py - keep more than one Instagram account's data apart.

Every skill in the pack reads and writes files (voice.md, brand.json,
posts.csv, swipe.md, plan.md, log.md, engaged.md, ...) in one data folder.
This script decides which folder that is, and manages one folder per account.

Data folder rule (every skill implements exactly this):
  1. $IG_DATA_DIR if set
  2. else if $IG_HOME/active-account names a handle h AND
     $IG_HOME/accounts/<h>/ exists, that folder
  3. else $IG_HOME  (single-account, the original layout)
$IG_HOME defaults to ~/IGStudio.

Usage
  python3 account.py list [--json]
  python3 account.py new HANDLE [--from-current --yes] [--template voice.md] [--json]
  python3 account.py use HANDLE
  python3 account.py use --none
  python3 account.py current [--json]
  python3 account.py path
  python3 account.py remove HANDLE --yes

In shell:  DATA=$(python3 ~/.claude/skills/ig-account/account.py path)

Nothing is ever hard-deleted. --from-current and remove leave a copy in
$IG_HOME/backup-<timestamp>/.
"""

import argparse
import datetime
import json
import os
import re
import shutil
import sys

HERE = os.path.dirname(os.path.abspath(__file__))

ACCOUNTS = "accounts"
ACTIVE = "active-account"
BACKUP_PREFIX = "backup-"
# Things at the top of $IG_HOME that are bookkeeping, not account data.
RESERVED = {ACCOUNTS, ACTIVE}
TEMPLATE_CANDIDATES = [
    os.path.join(HERE, "..", "..", "templates", "voice.md"),
    os.path.join(HERE, "..", "..", "upstream", "templates", "voice.md"),
    os.path.join(HERE, "voice.template.md"),
]

HANDLE_RE = re.compile(r"^[a-z0-9._]{1,30}$")


class AccountError(Exception):
    pass


# ---------------------------------------------------------------- resolver

def ig_home():
    return os.path.expanduser(os.environ.get("IG_HOME") or "~/IGStudio")


def normalize(handle):
    """Strip whitespace and leading @, lowercase. No validation."""
    return (handle or "").strip().lstrip("@").strip().lower()


def handle_error(handle):
    """None if the (normalized) handle is a legal Instagram username, else why not."""
    h = normalize(handle)
    if not h:
        return "handle is empty"
    if len(h) > 30:
        return f"'{h}' is {len(h)} characters; Instagram allows 30"
    if not HANDLE_RE.match(h):
        bad = sorted(set(c for c in h if not re.match(r"[a-z0-9._]", c)))
        return f"'{h}' has characters Instagram does not allow: {' '.join(bad)} (letters, digits, . and _ only)"
    if h.startswith(".") or h.endswith("."):
        return f"'{h}' cannot start or end with a period"
    if ".." in h:
        return f"'{h}' cannot have two periods in a row"
    return None


def valid_handle(handle):
    return handle_error(handle) is None


def account_dir(handle, home=None):
    return os.path.join(home or ig_home(), ACCOUNTS, normalize(handle))


def active_handle(home=None):
    """The handle in active-account if it is valid and its folder exists, else None."""
    home = home or ig_home()
    try:
        with open(os.path.join(home, ACTIVE), encoding="utf-8") as f:
            h = normalize(f.read())
    except OSError:
        return None
    if valid_handle(h) and os.path.isdir(account_dir(h, home)):
        return h
    return None


def resolve_data_dir():
    """The data folder every skill should use. See the module docstring."""
    env = os.environ.get("IG_DATA_DIR")
    if env:
        return os.path.expanduser(env)
    home = ig_home()
    h = active_handle(home)
    return account_dir(h, home) if h else home


# ---------------------------------------------------------------- helpers

def list_handles(home=None):
    root = os.path.join(home or ig_home(), ACCOUNTS)
    if not os.path.isdir(root):
        return []
    return sorted(n for n in os.listdir(root)
                  if valid_handle(n) and n == normalize(n) and os.path.isdir(os.path.join(root, n)))


def require_handle(handle):
    err = handle_error(handle)
    if err:
        raise AccountError(f"invalid handle: {err}")
    return normalize(handle)


def new_backup_dir(home):
    stamp = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
    path = os.path.join(home, BACKUP_PREFIX + stamp)
    n = 2
    while os.path.exists(path):
        path = os.path.join(home, f"{BACKUP_PREFIX}{stamp}-{n}")
        n += 1
    os.makedirs(path)
    return path


def single_account_items(home):
    """Top-level entries in $IG_HOME that belong to the single-account layout."""
    if not os.path.isdir(home):
        return []
    return sorted(n for n in os.listdir(home)
                  if n not in RESERVED and not n.startswith(BACKUP_PREFIX) and n != ".DS_Store")


def copy_any(src, dst):
    if os.path.isdir(src):
        shutil.copytree(src, dst)
    else:
        shutil.copy2(src, dst)


def find_template(explicit=None):
    if explicit:
        p = os.path.expanduser(explicit)
        if not os.path.isfile(p):
            raise AccountError(f"template not found: {p}")
        return p
    for p in TEMPLATE_CANDIDATES:
        if os.path.isfile(p):
            return os.path.normpath(p)
    return None


def write_active(home, handle):
    os.makedirs(home, exist_ok=True)
    tmp = os.path.join(home, ACTIVE + ".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        f.write(handle + "\n")
    os.replace(tmp, os.path.join(home, ACTIVE))


def read_active_raw(home):
    try:
        with open(os.path.join(home, ACTIVE), encoding="utf-8") as f:
            return normalize(f.read()) or None
    except OSError:
        return None


# ---------------------------------------------------------------- commands

def cmd_list(args):
    home = ig_home()
    active = active_handle(home)
    handles = list_handles(home)
    override = os.environ.get("IG_DATA_DIR")
    if args.json:
        print(json.dumps({"home": home, "active": active, "data_dir": resolve_data_dir(),
                          "ig_data_dir_override": bool(override),
                          "accounts": [{"handle": h, "active": h == active, "path": account_dir(h, home)}
                                       for h in handles]}, indent=2))
        return 0
    if not handles:
        print(f"No accounts yet. Single-account mode, data in {home}")
        print("Add one with: account.py new HANDLE   (--from-current --yes to move existing files in)")
    else:
        for h in handles:
            print(f"{'*' if h == active else ' '} @{h}")
        if not active:
            print(f"\nNo active account. Data in {home} (single-account). Pick one with: account.py use HANDLE")
    if override:
        print(f"\nNote: IG_DATA_DIR is set, so every skill uses {os.path.expanduser(override)}")
    return 0


def cmd_new(args):
    home = ig_home()
    h = require_handle(args.handle)
    dest = account_dir(h, home)
    if os.path.exists(dest):
        raise AccountError(f"@{h} already exists at {dest}")
    moved, backup = [], None
    if args.from_current:
        items = single_account_items(home)
        if not items:
            raise AccountError(f"nothing to move: no single-account files in {home}")
        if not args.yes:
            print(f"This will MOVE these from {home} into {dest}:")
            for n in items:
                print(f"  {n}")
            print(f"A copy goes to {home}/{BACKUP_PREFIX}<timestamp>/ first. Re-run with --yes to do it.")
            return 2
        backup = new_backup_dir(home)
        for n in items:                      # backup first, all of it, then move
            copy_any(os.path.join(home, n), os.path.join(backup, n))
        os.makedirs(dest)
        for n in items:
            shutil.move(os.path.join(home, n), os.path.join(dest, n))
            moved.append(n)
    else:
        os.makedirs(dest)
    template = None
    if not os.path.exists(os.path.join(dest, "voice.md")):
        template = find_template(args.template)
        if template:
            shutil.copy2(template, os.path.join(dest, "voice.md"))
    if args.json:
        print(json.dumps({"handle": h, "path": dest, "moved": moved, "backup": backup,
                          "voice_template": template}, indent=2))
        return 0
    print(f"Created @{h}: {dest}")
    if moved:
        print(f"Moved {len(moved)} item(s) in: {', '.join(moved)}")
        print(f"Backup copy: {backup}")
    if template:
        print("Copied the voice.md template in. Fill it in for this account.")
    elif not os.path.exists(os.path.join(dest, "voice.md")):
        print("No voice.md yet. Copy templates/voice.md in and fill it in for this account.")
    if active_handle(home) != h:
        print(f"Not active yet. Switch with: account.py use {h}")
    return 0


def cmd_use(args):
    home = ig_home()
    if args.none:
        if args.handle:
            raise AccountError("give a handle or --none, not both")
        try:
            os.remove(os.path.join(home, ACTIVE))
        except FileNotFoundError:
            pass
        print(f"No active account. Single-account mode, data in {home}")
        return 0
    if not args.handle:
        raise AccountError("use needs a HANDLE (or --none)")
    h = require_handle(args.handle)
    if not os.path.isdir(account_dir(h, home)):
        known = ", ".join("@" + x for x in list_handles(home)) or "none"
        raise AccountError(f"no account @{h} (known: {known}). Create it with: account.py new {h}")
    write_active(home, h)
    print(f"Active account: @{h}  ({account_dir(h, home)})")
    if os.environ.get("IG_DATA_DIR"):
        print("Note: IG_DATA_DIR is set and overrides this until you unset it.")
    return 0


def cmd_current(args):
    home = ig_home()
    h = active_handle(home)
    path = resolve_data_dir()
    override = os.environ.get("IG_DATA_DIR")
    source = "IG_DATA_DIR" if override else ("account" if h else "single-account")
    stale = read_active_raw(home)
    stale = stale if stale and stale != h else None
    if args.json:
        print(json.dumps({"handle": h, "data_dir": path, "source": source,
                          "home": home, "ignored_active": stale}, indent=2))
        return 0
    if override:
        print(f"IG_DATA_DIR override  {path}")
    elif h:
        print(f"@{h}  {path}")
    else:
        print(f"(no active account)  {path}")
    if stale:
        print(f"Warning: active-account says '{stale}' but that is not a valid account folder; ignored.",
              file=sys.stderr)
    return 0


def cmd_path(args):
    print(resolve_data_dir())
    return 0


def cmd_remove(args):
    home = ig_home()
    h = require_handle(args.handle)
    src = account_dir(h, home)
    if not os.path.isdir(src):
        raise AccountError(f"no account @{h}")
    if not args.yes:
        print(f"This moves {src} to {home}/{BACKUP_PREFIX}<timestamp>/{ACCOUNTS}/{h}. "
              "Nothing is deleted. Re-run with --yes to do it.")
        return 2
    was_active = read_active_raw(home) == h
    backup = new_backup_dir(home)
    os.makedirs(os.path.join(backup, ACCOUNTS))
    dest = os.path.join(backup, ACCOUNTS, h)
    shutil.move(src, dest)
    if was_active:
        os.remove(os.path.join(home, ACTIVE))
    print(f"Removed @{h}. Its files are in {dest}")
    if was_active:
        print(f"It was active; now single-account mode, data in {home}")
    return 0


def build_parser():
    ap = argparse.ArgumentParser(description="Manage Instagram accounts for the ig-* skills.")
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("list", help="list accounts, * marks the active one")
    p.add_argument("--json", action="store_true")
    p.set_defaults(fn=cmd_list)
    p = sub.add_parser("new", help="create an account folder")
    p.add_argument("handle")
    p.add_argument("--from-current", action="store_true",
                   help="move the existing single-account files into it (needs --yes)")
    p.add_argument("--yes", action="store_true")
    p.add_argument("--template", help="voice.md template to copy in")
    p.add_argument("--json", action="store_true")
    p.set_defaults(fn=cmd_new)
    p = sub.add_parser("use", help="make an account active")
    p.add_argument("handle", nargs="?")
    p.add_argument("--none", action="store_true", help="back to single-account mode")
    p.set_defaults(fn=cmd_use)
    p = sub.add_parser("current", help="print the active handle and data folder")
    p.add_argument("--json", action="store_true")
    p.set_defaults(fn=cmd_current)
    p = sub.add_parser("path", help="print the resolved data folder only")
    p.set_defaults(fn=cmd_path)
    p = sub.add_parser("remove", help="move an account to a backup folder")
    p.add_argument("handle")
    p.add_argument("--yes", action="store_true")
    p.set_defaults(fn=cmd_remove)
    return ap


def main(argv=None):
    args = build_parser().parse_args(argv)
    try:
        return args.fn(args)
    except AccountError as e:
        print(f"error: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
