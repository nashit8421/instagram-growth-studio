"""
Stand-in for ig-ledger/ledger.py, for ig-test's own tests only.

Implements the shared contract and nothing more: load_rows, save_rows,
add_row, update_row, data_dir, COLUMNS. Reads IG_DATA_DIR on every call so
each test can point it at its own temp dir.
"""

import csv
import os
import re

COLUMNS = ["id", "date", "format", "theme", "hook_formula", "first_line", "length_s",
           "permalink", "views", "reach", "likes", "comments", "shares", "saves",
           "follows", "skip_rate", "nonfollower_pct", "avg_watch_s", "trial",
           "test_id", "variant", "notes"]


def data_dir():
    """The active account's data folder. Same rule as ig-account/account.py:
    $IG_DATA_DIR, else $IG_HOME/accounts/<active-account>/ if it exists,
    else $IG_HOME (default ~/IGStudio)."""
    env = os.environ.get("IG_DATA_DIR")
    if env:
        return os.path.expanduser(env)
    home = os.path.expanduser(os.environ.get("IG_HOME") or "~/IGStudio")
    try:
        with open(os.path.join(home, "active-account"), encoding="utf-8") as f:
            h = f.read().strip().lstrip("@").strip().lower()
    except OSError:
        h = ""
    if h and re.match(r"^[a-z0-9._]{1,30}$", h) and ".." not in h:
        d = os.path.join(home, "accounts", h)
        if os.path.isdir(d):
            return d
    return home


def _path():
    return os.path.join(data_dir(), "posts.csv")


def load_rows():
    if not os.path.exists(_path()):
        return []
    with open(_path(), newline="", encoding="utf-8") as f:
        return [{c: (r.get(c) or "") for c in COLUMNS} for r in csv.DictReader(f)]


def save_rows(rows):
    os.makedirs(data_dir(), exist_ok=True)
    with open(_path(), "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=COLUMNS, extrasaction="ignore")
        w.writeheader()
        for r in rows:
            w.writerow({c: ("" if r.get(c) is None else r.get(c)) for c in COLUMNS})


PCT_FIELDS = ("skip_rate", "nonfollower_pct")


def _clean(fields):
    unknown = set(fields) - set(COLUMNS)
    if unknown:
        raise ValueError("unknown columns: %s" % ", ".join(sorted(unknown)))
    out = {}
    for k, v in fields.items():
        v = "" if v is None else str(v).strip()
        if k in PCT_FIELDS:
            v = v.rstrip("%")
        out[k] = v
    return out


def _next_id(rows):
    nums = [int(r["id"][1:]) for r in rows if r.get("id", "")[1:].isdigit()]
    return "P%04d" % (max(nums, default=0) + 1)


def add_row(**fields):
    rows = load_rows()
    row = {c: "" for c in COLUMNS}
    row.update(_clean(fields))
    row["id"] = row["id"] or _next_id(rows)
    rows.append(row)
    save_rows(rows)
    return row["id"]


def update_row(id, **fields):
    clean = _clean({k: v for k, v in fields.items() if v is not None})
    rows = load_rows()
    for r in rows:
        if r["id"] == id:
            r.update(clean)
            save_rows(rows)
            return r
    raise KeyError(id)
