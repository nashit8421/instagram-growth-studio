#!/usr/bin/env python3
"""
ledger.py - the results log. One row per post, with the numbers it got.

The rest of the pack writes posts. This file remembers how they did.
Instagram's in-app insights only reach back about 90 days, so anything you
want to learn from past that window has to live here.

The ledger is a plain CSV, posts.csv, in the active account's data folder
(see /ig-account: $IG_DATA_DIR, else the active account, else
~/IGStudio). Open it in a spreadsheet if you like. Empty
cell means unknown, never zero.

Usage
  python3 ledger.py add --format reel --hook-formula 3 --first-line "nobody tells you..."
  python3 ledger.py update P0003 --views 12400 --reach 9800 --shares 41 --saves 77
  python3 ledger.py import export.csv            # Meta Business Suite content export
  python3 ledger.py import export.csv --dry-run
  python3 ledger.py list --last 10
  python3 ledger.py list --format reel --json

Importable: other skills do `sys.path.insert(0, <this folder>); import ledger`
and use load_rows(), save_rows(rows), add_row(**fields), update_row(id, **fields).
"""

import argparse
import csv
import datetime as dt
import io
import json
import os
import re
import sys
import tempfile

COLUMNS = [
    "id", "date", "format", "theme", "hook_formula", "first_line", "length_s",
    "permalink", "views", "reach", "likes", "comments", "shares", "saves",
    "follows", "skip_rate", "nonfollower_pct", "avg_watch_s", "trial",
    "test_id", "variant", "notes",
]
FORMATS = ("reel", "carousel", "story", "photo")
INT_FIELDS = ("views", "reach", "likes", "comments", "shares", "saves", "follows")
FLOAT_FIELDS = ("length_s", "skip_rate", "nonfollower_pct", "avg_watch_s")
PCT_FIELDS = ("skip_rate", "nonfollower_pct")
METRIC_FIELDS = INT_FIELDS + ("skip_rate", "nonfollower_pct", "avg_watch_s")
ID_RE = re.compile(r"^P(\d+)$")


# ---------------------------------------------------------------- storage

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


def ledger_path():
    return os.path.join(data_dir(), "posts.csv")


def load_rows():
    """Every row as a dict of strings, all COLUMNS present. [] if no ledger yet."""
    path = ledger_path()
    if not os.path.exists(path):
        return []
    with open(path, encoding="utf-8-sig", newline="") as f:
        rows = []
        for raw in csv.DictReader(f):
            rows.append({c: (raw.get(c) or "").strip() for c in COLUMNS})
    return rows


def save_rows(rows):
    """Write the whole ledger atomically: temp file in the same dir, then os.replace."""
    path = ledger_path()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=".posts.", suffix=".csv", dir=os.path.dirname(path))
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="") as f:
            w = csv.DictWriter(f, fieldnames=COLUMNS, extrasaction="ignore")
            w.writeheader()
            for r in rows:
                w.writerow({c: _cell(r.get(c, "")) for c in COLUMNS})
        os.replace(tmp, path)
    except BaseException:
        if os.path.exists(tmp):
            os.unlink(tmp)
        raise


def _cell(v):
    return "" if v is None else str(v)


# ---------------------------------------------------------------- values

def parse_number(v):
    """'12,400' -> 12400.0, '1.2K' -> 1200.0, '34.5%' -> 34.5, '' / '--' -> None."""
    if v is None:
        return None
    s = str(v).strip().replace(" ", "").replace(" ", "")
    if s in ("", "-", "--", "n/a", "N/A", "null", "None"):
        return None
    s = s.rstrip("%")
    mult = 1
    if s[-1:] in ("K", "k"):
        mult, s = 1000, s[:-1]
    elif s[-1:] in ("M", "m"):
        mult, s = 1000000, s[:-1]
    s = s.replace(",", "")
    try:
        return float(s) * mult
    except ValueError:
        return None


def _fmt_num(x):
    if x is None:
        return ""
    if float(x).is_integer():
        return str(int(x))
    return f"{x:.2f}".rstrip("0").rstrip(".")


def normalize(field, value):
    """Turn whatever the caller passed into the string the CSV stores."""
    if value is None:
        return ""
    if field in INT_FIELDS:
        n = parse_number(value)
        if n is None and str(value).strip():
            raise ValueError(f"{field}: not a number: {value!r}")
        return "" if n is None else str(int(round(n)))
    if field in FLOAT_FIELDS:
        n = parse_number(value)
        if n is None and str(value).strip():
            raise ValueError(f"{field}: not a number: {value!r}")
        if n is not None and field in PCT_FIELDS:
            # Contract stores 0-100. A bare 0.34 is a fraction someone pasted
            # from a spreadsheet, so scale it. "0.34%" keeps its percent sign
            # and is left alone.
            if 0 < n < 1 and "%" not in str(value):
                n *= 100
            if not 0 <= n <= 100:
                raise ValueError(f"{field}: percentage out of range: {value!r}")
        return _fmt_num(n)
    if field == "format":
        f = str(value).strip().lower()
        if f and f not in FORMATS:
            raise ValueError(f"format must be one of {', '.join(FORMATS)}, got {value!r}")
        return f
    if field == "trial":
        if isinstance(value, bool):
            return "yes" if value else ""
        return "yes" if str(value).strip().lower() in ("yes", "y", "true", "1") else ""
    if field == "date":
        s = str(value).strip()
        if s:
            d = parse_date(s)
            if not d:
                raise ValueError(f"date must be YYYY-MM-DD, got {value!r}")
            return d
        return ""
    if field == "variant":
        return str(value).strip().upper()
    if field == "test_id":
        return str(value).strip().upper()
    return " ".join(str(value).split()) if field == "first_line" else str(value).strip()


DATE_FORMATS = (
    "%Y-%m-%d", "%Y-%m-%dT%H:%M:%S%z", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%dT%H:%M%z",
    "%Y-%m-%dT%H:%M", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M",
    "%m/%d/%Y %H:%M", "%m/%d/%Y %H:%M:%S", "%m/%d/%Y", "%m/%d/%y %H:%M", "%m/%d/%y",
    "%d %b %Y", "%b %d, %Y", "%B %d, %Y", "%b %d, %Y %I:%M %p",
)


def parse_date(s):
    """Return YYYY-MM-DD or None. 'Lifetime' (what Meta puts in its Date column) -> None."""
    s = (s or "").strip()
    if not s:
        return None
    for fmt in DATE_FORMATS:
        try:
            return dt.datetime.strptime(s, fmt).strftime("%Y-%m-%d")
        except ValueError:
            continue
    m = re.match(r"^(\d{4}-\d{2}-\d{2})", s)
    if m:
        try:
            return dt.datetime.strptime(m.group(1), "%Y-%m-%d").strftime("%Y-%m-%d")
        except ValueError:
            return None
    return None


# ---------------------------------------------------------------- rows

def next_id(rows):
    top = 0
    for r in rows:
        m = ID_RE.match(r.get("id", ""))
        if m:
            top = max(top, int(m.group(1)))
    return f"P{top + 1:04d}"


def _clean(fields):
    out = {}
    for k, v in fields.items():
        if k not in COLUMNS or k == "id":
            raise ValueError(f"unknown field: {k}")
        out[k] = normalize(k, v)
    return out


def add_row(**fields):
    """Append a post. `format` is required. Returns the new id, e.g. 'P0003'."""
    clean = _clean(fields)
    if not clean.get("format"):
        raise ValueError("format is required (reel, carousel, story, photo)")
    if not clean.get("date"):
        clean["date"] = dt.date.today().isoformat()
    rows = load_rows()
    row = {c: "" for c in COLUMNS}
    row.update(clean)
    row["id"] = next_id(rows)
    rows.append(row)
    save_rows(rows)
    return row["id"]


def update_row(id, **fields):
    """Set the given fields on one row. None leaves a field alone, '' clears it.
    Returns the updated row. Raises KeyError if the id is not in the ledger."""
    clean = _clean({k: v for k, v in fields.items() if v is not None})
    rows = load_rows()
    pid = id.strip().upper()
    for r in rows:
        if r["id"] == pid:
            r.update(clean)
            save_rows(rows)
            return r
    raise KeyError(f"no post with id {pid}")


def get_row(id):
    pid = id.strip().upper()
    for r in load_rows():
        if r["id"] == pid:
            return r
    return None


# ---------------------------------------------------------------- import

# Lower-cased header -> ledger field. Meta renames these every few months and
# the Professional Dashboard export differs from Business Suite's, so match
# on aliases rather than exact names.
ALIASES = {
    "permalink": "permalink", "post link": "permalink", "link": "permalink", "url": "permalink",
    "publish time": "_date", "published": "_date", "publish date": "_date",
    "date published": "_date", "posted": "_date", "date": "_date2",
    "description": "_desc", "caption": "_desc", "post description": "_desc", "title": "_desc",
    "post type": "_type", "type": "_type", "media type": "_type", "content type": "_type",
    "views": "views", "plays": "views", "video views": "views", "impressions": "_impressions",
    "reach": "reach", "accounts reached": "reach",
    "likes": "likes", "comments": "comments",
    "shares": "shares", "sends": "shares",
    "saves": "saves", "saved": "saves",
    "follows": "follows", "follows from post": "follows", "new follows": "follows",
    "skip rate": "skip_rate", "typical skip rate": "skip_rate",
    "non-follower reach": "nonfollower_pct", "nonfollower reach": "nonfollower_pct",
    "non-followers": "nonfollower_pct", "% non-followers": "nonfollower_pct",
    "non-follower %": "nonfollower_pct", "reach from non-followers (%)": "nonfollower_pct",
    "average watch time": "avg_watch_s", "avg watch time": "avg_watch_s",
    "average watch time (sec)": "avg_watch_s", "avg. watch time": "avg_watch_s",
    "duration (sec)": "length_s", "duration": "length_s", "video duration": "length_s",
}


def _header_key(h):
    h = (h or "").replace("﻿", "").strip().lower()
    return re.sub(r"\s+", " ", h)


def map_type(t):
    t = (t or "").strip().lower()
    if not t:
        return ""
    if "reel" in t or "video" in t:
        return "reel"
    if "carousel" in t or "album" in t:
        return "carousel"
    if "stor" in t:
        return "story"
    if "image" in t or "photo" in t or "post" in t:
        return "photo"
    return ""


def _norm_text(s):
    return " ".join((s or "").lower().split())


def prefix_match(first_line, description, n=40):
    """Same post if one opening is a prefix of the other, on the first n chars,
    ignoring case and runs of whitespace. Captions often start with the hook,
    and logged first lines are often a little shorter or longer than the caption."""
    a, b = _norm_text(first_line)[:n], _norm_text(description)[:n]
    if not a or not b:
        return False
    return a.startswith(b) or b.startswith(a)


def read_export(path):
    """Parse a Meta export into a list of dicts keyed by ledger field (plus
    _date/_desc/_type). Unknown columns are ignored."""
    with open(path, "rb") as f:
        raw = f.read()
    for enc in ("utf-8-sig", "utf-16", "cp1252"):
        try:
            text = raw.decode(enc)
            break
        except UnicodeError:
            continue
    text = text.lstrip("﻿")
    # Pick the delimiter from the header line. Sniffer trips on captions
    # with line breaks; European Excel saves with semicolons.
    first = text.split("\n", 1)[0]
    delim = max((",", ";", "\t"), key=first.count)
    reader = csv.reader(io.StringIO(text), delimiter=delim)
    rows = list(reader)
    if not rows:
        return [], []
    header = [_header_key(h) for h in rows[0]]
    mapping = {i: ALIASES[h] for i, h in enumerate(header) if h in ALIASES}
    out = []
    for cells in rows[1:]:
        if not any(c.strip() for c in cells):
            continue
        rec = {}
        for i, field in mapping.items():
            # first non-empty column wins when two headers map to one field
            if i < len(cells) and not rec.get(field):
                rec[field] = cells[i].strip()
        out.append(rec)
    return out, sorted(set(mapping.values()))


def import_file(path, dry_run=False):
    """Merge a Meta export into the ledger. Returns a summary dict.
    Only non-empty values overwrite: an export never blanks out a number you
    already have."""
    records, mapped = read_export(path)
    rows = load_rows()
    summary = {"matched": 0, "created": 0, "skipped": 0, "ids": [], "skipped_reasons": []}
    for rec in records:
        date = parse_date(rec.get("_date", "")) or parse_date(rec.get("_date2", ""))
        desc = rec.get("_desc", "")
        link = rec.get("permalink", "")
        fmt = map_type(rec.get("_type", ""))
        if not link and not date and not desc:
            summary["skipped"] += 1
            summary["skipped_reasons"].append("no permalink, date or description")
            continue
        if "views" not in rec or not rec.get("views"):
            # Older exports call it impressions. Use only if views is missing.
            if rec.get("_impressions"):
                rec["views"] = rec["_impressions"]
        metrics = {}
        for field in METRIC_FIELDS + ("length_s",):
            v = rec.get(field, "")
            if v == "":
                continue
            try:
                n = normalize(field, v)
            except ValueError:
                n = ""
            if n != "":
                metrics[field] = n
        if not metrics:
            summary["skipped"] += 1
            summary["skipped_reasons"].append(f"no numbers: {link or desc[:40] or date}")
            continue

        target = None
        if link:
            key = link.rstrip("/").lower()
            target = next((r for r in rows if r["permalink"]
                           and r["permalink"].rstrip("/").lower() == key), None)
        if target is None and date and desc:
            target = next((r for r in rows if r["date"] == date and r["first_line"]
                           and prefix_match(r["first_line"], desc)), None)
        if target is not None:
            target.update(metrics)
            if link and not target["permalink"]:
                target["permalink"] = link
            if fmt and not target["format"]:
                target["format"] = fmt
            summary["matched"] += 1
            summary["ids"].append(("matched", target["id"]))
        else:
            row = {c: "" for c in COLUMNS}
            row.update(metrics)
            row["id"] = next_id(rows)
            row["date"] = date or ""
            row["format"] = fmt or ""
            row["permalink"] = link
            first = desc.strip().splitlines()[0] if desc.strip() else ""
            row["first_line"] = " ".join(first.split())[:150]
            row["notes"] = "imported"
            rows.append(row)
            summary["created"] += 1
            summary["ids"].append(("created", row["id"]))
    if not dry_run:
        save_rows(rows)
    summary["mapped_columns"] = [m for m in mapped if not m.startswith("_")]
    return summary


# ---------------------------------------------------------------- list

def filter_rows(rows, fmt=None, last=None):
    if fmt:
        rows = [r for r in rows if r["format"] == fmt]
    if last:
        rows = rows[-last:]
    return rows


def render_list(rows, out=None):
    out = out or sys.stdout
    head = f"LEDGER  ·  {len(rows)} posts"
    print("\n" + head + "\n" + ledger_path(), file=out)
    print("=" * 78, file=out)
    if not rows:
        print("  nothing logged yet. Add one with: ledger.py add --format reel", file=out)
        return
    print(f"  {'id':<6} {'date':<10} {'fmt':<8} {'hook':>4} {'views':>9} {'reach':>9} "
          f"{'sends':>6} {'saves':>6} {'follows':>7}  first line", file=out)
    for r in rows:
        def n(k):
            v = parse_number(r[k])
            return f"{int(v):,}" if v is not None else "-"
        flag = " [trial]" if r["trial"] == "yes" else ""
        test = f" [{r['test_id']}{r['variant']}]" if r["test_id"] else ""
        print(f"  {r['id']:<6} {r['date'] or '-':<10} {r['format'] or '-':<8} "
              f"{r['hook_formula'] or '-':>4} {n('views'):>9} {n('reach'):>9} "
              f"{n('shares'):>6} {n('saves'):>6} {n('follows'):>7}  "
              f"{(r['first_line'] or '')[:40]}{flag}{test}", file=out)
    missing = sum(1 for r in rows if not r["views"])
    if missing:
        print("-" * 78, file=out)
        print(f"  {missing} of {len(rows)} have no views yet. Add them with update or import.",
              file=out)
    print(file=out)


def render_row(r, out=None):
    out = out or sys.stdout
    width = max(len(c) for c in COLUMNS)
    for c in COLUMNS:
        print(f"  {c:<{width}}  {r[c]}", file=out)


# ---------------------------------------------------------------- cli

def _add_post_args(p, update=False):
    p.add_argument("--date", help="YYYY-MM-DD" + ("" if update else " (default today)"))
    p.add_argument("--format", choices=FORMATS, required=not update)
    p.add_argument("--theme")
    p.add_argument("--hook-formula", help="formula id from ig-reel/hooks.json, e.g. 3")
    p.add_argument("--first-line")
    p.add_argument("--length", help="length in seconds")
    p.add_argument("--permalink")
    p.add_argument("--test-id", help="e.g. T001")
    p.add_argument("--variant", choices=("A", "B", "a", "b"))
    p.add_argument("--notes")


def main(argv=None):
    ap = argparse.ArgumentParser(description="The results log: one row per post, with its numbers.")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("add", help="log a new post, prints its id")
    _add_post_args(p)
    p.add_argument("--trial", action="store_true", help="trial reel (shown to non-followers only)")

    p = sub.add_parser("update", help="add numbers or fix fields on one post")
    p.add_argument("id")
    for flag in ("views", "reach", "likes", "comments", "shares", "saves", "follows"):
        p.add_argument(f"--{flag}")
    p.add_argument("--skip-rate", help="percent, 0-100")
    p.add_argument("--nonfollower-pct", help="percent of reach from non-followers, 0-100")
    p.add_argument("--avg-watch", help="average watch time in seconds")
    _add_post_args(p, update=True)
    p.add_argument("--trial", dest="trial", action="store_const", const="yes")
    p.add_argument("--no-trial", dest="trial", action="store_const", const="")

    p = sub.add_parser("import", help="merge a Meta Business Suite CSV export")
    p.add_argument("file")
    p.add_argument("--dry-run", action="store_true", help="show what would change, write nothing")

    p = sub.add_parser("list", help="show the ledger")
    p.add_argument("--json", action="store_true")
    p.add_argument("--format", choices=FORMATS)
    p.add_argument("--last", type=int)

    args = ap.parse_args(argv)
    try:
        if args.cmd == "add":
            pid = add_row(date=args.date, format=args.format, theme=args.theme,
                          hook_formula=args.hook_formula, first_line=args.first_line,
                          length_s=args.length, permalink=args.permalink,
                          trial=args.trial, test_id=args.test_id, variant=args.variant,
                          notes=args.notes)
            print(pid)
        elif args.cmd == "update":
            fields = dict(views=args.views, reach=args.reach, likes=args.likes,
                          comments=args.comments, shares=args.shares, saves=args.saves,
                          follows=args.follows, skip_rate=args.skip_rate,
                          nonfollower_pct=args.nonfollower_pct, avg_watch_s=args.avg_watch,
                          date=args.date, format=args.format, theme=args.theme,
                          hook_formula=args.hook_formula, first_line=args.first_line,
                          length_s=args.length, permalink=args.permalink,
                          test_id=args.test_id, variant=args.variant, notes=args.notes,
                          trial=args.trial)
            render_row(update_row(args.id, **fields))
        elif args.cmd == "import":
            s = import_file(args.file, dry_run=args.dry_run)
            tag = "  (dry run, nothing written)" if args.dry_run else ""
            print(f"matched {s['matched']}, created {s['created']}, skipped {s['skipped']}{tag}")
            print("columns used: " + (", ".join(s["mapped_columns"]) or "none"))
            for why in s["skipped_reasons"]:
                print(f"  skipped: {why}")
            if s["created"]:
                print("New rows have no hook formula or theme. Fill those in with "
                      "update, or the audit cannot group them.")
        elif args.cmd == "list":
            rows = filter_rows(load_rows(), args.format, args.last)
            if args.json:
                print(json.dumps(rows, indent=2, ensure_ascii=False))
            else:
                render_list(rows)
    except (ValueError, KeyError, OSError) as e:
        msg = e.args[0] if isinstance(e, KeyError) and e.args else e
        print(f"error: {msg}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
