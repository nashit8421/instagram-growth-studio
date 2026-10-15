#!/usr/bin/env python3
"""
scan.py - read the Instagram account we are growing, and write down what it is.

Every other skill gives better advice when it knows the account: its niche,
its size, how often it posts, which formats and hooks work for it, how it
sounds. This script collects the posts from one of four sources, then turns
them into account.md (for people and Claude) and account.json (for scripts).

Sources, best first
  python3 scan.py api [--max 200] [--insights]     # IG_ACCESS_TOKEN in env, read-only
  python3 scan.py ingest --captured captured.json  # Claude browsed via /ig-kweo, or read screenshots
  python3 scan.py dyi ~/Downloads/instagram-xyz.zip [--followers N]   # Download Your Information export

Then
  python3 scan.py analyze [--json]     # writes $DATA/account.md + $DATA/account.json
  python3 scan.py context [--json]     # 10-15 lines other skills paste into their thinking
  python3 scan.py to-ledger [--dry-run]
  python3 scan.py prefill [--json]     # suggested `state.py set` values + typical captions

Nothing here posts, likes, follows or messages. The API source is read-only
and the token is read from the environment only: never printed, never saved.
Stdlib only. Data folder: IG_DATA_DIR, else $IG_HOME/accounts/<active>,
else $IG_HOME (default ~/.claude/instagram).
"""

import argparse
import collections
import datetime as dt
import io
import json
import os
import re
import statistics
import sys
import time
import unicodedata
import urllib.error
import urllib.parse
import urllib.request
import zipfile

HERE = os.path.dirname(os.path.abspath(__file__))
SKILLS = os.path.dirname(HERE)

API_BASE = "https://graph.instagram.com"
API_VERSION = "v25.0"           # checked 2026-10-15 against developers.facebook.com
PROFILE_FIELDS = ("user_id,username,name,account_type,profile_picture_url,followers_count,"
                  "follows_count,media_count,biography,website")
PROFILE_FIELDS_MIN = "user_id,username,account_type,followers_count,follows_count,media_count"
MEDIA_FIELDS = "id,caption,media_type,media_product_type,timestamp,permalink,like_count,comments_count"
MEDIA_FIELDS_MIN = "id,caption,media_type,timestamp,permalink,like_count,comments_count"
INSIGHTS_ALL = ("reach", "views", "saved", "shares", "total_interactions")
INSIGHTS_REELS = ("ig_reels_avg_watch_time", "reels_skip_rate")
PAGE_SIZE = 50
MAX_POSTS = 200

TYPES = ("reel", "carousel", "photo", "story")
METRICS = ("likes", "comments", "views", "reach", "saves", "shares", "follows", "avg_watch_s",
           "skip_rate", "nonfollower_pct")
STALE_DAYS = 30
THIN = 3

TIERS = ((10_000, "nano"), (100_000, "micro"), (500_000, "mid"), (1_000_000, "macro"))


# ---------------------------------------------------------------- paths

def ig_home():
    return os.path.expanduser(os.environ.get("IG_HOME") or "~/.claude/instagram")


def data_dir():
    """Same rule as ig-account/account.py."""
    env = os.environ.get("IG_DATA_DIR")
    if env:
        return os.path.expanduser(env)
    home = ig_home()
    try:
        with open(os.path.join(home, "active-account"), encoding="utf-8") as f:
            h = f.read().strip().lstrip("@").strip().lower()
    except OSError:
        h = ""
    if h and re.fullmatch(r"[a-z0-9._]{1,30}", h) and ".." not in h:
        d = os.path.join(home, "accounts", h)
        if os.path.isdir(d):
            return d
    return home


def scan_dir():
    return os.path.join(data_dir(), "scan")


def _skill_dirs():
    env = os.environ.get("IG_SKILLS_DIR")
    dirs = [env] if env else []
    dirs += [SKILLS, os.path.join(SKILLS, "..", "upstream", "skills"),
             os.path.expanduser("~/.claude/skills")]
    return [d for d in dirs if d and os.path.isdir(d)]


def _find_skill(*parts):
    for base in _skill_dirs():
        p = os.path.join(base, *parts)
        if os.path.exists(p):
            return p
    return None


def _import_from(skill, module):
    """Import ig-<skill>/<module>.py from the first install that has it."""
    path = _find_skill(skill, module + ".py")
    if not path:
        return None
    folder = os.path.dirname(path)
    if folder not in sys.path:
        sys.path.insert(0, folder)
    try:
        import importlib
        return importlib.import_module(module)
    except Exception:
        return None


def hashtag_cap():
    for base in _skill_dirs() + [os.path.join(SKILLS, "..", "upstream")]:
        p = os.path.join(base, "platform.json")
        try:
            with open(p, encoding="utf-8") as f:
                v = json.load(f)["facts"]["hashtag_cap"]["value"]
            if isinstance(v, int) and v > 0:
                return v
        except (OSError, ValueError, KeyError, TypeError):
            continue
    return 5


def _write_json(path, obj):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(obj, f, indent=2, ensure_ascii=False)
        f.write("\n")
    os.replace(tmp, path)


def _read_json(path, default=None):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return default


def _now():
    return dt.datetime.now().replace(microsecond=0).isoformat()


# ---------------------------------------------------------------- normalizing

def norm_type(t, url=""):
    t = (t or "").strip().lower()
    if "stor" in t:
        return "story"
    if "reel" in t or "video" in t or "clip" in t:
        return "reel"
    if "carousel" in t or "album" in t or "sidecar" in t:
        return "carousel"
    if "photo" in t or "image" in t or "feed" in t or t == "post":
        return "photo"
    if "/reel/" in (url or ""):
        return "reel"
    return "photo" if not t else "photo"


def norm_date(v):
    """YYYY-MM-DD from an ISO string, a unix timestamp or a few common forms."""
    if v is None or v == "":
        return None
    if isinstance(v, (int, float)):
        try:
            return dt.datetime.fromtimestamp(v, dt.timezone.utc).date().isoformat()
        except (OverflowError, OSError, ValueError):
            return None
    s = str(v).strip()
    m = re.match(r"(\d{4})-(\d{2})-(\d{2})", s)
    if m:
        try:
            return dt.date(int(m[1]), int(m[2]), int(m[3])).isoformat()
        except ValueError:
            return None
    for fmt in ("%d/%m/%Y", "%b %d, %Y", "%B %d, %Y", "%d %b %Y", "%d %B %Y"):
        try:
            return dt.datetime.strptime(s, fmt).date().isoformat()
        except ValueError:
            continue
    return None


def num(v):
    """'12,400' -> 12400, '1.2K' -> 1200, '' / None / '--' -> None."""
    if v is None or isinstance(v, bool):
        return None
    if isinstance(v, (int, float)):
        return v
    s = str(v).strip().replace(",", "").replace(" ", "").lower()
    if s in ("", "-", "--", "n/a", "null", "none", "hidden"):
        return None
    mult = 1
    if s.endswith("k"):
        mult, s = 1_000, s[:-1]
    elif s.endswith("m"):
        mult, s = 1_000_000, s[:-1]
    s = s.rstrip("%")
    try:
        x = float(s) * mult
    except ValueError:
        return None
    return int(round(x)) if x.is_integer() or mult > 1 else x


def norm_post(p, source):
    url = (p.get("url") or p.get("permalink") or "").strip()
    out = {
        "id": str(p.get("id") or ""),
        "date": norm_date(p.get("date") or p.get("timestamp")),
        "type": norm_type(p.get("type") or p.get("media_type"), url),
        "caption": (p.get("caption") or "").strip(),
        "url": url,
        "source": p.get("source") or source,
    }
    for k in METRICS:
        out[k] = num(p.get(k))
    return out


def norm_account(a, source):
    at = (a.get("account_type") or "").strip().lower()
    at = {"media_creator": "creator", "creator": "creator", "business": "business",
          "personal": "personal"}.get(at, "unknown" if not at else at)
    return {
        "handle": (a.get("handle") or a.get("username") or "").strip().lstrip("@").lower(),
        "name": (a.get("name") or "").strip(),
        "bio": (a.get("bio") or a.get("biography") or "").strip(),
        "website": (a.get("website") or "").strip(),
        "followers": num(a.get("followers") if a.get("followers") is not None else a.get("followers_count")),
        "following": num(a.get("following") if a.get("following") is not None else a.get("follows_count")),
        "posts_count": num(a.get("posts_count") if a.get("posts_count") is not None else a.get("media_count")),
        "account_type": at,
        "category": (a.get("category") or "").strip(),
        "source": source,
    }


def _key_text(s, n=40):
    return " ".join((s or "").lower().split())[:n]


def same_post(a, b):
    if a.get("url") and b.get("url"):
        return a["url"].rstrip("/").lower() == b["url"].rstrip("/").lower()
    if a.get("date") and a.get("date") == b.get("date"):
        x, y = _key_text(a.get("caption")), _key_text(b.get("caption"))
        if x and y:
            return x.startswith(y) or y.startswith(x)
        return not x and not y and a.get("type") == b.get("type")
    return False


def merge_posts(old, new):
    """New values fill in and update; a missing new value never blanks an old one."""
    merged = [dict(p) for p in old]
    for p in new:
        hit = next((m for m in merged if same_post(m, p)), None)
        if hit is None:
            merged.append(dict(p))
            continue
        for k, v in p.items():
            if v not in (None, ""):
                if k == "caption" and hit.get("caption") and len(hit["caption"]) > len(v):
                    continue                      # keep the fuller caption
                hit[k] = v
    merged.sort(key=lambda p: p.get("date") or "", reverse=True)
    return merged


def save_scan(account, posts, source, raw, replace=False, insights=()):
    """Write scan/account.json, scan/posts.json and the raw source.
    `insights` are url-keyed number sets that only fill posts already known.
    Returns (account, posts, notes)."""
    d = scan_dir()
    os.makedirs(os.path.join(d, "raw"), exist_ok=True)
    notes = []
    old_acc = {} if replace else (_read_json(os.path.join(d, "account.json"), {}) or {})
    if old_acc.get("handle") and account.get("handle") and old_acc["handle"] != account["handle"]:
        notes.append(f"previous scan was @{old_acc['handle']}; started over for @{account['handle']}")
        old_acc, replace = {}, True
    old_posts = [] if replace else (_read_json(os.path.join(d, "posts.json"), {}) or {}).get("posts", [])
    acc = dict(old_acc)
    for k, v in account.items():
        if v not in (None, "", "unknown") or k not in acc:
            acc[k] = v
    sources = list(dict.fromkeys((old_acc.get("sources") or []) + [source]))
    acc["sources"] = sources
    acc["source"] = source
    acc["scanned_at"] = _now()
    posts = merge_posts(old_posts, posts)
    unmatched = 0
    for ins in insights:
        hit = next((p for p in posts if same_post(p, ins)), None)
        if hit is None:
            unmatched += 1
            continue
        for k in METRICS:
            if ins.get(k) is not None:
                hit[k] = ins[k]
    if unmatched:
        notes.append(f"{unmatched} insight row(s) had no matching post url and were not used")
    _write_json(os.path.join(d, "account.json"), acc)
    _write_json(os.path.join(d, "posts.json"), {"scanned_at": acc["scanned_at"], "sources": sources,
                                                 "posts": posts})
    stamp = dt.datetime.now().strftime("%Y%m%d-%H%M%S")
    _write_json(os.path.join(d, "raw", f"{source}-{stamp}.json"), raw)
    return acc, posts, notes


def print_ingest_summary(acc, posts, new_n, source, out=None, notes=()):
    out = out or sys.stdout
    p = lambda *a: print(*a, file=out)  # noqa: E731
    p("")
    p(f"SCAN  ·  @{acc.get('handle') or '?'}  ·  source: {source}")
    p("=" * 64)
    p(f"  read now      {new_n} posts")
    p(f"  on file       {len(posts)} posts across sources: {', '.join(acc.get('sources') or [source])}")
    p(f"  followers     {acc.get('followers') if acc.get('followers') is not None else 'unknown'}")
    dates = sorted(x["date"] for x in posts if x.get("date"))
    if dates:
        p(f"  date range    {dates[0]} to {dates[-1]}")
    for m in ("views", "likes", "comments"):
        have = sum(1 for x in posts if x.get(m) is not None)
        p(f"  {m:<13} {have} of {len(posts)} posts")
    for n in notes:
        p(f"  note: {n}")
    p("-" * 64)
    p("  Next: python3 scan.py analyze")
    p("")


# ---------------------------------------------------------------- source 1: API

class APIError(Exception):
    pass


def _redact(text, token):
    text = str(text)
    if token:
        text = text.replace(token, "[token]")
        text = text.replace(urllib.parse.quote(token, safe=""), "[token]")
    return re.sub(r"access_token=[^&\s\"']+", "access_token=[token]", text)


class APIClient:
    """Read-only client for the Instagram API with Instagram Login.

    The token comes from the environment and only ever goes into the query
    string of a request to graph.instagram.com. Errors are redacted.
    """

    def __init__(self, token, version=None, base=API_BASE, pause=0.2, log=None):
        if not token:
            raise APIError("IG_ACCESS_TOKEN is not set")
        self._token = token
        self.version = version or os.environ.get("IG_API_VERSION") or API_VERSION
        self.base = base
        self.pause = pause
        self.calls = 0
        self.log = log or (lambda msg: print(msg, file=sys.stderr))

    def __repr__(self):
        return f"APIClient(version={self.version!r}, token=[hidden])"

    def _url(self, path, params):
        q = dict(params or {})
        q["access_token"] = self._token
        return f"{self.base}/{self.version}/{path.lstrip('/')}?{urllib.parse.urlencode(q)}"

    def _open(self, url):
        if not url.startswith(self.base + "/"):
            raise APIError("refusing to follow a paging link off graph.instagram.com")
        self.calls += 1
        req = urllib.request.Request(url, headers={"User-Agent": "ig-scan/1"})
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                body = r.read()
        except urllib.error.HTTPError as e:
            try:
                detail = json.loads(e.read() or b"{}").get("error", {})
                msg = f"HTTP {e.code}: {detail.get('message') or e.reason} (code {detail.get('code')})"
            except Exception:
                msg = f"HTTP {e.code}: {e.reason}"
            raise APIError(_redact(msg, self._token)) from None
        except (urllib.error.URLError, OSError) as e:
            raise APIError(_redact(f"network error: {getattr(e, 'reason', e)}", self._token)) from None
        try:
            return json.loads(body)
        except ValueError:
            raise APIError("the API answered with something that is not JSON") from None

    def get(self, path, **params):
        return self._open(self._url(path, params))

    def profile(self):
        try:
            return self.get("me", fields=PROFILE_FIELDS)
        except APIError as e:
            self.log(f"note: full profile fields refused ({e}). Retrying with the basic set.")
            return self.get("me", fields=PROFILE_FIELDS_MIN)

    def media(self, max_posts=MAX_POSTS):
        fields = MEDIA_FIELDS
        try:
            page = self.get("me/media", fields=fields, limit=min(PAGE_SIZE, max_posts))
        except APIError as e:
            self.log(f"note: media fields refused ({e}). Retrying without media_product_type.")
            fields = MEDIA_FIELDS_MIN
            page = self.get("me/media", fields=fields, limit=min(PAGE_SIZE, max_posts))
        items = []
        while True:
            items.extend(page.get("data") or [])
            nxt = (page.get("paging") or {}).get("next")
            if len(items) >= max_posts or not nxt:
                break
            time.sleep(self.pause)
            page = self._open(nxt)
        return items[:max_posts]

    def insights(self, media_id, is_reel, bad=None):
        """Dict of metric -> value. Metrics the API refuses are skipped and
        remembered in `bad` so the next post does not ask again."""
        bad = bad if bad is not None else set()
        wanted = [m for m in INSIGHTS_ALL + (INSIGHTS_REELS if is_reel else ()) if m not in bad]
        if not wanted:
            return {}, []
        errors = []
        try:
            return self._parse_insights(self.get(f"{media_id}/insights", metric=",".join(wanted))), errors
        except APIError as e:
            errors.append(str(e))
        out = {}
        for m in wanted:                          # one at a time, to find the refused one
            try:
                out.update(self._parse_insights(self.get(f"{media_id}/insights", metric=m)))
            except APIError as e:
                bad.add(m)
                errors.append(f"{m}: {e}")
        return out, errors

    @staticmethod
    def _parse_insights(resp):
        out = {}
        for d in resp.get("data") or []:
            name = d.get("name")
            val = None
            if isinstance(d.get("total_value"), dict):
                val = d["total_value"].get("value")
            elif d.get("values"):
                val = (d["values"][0] or {}).get("value")
            if name and isinstance(val, (int, float)):
                out[name] = val
        return out


def api_type(m):
    pt = (m.get("media_product_type") or "").upper()
    mt = (m.get("media_type") or "").upper()
    if pt == "STORY":
        return "story"
    if pt == "REELS":
        return "reel"
    if mt == "CAROUSEL_ALBUM":
        return "carousel"
    if mt == "VIDEO":
        return "reel"          # feed videos have been reels since 2022
    return "photo"


def from_api(client, max_posts=MAX_POSTS, insights=False):
    prof = client.profile()
    media = client.media(max_posts)
    posts, bad, notes, insight_errors = [], set(), [], 0
    for m in media:
        t = api_type(m)
        p = {"id": m.get("id"), "date": m.get("timestamp"), "type": t,
             "caption": m.get("caption") or "", "url": m.get("permalink") or "",
             "likes": m.get("like_count"), "comments": m.get("comments_count")}
        if insights and m.get("id"):
            time.sleep(client.pause)
            vals, errs = client.insights(m["id"], t == "reel", bad)
            insight_errors += len(errs)
            p["reach"] = vals.get("reach")
            p["views"] = vals.get("views")
            p["saves"] = vals.get("saved")
            p["shares"] = vals.get("shares")
            if vals.get("ig_reels_avg_watch_time") is not None:
                p["avg_watch_s"] = round(vals["ig_reels_avg_watch_time"] / 1000, 2)   # ms
            sr = vals.get("reels_skip_rate")
            if sr is not None:
                p["skip_rate"] = round(sr * 100, 1) if sr <= 1 else sr
        posts.append(norm_post(p, "api"))
    if bad:
        notes.append("the API refused these metrics, so they are blank: " + ", ".join(sorted(bad)))
    if insight_errors:
        notes.append(f"{insight_errors} insight request(s) failed and were skipped")
    if not insights:
        notes.append("no --insights: likes and comments only, no views or reach")
    account = norm_account({
        "username": prof.get("username"), "name": prof.get("name"),
        "biography": prof.get("biography"), "website": prof.get("website"),
        "followers_count": prof.get("followers_count"), "follows_count": prof.get("follows_count"),
        "media_count": prof.get("media_count"), "account_type": prof.get("account_type"),
    }, "api")
    raw = {"profile": {k: v for k, v in prof.items()}, "media": media}     # no paging links, no token
    return account, posts, raw, notes


# ---------------------------------------------------------------- source 3: DYI export

def fix_mojibake(s):
    """DYI JSON stores UTF-8 bytes as \\u00XX escapes ('Ã©' for 'é'). Undo it."""
    if not isinstance(s, str) or not s:
        return s
    if any(ord(c) > 0xFF for c in s) or not any(ord(c) >= 0x80 for c in s):
        return s
    try:
        return s.encode("latin-1").decode("utf-8")
    except (UnicodeEncodeError, UnicodeDecodeError):
        return s


def _fix_all(obj):
    if isinstance(obj, str):
        return fix_mojibake(obj)
    if isinstance(obj, list):
        return [_fix_all(x) for x in obj]
    if isinstance(obj, dict):
        return {fix_mojibake(k): _fix_all(v) for k, v in obj.items()}
    return obj


MAX_JSON_BYTES = 64 * 1024 * 1024
DYI_POSTS_RE = re.compile(r"(?:^|/)posts_\d+\.json$")
DYI_REELS_RE = re.compile(r"(?:^|/)reels\.json$")
DYI_STORIES_RE = re.compile(r"(?:^|/)stories\.json$")
DYI_FOLLOWERS_RE = re.compile(r"(?:^|/)followers_\d+\.json$")
DYI_FOLLOWING_RE = re.compile(r"(?:^|/)following\.json$")
DYI_PERSONAL_RE = re.compile(r"(?:^|/)personal_information\.json$")


def _dyi_files(path):
    """Yield (relative name, loader) for every json file in a zip or folder.
    Nothing is extracted to disk."""
    path = os.path.expanduser(path)
    if zipfile.is_zipfile(path):
        with zipfile.ZipFile(path) as z:
            for info in z.infolist():
                if info.filename.endswith(".json") and info.file_size <= MAX_JSON_BYTES:
                    yield info.filename.replace("\\", "/"), z.read(info)
    elif os.path.isdir(path):
        for root, _dirs, files in os.walk(path):
            for f in files:
                if f.endswith(".json"):
                    full = os.path.join(root, f)
                    if os.path.getsize(full) <= MAX_JSON_BYTES:
                        with open(full, "rb") as fh:
                            yield os.path.relpath(full, path).replace(os.sep, "/"), fh.read()
    else:
        raise FileNotFoundError(f"not a zip or a folder: {path}")


def _entries(obj):
    """Post-like entries in any of the shapes the export has used: a list,
    or a dict holding one list (ig_reels_media, ig_stories, ...)."""
    if isinstance(obj, list):
        return obj
    if isinstance(obj, dict):
        if "media" in obj or "creation_timestamp" in obj:
            return [obj]
        for v in obj.values():
            if isinstance(v, list):
                return v
    return []


def _dyi_post(entry, kind):
    if not isinstance(entry, dict):
        return None
    media = entry.get("media")
    media = media if isinstance(media, list) else ([entry] if entry.get("uri") else [])
    first = media[0] if media and isinstance(media[0], dict) else {}
    caption = entry.get("title") or first.get("title") or ""
    ts = entry.get("creation_timestamp") or first.get("creation_timestamp")
    if ts is None:
        return None
    uri = (first.get("uri") or "").lower()
    if kind == "reel":
        t = "reel"
    elif kind == "story":
        t = "story"
    elif len(media) > 1:
        t = "carousel"
    elif uri.endswith((".mp4", ".mov")):
        t = "reel"
    else:
        t = "photo"
    return norm_post({"date": ts, "type": t, "caption": caption}, "dyi")


def _string_map(obj, key):
    """Find string_map_data[key].value anywhere in personal_information.json."""
    if isinstance(obj, dict):
        smd = obj.get("string_map_data")
        if isinstance(smd, dict) and isinstance(smd.get(key), dict):
            return smd[key].get("value")
        for v in obj.values():
            r = _string_map(v, key)
            if r:
                return r
    elif isinstance(obj, list):
        for v in obj:
            r = _string_map(v, key)
            if r:
                return r
    return None


def from_dyi(path, stories=False):
    posts, raw, notes = [], {"files": []}, []
    followers = following = None
    personal = {}
    for name, blob in _dyi_files(path):
        kind = None
        if DYI_POSTS_RE.search(name):
            kind = "post"
        elif DYI_REELS_RE.search(name):
            kind = "reel"
        elif DYI_STORIES_RE.search(name):
            kind = "story" if stories else None
        elif DYI_FOLLOWERS_RE.search(name):
            kind = "followers"
        elif DYI_FOLLOWING_RE.search(name):
            kind = "following"
        elif DYI_PERSONAL_RE.search(name):
            kind = "personal"
        if not kind:
            continue
        try:
            obj = _fix_all(json.loads(blob.decode("utf-8-sig")))
        except (ValueError, UnicodeDecodeError):
            notes.append(f"could not read {name}")
            continue
        raw["files"].append(name)
        if kind in ("post", "reel", "story"):
            for e in _entries(obj):
                p = _dyi_post(e, kind)
                if p:
                    posts.append(p)
            raw.setdefault(kind, []).extend(_entries(obj))
        elif kind == "followers":
            followers = (followers or 0) + len(_entries(obj))
        elif kind == "following":
            following = (following or 0) + len(_entries(obj))
        elif kind == "personal":
            for k in ("Username", "Name", "Bio", "Website"):
                v = _string_map(obj, k)
                if v:
                    personal[k.lower()] = v
    if not raw["files"]:
        raise ValueError("no posts_*.json or reels.json found. Was the export made in JSON format?")
    if followers is None:
        notes.append("the export has no follower count. Ask the user and pass --followers N")
    else:
        notes.append("follower count is counted from the export's followers list; "
                     "check it against the profile")
    notes.append("exports have no likes, comments or views. Performance needs the API, kweo or screenshots")
    account = norm_account({"username": personal.get("username"), "name": personal.get("name"),
                            "bio": personal.get("bio"), "website": personal.get("website"),
                            "followers": followers, "following": following,
                            "posts_count": len([p for p in posts if p["type"] != "story"])}, "dyi")
    return account, posts, raw, notes


# ---------------------------------------------------------------- source 2/4: captured JSON

class Blocked(Exception):
    """A captured file says the reader hit a login wall or checkpoint."""


def _load_captured(path):
    with open(os.path.expanduser(path), encoding="utf-8") as f:
        cap = json.load(f)
    if not isinstance(cap, dict):
        raise ValueError(f"{path}: captured file must be a JSON object")
    for key in ("posts", "insights"):
        if cap.get(key) is not None and not isinstance(cap[key], list):
            raise ValueError(f"{path}: {key} must be a list")
    return cap


def from_captured(paths):
    """One or more captured files: a kweo-reader `profile` job, extra `posts`
    jobs, an `insights` job, or a file Claude wrote from screenshots.
    Posts are merged by url (else date + caption); insights fill numbers onto
    posts with the same url. A file with "blocked" set stops the ingest."""
    if isinstance(paths, str):
        paths = [paths]
    caps = [(p, _load_captured(p)) for p in paths]
    blocked = [(p, c.get("blocked")) for p, c in caps if c.get("blocked")]
    if blocked:
        raise Blocked("; ".join(f"{os.path.basename(p)}: blocked ({why})" for p, why in blocked))
    source = "manual"
    for _, c in caps:
        s = (c.get("source") or "").strip().lower()
        if s in ("kweo", "screenshot", "manual"):
            source = s
            break
    account = norm_account({}, source)
    for _, c in caps:                        # first file that has a value wins, field by field
        a = norm_account(c, source)
        for k, v in a.items():
            if account.get(k) in (None, "", "unknown") and v not in (None, ""):
                account[k] = v
    posts, notes, insights = [], [], []
    for path, c in caps:
        for p in c.get("posts") or []:
            if not isinstance(p, dict):
                continue
            np_ = norm_post(p, source)
            if p.get("pinned"):
                np_["pinned"] = True
            if not np_["date"]:
                notes.append(f"post without a usable date: {np_['url'] or np_['caption'][:40]}")
            posts = merge_posts(posts, [np_])
        insights += [i for i in (c.get("insights") or []) if isinstance(i, dict) and i.get("url")]
        if (c.get("notes") or "").strip():
            notes.append(f"{os.path.basename(path)}: {c['notes'].strip()[:200]}")
    stash = []
    for ins in insights:
        np_ = norm_post(ins, source)
        hit = next((p for p in posts if same_post(p, np_)), None)
        if hit is None:
            stash.append(np_)                    # may match a post already on file
            continue
        for k in METRICS:
            if np_.get(k) is not None:
                hit[k] = np_[k]
    if account["followers"] is None:
        notes.append("no follower count captured")
    raw = {"files": [os.path.basename(p) for p, _ in caps], "captured": [c for _, c in caps]}
    return account, posts, raw, notes, stash


# ---------------------------------------------------------------- text tools

def _mark_class():
    ranges, start, prev = [], None, None
    for cp in range(0x0300, 0x10000):
        if unicodedata.category(chr(cp))[0] == "M":
            start = cp if start is None else start
            prev = cp
        elif start is not None:
            ranges.append((start, prev))
            start = None
    return "".join(re.escape(chr(a)) + ("-" + re.escape(chr(b)) if b > a else "")
                   for a, b in ranges) + "‌‍"


MARKS = _mark_class()
WORD_RE = re.compile(r"(?:[^\W_]|['’" + MARKS + r"])+")
HASHTAG_RE = re.compile(r"(?:^|\s)#((?:\w|[" + MARKS + r"])+)")
MENTION_RE = re.compile(r"@[A-Za-z0-9_.]+")
URL_RE = re.compile(r"https?://\S+|\bwww\.\S+", re.IGNORECASE)
EMOJI_RE = re.compile(r"[\U0001F300-\U0001FAFF☀-➿\U0001F1E6-\U0001F1FF]")

STOP_EN = set("""
a about above after again against all also am an and any are aren't as at be because been before
being below between both but by can can't cannot could couldn't did didn't do does doesn't doing
don't down during each even ever every few for from further get gets got had hadn't has hasn't
have haven't having he he'd he'll he's her here here's hers herself him himself his how how's i
i'd i'll i'm i've if in into is isn't it it's its itself just let's like make made me more most
much must mustn't my myself new no nor not now of off on once one only or other ought our ours
ourselves out over own really same shan't she she'd she'll she's should shouldn't so some still
such than that that's the their theirs them themselves then there there's these they they'd
they'll they're they've thing things this those through to too under until up upon us very via
want was wasn't way we we'd we'll we're we've well were weren't what what's when when's where
where's which while who who's whom why why's will with won't would wouldn't you you'd you'll
you're you've your yours yourself yourselves day days time today go going know see link bio
comment comments follow save share dm post posts reel reels let us im dont cant ive youre
""".split())
# Romanized Hindi/Urdu function words, so Hinglish captions do not fill the keyword list.
STOP_ROMAN = set("""
hai hain ho tha thi the ka ki ke ko se me mein main mai aur ya bhi nahi nhi na kya kyun kaise
yeh ye woh wo jo toh to hi par pe ek apna apni apne hum tum aap mera meri mere tera teri tere
kar karo karna kiya raha rahi rahe ab bas bhai yaar sab kuch koi
""".split())
STOP_SCRIPT = set("""
है हैं का की के को से में और या भी नहीं क्या यह वह जो तो ही पर एक हम आप मेरा मेरी मेरे था थी थे कर
ہے ہیں کا کی کے کو سے میں اور یا بھی نہیں کیا یہ وہ جو تو ہی پر ایک ہم آپ میرا میری میرے تھا تھی تھے کر
""".split())
ROMAN_MARKERS = set("hai hain nahi nhi kya kyun kaise yaar bhai mein aur bhi apna kar karo raha".split())
URDU_LETTERS = set("ٹڈڑےںھہ")

ASKS_FALLBACK = [
    (re.compile(r"(?i)\bcomment (?:the word |\")?[A-Z0-9]{2,}\b"), "comment a keyword"),
    (re.compile(r"(?i)\b(?:dm|message) me\b"), "DM me"),
    (re.compile(r"(?i)\bsave (?:this|it)\b"), "save this"),
    (re.compile(r"(?i)\bshare (?:this|it)\b"), "share this"),
    (re.compile(r"(?i)\bfollow (?:me|for)\b"), "follow"),
    (re.compile(r"(?i)\blink in (?:my )?bio\b"), "link in bio"),
    (re.compile(r"(?i)\b(?:swipe|tap) (?:through|left|right|for|to)\b"), "swipe or tap"),
    (re.compile(r"(?i)\btell me\b|\bwhat would you\b|\bwhich one\b"), "answer a question"),
]


def asks_patterns():
    mod = _import_from("ig-caption", "caption")
    pats = getattr(mod, "ASKS", None) if mod else None
    return pats if pats else ASKS_FALLBACK


def first_line(caption):
    for line in (caption or "").splitlines():
        line = line.strip()
        if line:
            return line
    return ""


def body_text(caption):
    t = URL_RE.sub(" ", caption or "")
    t = re.sub(r"(?:^|\s)#\S+", " ", t)
    return MENTION_RE.sub(" ", t)


def tokens(caption):
    out = []
    for w in WORD_RE.findall(body_text(caption)):
        w = w.lower().strip("'’")
        if len(w) < 2 or w.isdigit() or any(c.isdigit() for c in w) and not any(c.isalpha() for c in w):
            continue
        is_latin = all(ord(c) < 0x250 for c in w)
        if is_latin and (len(w) < 3 or w in STOP_EN or w in STOP_ROMAN):
            continue
        if not is_latin and w in STOP_SCRIPT:
            continue
        out.append(w)
    return out


def hashtags(caption):
    return [h.lower() for h in HASHTAG_RE.findall(caption or "")]


def _script(ch):
    try:
        name = unicodedata.name(ch)
    except ValueError:
        return None
    first = name.split()[0]
    if first in ("CJK", "HIRAGANA", "KATAKANA"):
        return "CJK"
    return first


def script_share(texts):
    counts = collections.Counter()
    for t in texts:
        for ch in body_text(t):
            if ch.isalpha() or unicodedata.category(ch)[0] == "M":
                s = _script(ch)
                if s:
                    counts[s] += 1
    total = sum(counts.values())
    return {k: round(v / total, 3) for k, v in counts.most_common()} if total else {}


SCRIPT_LANG = {"DEVANAGARI": "hi", "BENGALI": "bn", "GURMUKHI": "pa", "GUJARATI": "gu",
               "TAMIL": "ta", "TELUGU": "te", "KANNADA": "kn", "MALAYALAM": "ml",
               "CYRILLIC": "ru", "GREEK": "el", "HEBREW": "he", "THAI": "th", "HANGUL": "ko",
               "CJK": "zh/ja"}


def detect_languages(captions):
    """[(code, share, label)] by script share, with English vs romanized
    Hindi/Urdu split inside Latin by marker words."""
    shares = script_share(captions)
    if not shares:
        return [], shares
    langs = collections.Counter()
    text = " ".join(body_text(c) for c in captions)
    for script, share in shares.items():
        if script == "LATIN":
            words = [w.lower() for w in re.findall(r"[A-Za-z']+", text)]
            roman = sum(1 for w in words if w in ROMAN_MARKERS)
            en = sum(1 for w in words if w in STOP_EN)
            if words and roman / len(words) > 0.04 and roman >= 3:
                r = min(0.9, roman / max(1, roman + en) * 1.5)
                langs["hi-Latn"] += share * r
                langs["en"] += share * (1 - r)
            elif en >= 1 or not words:
                langs["en"] += share
            else:
                langs["latin-other"] += share
        elif script == "ARABIC":
            urdu = any(c in URDU_LETTERS for c in text)
            langs["ur" if urdu else "ar"] += share
        else:
            langs[SCRIPT_LANG.get(script, script.lower())] += share
    labels = {"en": "English", "hi": "Hindi", "hi-Latn": "Hinglish (romanized Hindi/Urdu)",
              "ur": "Urdu", "ar": "Arabic or Persian", "bn": "Bengali", "pa": "Punjabi",
              "ta": "Tamil", "te": "Telugu", "ru": "Russian or another Cyrillic language",
              "ko": "Korean", "zh/ja": "Chinese or Japanese", "latin-other": "another Latin-script language"}
    out = [(k, round(v, 3), labels.get(k, k)) for k, v in langs.most_common() if v >= 0.03]
    return out, shares


# ---------------------------------------------------------------- niche lexicon

NICHES = {
    "fitness and training": "workout gym fitness training muscle fat loss protein reps squat cardio strength abs physique",
    "food and recipes": "recipe food cook cooking kitchen dinner lunch breakfast chicken bake baking meal snack chef tasty",
    "personal finance": "money invest investing stocks savings budget finance wealth salary tax mutual fund crypto income debt",
    "business and marketing": "business marketing brand clients sales startup founder entrepreneur leads agency growth revenue customers",
    "freelancing and careers": "freelance freelancer clients contract invoice career job interview resume linkedin hiring rates",
    "beauty and skincare": "skincare skin makeup beauty serum glow hair routine moisturizer sunscreen acne lipstick",
    "fashion and style": "outfit fashion style wear dress ootd styling wardrobe shoes jeans",
    "travel": "travel trip hotel beach flight explore visit wanderlust itinerary mountains city vacation",
    "parenting and family": "kids baby mom dad parenting toddler family children motherhood",
    "tech and AI": "tech app apps software code coding developer iphone android gadget tools automation prompt chatgpt",
    "education and study": "study exam students learn learning tips notes school college upsc neet",
    "real estate and home": "home house property interior decor apartment rent realestate design room",
    "photography and art": "photo photography camera art drawing painting artist design edit lightroom",
    "mental health and self-growth": "mindset habits motivation mental health anxiety therapy discipline productivity journaling",
    "comedy and entertainment": "funny comedy meme memes prank relatable sketch",
    "faith and spirituality": "god prayer faith islam quran allah bible jesus spiritual temple",
    "pets": "dog cat puppy pet pets kitten",
}


def niche_guess(top_kw, top_tags):
    words = collections.Counter()
    for w, n in top_kw:
        words[w] += n
    for t, n in top_tags:
        words[t] += n
    scores = []
    for niche, lex in NICHES.items():
        lexset = set(lex.split())
        s = sum(n for w, n in words.items() if w in lexset or any(w.startswith(x) and len(x) > 4 for x in lexset))
        if s:
            scores.append((s, niche))
    scores.sort(reverse=True)
    kws = [w for w, _ in top_kw[:4]]
    if scores and scores[0][0] >= 3:
        label = scores[0][1]
        conf = "medium" if len(scores) == 1 or scores[0][0] >= 2 * scores[1][0] else "low"
        return {"label": label, "keywords": kws, "confidence": conf,
                "runner_up": scores[1][1] if len(scores) > 1 else None}
    return {"label": ", ".join(kws[:3]) if kws else "unknown", "keywords": kws,
            "confidence": "low", "runner_up": None}


# ---------------------------------------------------------------- analysis

def size_tier(followers):
    if followers is None:
        return "unknown"
    for limit, name in TIERS:
        if followers < limit:
            return name
    return "mega"


def _median(vals):
    vals = [v for v in vals if v is not None]
    return statistics.median(vals) if vals else None


def _pct(n, d):
    return round(100 * n / d, 1) if d else 0.0


def _parse_day(s):
    try:
        return dt.date.fromisoformat(s[:10])
    except (TypeError, ValueError):
        return None


def cadence(posts, today):
    dated = sorted(d for d in (_parse_day(p.get("date")) for p in posts) if d)
    out = {"per_week_30d": 0.0, "per_week_90d": 0.0, "longest_gap_days": None,
           "days_since_last": None, "consistency": None, "weeks_considered": 0}
    if not dated:
        return out
    n30 = sum(1 for d in dated if 0 <= (today - d).days < 30)
    n90 = sum(1 for d in dated if 0 <= (today - d).days < 90)
    out["per_week_30d"] = round(n30 / (30 / 7), 2)
    out["per_week_90d"] = round(n90 / (90 / 7), 2)
    gaps = [(b - a).days for a, b in zip(dated, dated[1:])]
    out["longest_gap_days"] = max(gaps) if gaps else None
    out["days_since_last"] = (today - dated[-1]).days
    span_weeks = max(1, min(12, ((today - dated[0]).days // 7) + 1))
    weeks_with = {(today - d).days // 7 for d in dated if 0 <= (today - d).days < span_weeks * 7}
    out["weeks_considered"] = span_weeks
    out["consistency"] = round(100 * len(weeks_with) / span_weeks)
    return out


def format_mix(posts, today):
    feed = [p for p in posts if p["type"] != "story"]

    def mix(items):
        c = collections.Counter(p["type"] for p in items)
        return {t: _pct(c[t], len(items)) for t in ("reel", "carousel", "photo") if c[t]}, len(items)

    recent = [p for p in feed if (d := _parse_day(p.get("date"))) and 0 <= (today - d).days < 30]
    earlier = [p for p in feed if (d := _parse_day(p.get("date"))) and 30 <= (today - d).days < 120]
    basis = "last 30 days vs the 90 before"
    if not recent or not earlier:
        ordered = sorted(feed, key=lambda p: p.get("date") or "", reverse=True)
        k = max(1, len(ordered) // 3)
        recent, earlier = ordered[:k], ordered[k:]
        basis = f"newest {len(recent)} posts vs the {len(earlier)} before"
    all_mix, n = mix(feed)
    r_mix, rn = mix(recent)
    e_mix, en = mix(earlier)
    shift = {t: round(r_mix.get(t, 0) - e_mix.get(t, 0), 1) for t in ("reel", "carousel", "photo")
             if t in r_mix or t in e_mix} if rn and en else {}
    return {"all": all_mix, "n": n, "recent": r_mix, "recent_n": rn, "earlier": e_mix,
            "earlier_n": en, "shift_pts": shift, "basis": basis}


def performance(posts, followers):
    feed = [p for p in posts if p["type"] != "story"]
    n = len(feed)
    have = {m: sum(1 for p in feed if p.get(m) is not None) for m in METRICS}
    basis = None
    if n and have["views"] >= 0.6 * n:
        basis = "views"
    elif n and have["likes"] >= 0.6 * n:
        basis = "interactions"          # likes + comments

    def val(p):
        if basis == "views":
            return p.get("views")
        if basis == "interactions" and p.get("likes") is not None:
            return p["likes"] + (p.get("comments") or 0)
        return None

    base = _median([val(p) for p in feed])
    for p in feed:
        v = val(p)
        p["outlier"] = round(v / base, 2) if v is not None and base else None
        if followers and p.get("likes") is not None:
            p["er"] = round(100 * (p["likes"] + (p.get("comments") or 0)) / followers, 2)
        else:
            p["er"] = None
    er_by_format = {}
    for t in ("reel", "carousel", "photo"):
        vals = [p["er"] for p in feed if p["type"] == t and p.get("er") is not None]
        if vals:
            er_by_format[t] = {"median": round(statistics.median(vals), 2), "n": len(vals)}
    ranked = sorted((p for p in feed if p.get("outlier") is not None), key=lambda p: -p["outlier"])

    def brief(p):
        return {"date": p.get("date"), "type": p["type"], "outlier": p["outlier"],
                "views": p.get("views"), "likes": p.get("likes"), "comments": p.get("comments"),
                "first_line": first_line(p.get("caption"))[:110], "url": p.get("url")}

    k = min(5, len(ranked) // 2) if len(ranked) >= 4 else min(5, len(ranked))
    return {
        "basis": basis, "baseline": base,
        "median": {m: _median([p.get(m) for p in feed]) for m in ("views", "likes", "comments", "reach", "saves", "shares")},
        "have": have, "n": n,
        "er_median": round(statistics.median([p["er"] for p in feed if p.get("er") is not None]), 2)
        if any(p.get("er") is not None for p in feed) else None,
        "er_by_format": er_by_format,
        "top": [brief(p) for p in ranked[:k]],
        "bottom": [brief(p) for p in ranked[-k:][::-1]] if len(ranked) >= 4 else [],
    }


def clusters(posts, top_kw, max_clusters=5):
    """Group the top keywords by how often they share a caption."""
    kws = [w for w, _ in top_kw[:20]]
    if not kws:
        return []
    sets = [set(tokens(p.get("caption"))) for p in posts]
    df = {w: sum(1 for s in sets if w in s) for w in kws}
    co = {(a, b): sum(1 for s in sets if a in s and b in s) for i, a in enumerate(kws) for b in kws[i + 1:]}
    assigned, out = set(), []
    for w in kws:
        if w in assigned or len(out) >= max_clusters:
            continue
        group = [w]
        assigned.add(w)
        for o in kws:
            if o in assigned or len(group) >= 5:
                continue
            c = co.get((w, o)) or co.get((o, w)) or 0
            if c and c / min(df[w], df[o]) >= 0.4:
                group.append(o)
                assigned.add(o)
        posts_n = sum(1 for s in sets if s & set(group))
        out.append({"name": " / ".join(group[:3]), "keywords": group, "posts": posts_n})
    return out


def assign_theme(post, cl):
    toks = set(tokens(post.get("caption")))
    best, hits = None, 0
    for c in cl:
        h = len(toks & set(c["keywords"]))
        if h > hits:
            best, hits = c["name"], h
    return best


def length_bucket(caption):
    n = len(WORD_RE.findall(body_text(caption)))
    if n < 20:
        return "short (<20 words)"
    if n <= 80:
        return "medium (20-80 words)"
    return "long (80+ words)"


_FORMULAS = None


def formulas():
    global _FORMULAS
    if _FORMULAS is None:
        swipe = _import_from("ig-viral", "swipe")
        f = None
        if swipe:
            hooks = _find_skill("ig-reel", "hooks.json") or getattr(swipe, "HOOKS", None)
            f = swipe.load_formulas(hooks) if hooks else None
        _FORMULAS = (swipe, f)
    return _FORMULAS


def classify_hook(line):
    swipe, f = formulas()
    if not swipe or not f or not line:
        return None, "unclassified"
    return swipe.classify(line, f)


def rank_groups(feed, keyfn):
    groups = collections.defaultdict(list)
    for p in feed:
        k = keyfn(p)
        if k and p.get("outlier") is not None:
            groups[k].append(p["outlier"])
    rows = [{"group": k, "mean_outlier": round(statistics.mean(v), 2), "n": len(v), "thin": len(v) < THIN}
            for k, v in groups.items()]
    rows.sort(key=lambda r: (r["thin"], -r["mean_outlier"]))
    return rows


def worst_habit(a):
    """The one habit most worth changing, in priority order."""
    c, cont, perf = a["cadence"], a["content"], a["performance"]
    over = cont["hashtags"]["over_cap_posts"]
    if over >= 3 and over >= 0.2 * max(1, a["n_feed"]):
        return (f"{cont['hashtags']['over_cap_posts']} posts use more than {cont['hashtags']['cap']} hashtags. "
                f"Only {cont['hashtags']['cap']} count now")
    if c["days_since_last"] is not None and c["days_since_last"] > 14:
        return f"no post for {c['days_since_last']} days"
    if c["consistency"] is not None and c["consistency"] < 50 and c["weeks_considered"] >= 4:
        return f"posts in only {c['consistency']}% of recent weeks. Gaps reset momentum"
    asks = cont["cta"]
    if a["n_feed"] >= 5 and asks["none_pct"] >= 70:
        return f"{asks['none_pct']:.0f}% of captions ask for nothing"
    if a["n_feed"] >= 5 and asks["multi_pct"] >= 30:
        return f"{asks['multi_pct']:.0f}% of captions make two or more asks"
    wp = a["what_performs"]["format"]
    mix = a["format_mix"]["all"]
    solid = [r for r in wp if not r["thin"]]
    if len(solid) >= 2:
        worst = min(solid, key=lambda r: r["mean_outlier"])
        best = max(solid, key=lambda r: r["mean_outlier"])
        if mix.get(worst["group"], 0) >= 40 and best["mean_outlier"] >= 1.5 * worst["mean_outlier"]:
            return (f"{mix[worst['group']]:.0f}% of posts are {worst['group']}s, the weakest format here "
                    f"({worst['mean_outlier']}x vs {best['group']} {best['mean_outlier']}x)")
    fl = cont["first_line_chars_median"]
    if fl and fl > 125:
        return f"the median first line is {fl:.0f} characters, so the hook is cut at \"... more\""
    if perf["basis"] is None:
        return "no numbers yet, so nothing can be ranked. Add likes or views"
    return None


def analyze(account, posts, today=None):
    today = today or dt.date.today()
    followers = account.get("followers")
    feed = [dict(p) for p in posts if p.get("type") != "story"]
    stories = [p for p in posts if p.get("type") == "story"]
    dated = sorted(d for d in (_parse_day(p.get("date")) for p in feed) if d)
    following = account.get("following")

    perf = performance(feed, followers)
    caps = [p.get("caption") or "" for p in feed]
    df_kw = collections.Counter()
    for c in caps:
        df_kw.update(set(tokens(c)))
    ranked_kw = sorted(df_kw.items(), key=lambda kv: (-kv[1], kv[0]))      # stable across runs
    top_kw = [(w, n) for w, n in ranked_kw[:40] if n >= 2][:20] or ranked_kw[:10]
    tag_counts = collections.Counter(t for c in caps for t in hashtags(c))
    top_tags = sorted(tag_counts.items(), key=lambda kv: (-kv[1], kv[0]))[:15]
    cl = clusters(feed, top_kw)
    for p in feed:
        p["theme"] = assign_theme(p, cl)
        p["first_line"] = first_line(p.get("caption"))
        p["formula_id"], p["formula"] = classify_hook(p["first_line"])
        p["length_bucket"] = length_bucket(p.get("caption"))

    cap = hashtag_cap()
    per_post_tags = [len(hashtags(c)) for c in caps]
    pats = asks_patterns()
    cta_counts, none_n, multi_n = collections.Counter(), 0, 0
    for c in caps:
        found = [name for pat, name in pats if pat.search(c or "")]
        cta_counts.update(found)
        none_n += not found
        multi_n += len(found) >= 2
    langs, scripts = detect_languages(caps)
    words = [len(WORD_RE.findall(body_text(c))) for c in caps]
    fl_chars = [len(first_line(c)) for c in caps if c]
    emoji_counts = [len(EMOJI_RE.findall(c)) for c in caps]
    formula_counts = collections.Counter(p["formula"] for p in feed if p["first_line"])

    a = {
        "handle": account.get("handle"),
        "name": account.get("name"),
        "bio": account.get("bio"),
        "website": account.get("website"),
        "account_type": account.get("account_type"),
        "category": account.get("category"),
        "scanned_at": account.get("scanned_at") or _now(),
        "analyzed_at": _now(),
        "today": today.isoformat(),
        "source": account.get("source"),
        "sources": account.get("sources") or [account.get("source")],
        "n_posts": len(posts), "n_feed": len(feed), "n_stories": len(stories),
        "size": {
            "followers": followers,
            "tier": size_tier(followers),
            "following": following,
            "following_ratio": round(following / followers, 2) if followers and following is not None else None,
            "posts_count": account.get("posts_count") or len(feed),
            "first_post": dated[0].isoformat() if dated else None,
            "age_months_min": round((today - dated[0]).days / 30.4, 1) if dated else None,
            "sample_is_full_history": "dyi" in (account.get("sources") or []),
        },
        "cadence": cadence(feed, today),
        "format_mix": format_mix(feed, today),
        "performance": perf,
        "content": {
            "top_keywords": top_kw,
            "top_hashtags": top_tags,
            "themes": cl,
            "caption_words": {"median": _median(words), "min": min(words) if words else None,
                              "max": max(words) if words else None},
            "first_line_chars_median": _median(fl_chars),
            "languages": [{"code": c, "share": s, "label": l} for c, s, l in langs],
            "scripts": scripts,
            "cta": {"counts": dict(cta_counts.most_common()), "none_pct": _pct(none_n, len(caps)),
                    "multi_pct": _pct(multi_n, len(caps))},
            "hashtags": {"cap": cap, "mean": round(statistics.mean(per_post_tags), 1) if per_post_tags else 0,
                         "median": _median(per_post_tags), "max": max(per_post_tags) if per_post_tags else 0,
                         "over_cap_posts": sum(1 for x in per_post_tags if x > cap),
                         "none_posts": sum(1 for x in per_post_tags if x == 0)},
            "formulas": dict(formula_counts.most_common()),
            "formulas_available": formulas()[1] is not None,
            "emoji": {"posts_with_pct": _pct(sum(1 for x in emoji_counts if x), len(caps)),
                      "mean_per_post": round(statistics.mean(emoji_counts), 1) if emoji_counts else 0},
        },
        "what_performs": {
            "format": rank_groups(feed, lambda p: p["type"]),
            "formula": rank_groups(feed, lambda p: p["formula"] if p["first_line"] else None),
            "theme": rank_groups(feed, lambda p: p["theme"]),
            "length": rank_groups(feed, lambda p: p["length_bucket"]),
        },
        "niche_guess": niche_guess(top_kw, [(t, n) for t, n in top_tags]),
        "posts": [{k: p.get(k) for k in ("date", "type", "url", "outlier", "er", "theme", "formula_id",
                                          "formula", "first_line", "length_bucket")} for p in feed],
    }
    a["worst_habit"] = worst_habit(a)
    a["honesty"] = honesty(a)
    return a


def honesty(a):
    notes = []
    n = a["n_feed"]
    if n < 12:
        notes.append(f"only {n} posts. Treat every pattern here as a hint, not a finding")
    elif n < 30:
        notes.append(f"{n} posts. Enough to see habits, thin for ranking formulas and themes")
    have = a["performance"]["have"]
    missing = [m for m in ("views", "likes", "comments", "reach", "saves", "shares") if not have.get(m)]
    if missing:
        notes.append("missing metrics: " + ", ".join(missing))
    if a["size"]["followers"] is None:
        notes.append("no follower count, so no size tier or engagement rate. Ask the user")
    if a["performance"]["basis"] == "interactions":
        notes.append("outliers are on likes + comments, not views. Views tell more; add them if you can")
    if not a["content"]["formulas_available"]:
        notes.append("ig-viral/swipe.py or ig-reel/hooks.json not found, so hook formulas are not named")
    if not a["size"]["sample_is_full_history"]:
        notes.append("account age is from the oldest post read, so it is a minimum")
    return notes


# ---------------------------------------------------------------- rendering

CLAUDE_READ_HEAD = "## Claude's read"
CLAUDE_READ_PLACEHOLDER = """(Claude fills this in after reading the numbers and the captions. Keep it to:
- Niche, in one line:
- Audience (who, where, what language):
- What the account is for (sell, lead gen, personal brand, community):
- What is working:
- Three opportunities that fit this account:
)"""


def _fmt(n):
    if n is None:
        return "-"
    if isinstance(n, float) and not n.is_integer():
        return f"{n:,.1f}"
    return f"{int(n):,}"


def _group_lines(rows, label):
    if not rows:
        return [f"- {label}: nothing to rank yet"]
    parts = [f"{r['group']} {r['mean_outlier']}x (n={r['n']}{', thin' if r['thin'] else ''})" for r in rows[:5]]
    return [f"- {label}: " + "; ".join(parts)]


def to_markdown(a, claude_read=None):
    s, c, fm, perf, cont = a["size"], a["cadence"], a["format_mix"], a["performance"], a["content"]
    L = [f"# @{a['handle'] or '?'} - account profile", "",
         f"Scanned {a['scanned_at'][:10]} from {', '.join(x for x in a['sources'] if x)}. "
         f"{a['n_feed']} feed posts read"
         + (f", {a['n_stories']} stories" if a["n_stories"] else "") + ".", ""]
    if a.get("bio"):
        L += [f"> {a['bio'].replace(chr(10), ' / ')}", ""]
    ng = a["niche_guess"]
    L += ["## NICHE GUESS", "",
          f"{ng['label']} (confidence {ng['confidence']}). Top words: {', '.join(ng['keywords']) or '-'}."
          + (f" Runner-up: {ng['runner_up']}." if ng.get("runner_up") else ""),
          "Claude confirms this with the user and writes the real answer in Claude's read.", ""]
    L += [CLAUDE_READ_HEAD, "", (claude_read or CLAUDE_READ_PLACEHOLDER).strip(), ""]
    L += ["## Size", "",
          f"- followers: {_fmt(s['followers'])} ({s['tier']})",
          f"- following: {_fmt(s['following'])}"
          + (f" (ratio {s['following_ratio']})" if s["following_ratio"] is not None else ""),
          f"- posts: {_fmt(s['posts_count'])}",
          f"- first post read: {s['first_post'] or '-'}"
          + (f" (about {s['age_months_min']} months{'' if s['sample_is_full_history'] else ', at least'})"
             if s["age_months_min"] is not None else ""), ""]
    shift = ", ".join(f"{t} {'+' if v >= 0 else ''}{v} pts" for t, v in fm["shift_pts"].items())
    L += ["## Cadence", "",
          f"- posts per week: {c['per_week_30d']} (last 30 days), {c['per_week_90d']} (last 90)",
          f"- longest gap: {c['longest_gap_days'] if c['longest_gap_days'] is not None else '-'} days; "
          f"last post {c['days_since_last'] if c['days_since_last'] is not None else '-'} day(s) ago",
          f"- consistency: {c['consistency'] if c['consistency'] is not None else '-'}% of the last "
          f"{c['weeks_considered']} weeks had a post",
          "- format mix: " + (", ".join(f"{t} {v}%" for t, v in fm["all"].items()) or "-"),
          f"- recent shift ({fm['basis']}): {shift or 'not enough posts to compare'}", ""]
    basis = {"views": "views", "interactions": "likes + comments", None: "nothing (no numbers)"}[perf["basis"]]
    L += ["## Performance", "",
          f"- outliers measured on: {basis}; account median {_fmt(perf['baseline'])}",
          f"- median views {_fmt(perf['median']['views'])}, likes {_fmt(perf['median']['likes'])}, "
          f"comments {_fmt(perf['median']['comments'])}",
          "- engagement rate (likes+comments / followers): "
          + (f"{perf['er_median']}% median" if perf["er_median"] is not None else "-")
          + ("; " + ", ".join(f"{t} {v['median']}% (n={v['n']})" for t, v in perf["er_by_format"].items())
             if perf["er_by_format"] else ""), ""]
    if perf["top"]:
        L += ["Top posts:", ""]
        L += [f"- {p['outlier']}x  {p['date']}  {p['type']}  \"{p['first_line']}\"" for p in perf["top"]]
        L += [""]
    if perf["bottom"]:
        L += ["Bottom posts:", ""]
        L += [f"- {p['outlier']}x  {p['date']}  {p['type']}  \"{p['first_line']}\"" for p in perf["bottom"]]
        L += [""]
    L += ["## What performs", "", "Mean outlier multiple per group. Thin means fewer than 3 posts.", ""]
    L += _group_lines(a["what_performs"]["format"], "format")
    L += _group_lines(a["what_performs"]["formula"], "hook formula")
    L += _group_lines(a["what_performs"]["theme"], "theme")
    L += _group_lines(a["what_performs"]["length"], "caption length")
    L += [""]
    langs = ", ".join(f"{l['label']} {round(100 * l['share'])}%" for l in cont["languages"]) or "-"
    h = cont["hashtags"]
    L += ["## Content and voice", "",
          "- top keywords: " + (", ".join(f"{w} ({n})" for w, n in cont["top_keywords"][:12]) or "-"),
          "- top hashtags: " + (", ".join(f"#{t} ({n})" for t, n in cont["top_hashtags"][:10]) or "-"),
          "- themes: " + ("; ".join(f"{t['name']} ({t['posts']} posts)" for t in cont["themes"]) or "-"),
          f"- language: {langs}",
          f"- caption length: median {_fmt(cont['caption_words']['median'])} words "
          f"(range {_fmt(cont['caption_words']['min'])}-{_fmt(cont['caption_words']['max'])}); "
          f"first line median {_fmt(cont['first_line_chars_median'])} characters",
          f"- hashtags per post: mean {h['mean']}, max {h['max']}, cap {h['cap']}; "
          f"{h['over_cap_posts']} posts over the cap, {h['none_posts']} with none",
          "- asks: " + (", ".join(f"{k} {v}" for k, v in cont["cta"]["counts"].items()) or "none")
          + f"; {cont['cta']['none_pct']}% ask for nothing, {cont['cta']['multi_pct']}% ask for two or more",
          "- hook formulas used: " + (", ".join(f"{k} {v}" for k, v in list(cont["formulas"].items())[:6]) or "-"),
          f"- emoji: in {cont['emoji']['posts_with_pct']}% of captions, {cont['emoji']['mean_per_post']} per post", ""]
    L += ["## Worst habit", "", a["worst_habit"] or "Nothing stands out. Good.", ""]
    L += ["## How sure is this", ""] + [f"- {n}" for n in a["honesty"]] + \
         [f"- source: {', '.join(x for x in a['sources'] if x)}; scanned {a['scanned_at'][:10]}", ""]
    return "\n".join(L)


def extract_claude_read(md):
    if not md or CLAUDE_READ_HEAD not in md:
        return None
    body = md.split(CLAUDE_READ_HEAD, 1)[1]
    body = re.split(r"\n## ", body, maxsplit=1)[0].strip()
    if not body or body.startswith("(Claude fills this in"):
        return None
    return body


def render_summary(a, out=None):
    out = out or sys.stdout
    p = lambda *x: print(*x, file=out)  # noqa: E731
    s, c, perf = a["size"], a["cadence"], a["performance"]
    p("")
    p(f"ACCOUNT  ·  @{a['handle'] or '?'}  ·  {s['tier']}  ·  {a['n_feed']} posts  ·  scanned {a['scanned_at'][:10]}")
    p("=" * 72)
    p(f"  niche guess   {a['niche_guess']['label']} ({a['niche_guess']['confidence']})")
    p(f"  followers     {_fmt(s['followers'])}   following {_fmt(s['following'])}")
    p(f"  cadence       {c['per_week_30d']}/week (30d), {c['per_week_90d']}/week (90d), "
      f"consistency {c['consistency'] if c['consistency'] is not None else '-'}%")
    p("  mix           " + (", ".join(f"{t} {v}%" for t, v in a["format_mix"]["all"].items()) or "-"))
    p(f"  engagement    {perf['er_median'] if perf['er_median'] is not None else '-'}% median")
    for key, label in (("format", "best format"), ("formula", "best formula"), ("theme", "best theme")):
        rows = a["what_performs"][key]
        if rows:
            r = rows[0]
            p(f"  {label:<13} {r['group']} {r['mean_outlier']}x (n={r['n']}{', thin' if r['thin'] else ''})")
    langs = ", ".join(f"{l['label']} {round(100 * l['share'])}%" for l in a["content"]["languages"])
    p(f"  language      {langs or '-'}")
    p(f"  worst habit   {a['worst_habit'] or '-'}")
    p("-" * 72)
    for n in a["honesty"]:
        p(f"  note: {n}")
    p("")


def load_scan():
    d = scan_dir()
    acc = _read_json(os.path.join(d, "account.json"))
    posts = (_read_json(os.path.join(d, "posts.json"), {}) or {}).get("posts")
    if acc is None or posts is None:
        return None, None
    return acc, posts


def load_profile_json():
    p = _read_json(os.path.join(data_dir(), "profile.json"), {})
    return p if isinstance(p, dict) else {}


# ---------------------------------------------------------------- context

def context_block(a, profile=None, claude_read=None):
    profile = profile or {}
    s, c = a["size"], a["cadence"]
    niche = profile.get("niche")
    niche_line = f"{niche} (confirmed)" if niche else f"{a['niche_guess']['label']} (guess, not confirmed)"
    if claude_read:
        m = re.search(r"(?im)^\s*-?\s*niche[^:]*:\s*(.+)$", claude_read)
        if m and m.group(1).strip():
            niche_line = m.group(1).strip() + (" (confirmed)" if niche else " (Claude's read)")

    def best(key):
        rows = a["what_performs"][key]
        if not rows:
            return "-"
        r = rows[0]
        return f"{r['group']} {r['mean_outlier']}x n={r['n']}" + (" thin" if r["thin"] else "")

    langs = ", ".join(f"{l['label']} {round(100 * l['share'])}%" for l in a["content"]["languages"][:3])
    lines = [
        f"ACCOUNT CONTEXT (@{a['handle'] or '?'}, scanned {a['scanned_at'][:10]}, {a['n_feed']} posts, "
        f"source {', '.join(x for x in a['sources'] if x)})",
        f"size: {_fmt(s['followers'])} followers, {s['tier']}"
        + (f", following ratio {s['following_ratio']}" if s["following_ratio"] is not None else "")
        + (f", type {a['account_type']}" if a.get("account_type") not in (None, "", "unknown") else ""),
        f"niche: {niche_line}",
        f"region: {profile.get('region') or '-'}   goal: {profile.get('goal') or '-'}",
        f"audience language: {langs or '-'}",
        f"cadence: {c['per_week_30d']}/week last 30d, {c['per_week_90d']}/week last 90d, "
        f"consistency {c['consistency'] if c['consistency'] is not None else '-'}%, "
        f"longest gap {c['longest_gap_days'] if c['longest_gap_days'] is not None else '-'}d",
        "format mix: " + (", ".join(f"{t} {v}%" for t, v in a["format_mix"]["all"].items()) or "-"),
        f"best format: {best('format')}",
        f"best hook formula: {best('formula')}",
        f"best theme: {best('theme')}",
        "themes: " + (", ".join(t["name"] for t in a["content"]["themes"][:4]) or "-"),
        f"engagement: {a['performance']['er_median'] if a['performance']['er_median'] is not None else '-'}% median "
        f"(outliers on {a['performance']['basis'] or 'nothing'})",
        f"worst habit: {a['worst_habit'] or 'none stands out'}",
        f"caveat: {a['honesty'][0] if a['honesty'] else 'none'}",
    ]
    return lines


# ---------------------------------------------------------------- to-ledger

def to_ledger(posts, a=None, dry_run=False):
    ledger = _import_from("ig-ledger", "ledger")
    if ledger is None:
        raise RuntimeError("ig-ledger/ledger.py not found")
    by_key = {}
    if a:
        for p in a.get("posts", []):
            by_key[(p.get("url") or "", p.get("date"), (p.get("first_line") or "")[:40])] = p
    rows = ledger.load_rows()
    summary = {"created": 0, "updated": 0, "unchanged": 0, "skipped": 0, "ids": []}
    metric_map = {"views": "views", "reach": "reach", "likes": "likes", "comments": "comments",
                  "shares": "shares", "saves": "saves", "avg_watch_s": "avg_watch_s", "skip_rate": "skip_rate"}
    for p in sorted(posts, key=lambda x: x.get("date") or ""):
        if not p.get("date") and not p.get("url"):
            summary["skipped"] += 1
            continue
        fl = " ".join(first_line(p.get("caption")).split())[:150]
        info = by_key.get((p.get("url") or "", p.get("date"), fl[:40]), {})
        fid = info.get("formula_id")
        if fid is None and fl:
            fid, _ = classify_hook(fl)
        fields = {"date": p.get("date") or "", "format": p.get("type") or "", "first_line": fl,
                  "permalink": p.get("url") or "", "hook_formula": str(fid) if fid else "",
                  "theme": info.get("theme") or ""}
        metrics = {}
        for src, dst in metric_map.items():
            v = p.get(src)
            if v is not None:
                try:
                    metrics[dst] = ledger.normalize(dst, v)
                except ValueError:
                    pass
        target = None
        if p.get("url"):
            key = p["url"].rstrip("/").lower()
            target = next((r for r in rows if r["permalink"] and r["permalink"].rstrip("/").lower() == key), None)
        if target is None and p.get("date") and fl:
            target = next((r for r in rows if r["date"] == p["date"] and r["first_line"]
                           and ledger.prefix_match(r["first_line"], fl)), None)
        if target is not None:
            changed = False
            for k, v in metrics.items():                 # newer numbers win, blanks never overwrite
                if v != "" and target.get(k) != v:
                    target[k] = v
                    changed = True
            for k, v in fields.items():                  # text only fills empty cells
                if v and not target.get(k):
                    target[k] = ledger.normalize(k, v)
                    changed = True
            summary["updated" if changed else "unchanged"] += 1
            summary["ids"].append(("updated" if changed else "unchanged", target["id"]))
        else:
            row = {c: "" for c in ledger.COLUMNS}
            for k, v in fields.items():
                row[k] = ledger.normalize(k, v) if v else ""
            row.update(metrics)
            row["id"] = ledger.next_id(rows)
            row["notes"] = f"scan:{p.get('source') or 'scan'}"
            rows.append(row)
            summary["created"] += 1
            summary["ids"].append(("created", row["id"]))
    if not dry_run:
        ledger.save_rows(rows)
    return summary


# ---------------------------------------------------------------- prefill

FLAG_RE = re.compile(r"([\U0001F1E6-\U0001F1FF])([\U0001F1E6-\U0001F1FF])")
PLACE_REGION = {
    "IN": "india mumbai delhi bangalore bengaluru hyderabad chennai kolkata pune ahmedabad jaipur lucknow noida gurgaon gurugram",
    "PK": "pakistan karachi lahore islamabad rawalpindi peshawar faisalabad multan",
    "BD": "bangladesh dhaka chittagong",
    "AE": "dubai abudhabi uae sharjah",
    "GB": "london manchester birmingham uk england scotland glasgow edinburgh",
    "US": "usa nyc newyork losangeles chicago texas california miami seattle austin",
    "CA": "canada toronto vancouver montreal",
    "AU": "australia sydney melbourne brisbane perth",
    "SA": "riyadh jeddah saudi",
    "NG": "nigeria lagos abuja",
}
TLD_REGION = {".in": "IN", ".pk": "PK", ".co.uk": "GB", ".uk": "GB", ".ca": "CA", ".com.au": "AU",
              ".au": "AU", ".ae": "AE", ".bd": "BD", ".ng": "NG", ".de": "DE", ".fr": "FR", ".es": "ES",
              ".br": "BR", ".mx": "MX", ".sa": "SA"}
LANG_REGION = {"hi": "IN", "ur": "PK", "bn": "BD", "ta": "IN", "te": "IN", "pa": "IN", "ml": "IN",
               "kn": "IN", "gu": "IN"}


def guess_region(account, a):
    votes = collections.Counter()
    why = collections.defaultdict(list)
    bio = account.get("bio") or ""
    for m in FLAG_RE.finditer(bio):
        cc = chr(ord(m.group(1)) - 0x1F1E6 + 65) + chr(ord(m.group(2)) - 0x1F1E6 + 65)
        votes[cc] += 3
        why[cc].append("flag in bio")
    low = re.sub(r"[^a-z ]", " ", (bio + " " + (account.get("name") or "")).lower())
    words = set(low.split()) | {low.replace(" ", "")}
    for cc, places in PLACE_REGION.items():
        hit = [w for w in places.split() if w in words or f" {w} " in f" {low} "]
        if hit:
            votes[cc] += 3
            why[cc].append("bio mentions " + hit[0])
    site = (account.get("website") or "").lower()
    host = re.sub(r"^https?://", "", site).split("/")[0]
    for tld, cc in sorted(TLD_REGION.items(), key=lambda kv: -len(kv[0])):
        if host.endswith(tld):
            votes[cc] += 2
            why[cc].append(f"website ends {tld}")
            break
    for l in (a or {}).get("content", {}).get("languages", []):
        code = l["code"]
        cc = LANG_REGION.get(code) or ("IN" if code == "hi-Latn" else None)
        if cc and l["share"] >= 0.1:
            votes[cc] += 2 if code != "hi-Latn" else 1
            why[cc].append(f"{l['label']} captions")
    if not votes:
        return None, "no clue in bio, website or language. Ask the user"
    cc, _ = votes.most_common(1)[0]
    return cc, "; ".join(why[cc])


def typical_captions(posts, a, k=3):
    feed = [p for p in posts if p.get("type") != "story" and len((p.get("caption") or "").split()) >= 5]
    if not feed:
        return []
    top = {w for w, _ in (a or {}).get("content", {}).get("top_keywords", [])[:20]}
    lens = [len(WORD_RE.findall(body_text(p["caption"]))) for p in feed]
    med = statistics.median(lens)

    def score(p, n):
        overlap = len(set(tokens(p["caption"])) & top)
        return overlap - abs(n - med) / max(5.0, med)

    ranked = sorted(zip(feed, lens), key=lambda pn: -score(*pn))
    out, seen = [], set()
    for p, _ in ranked:
        key = _key_text(p["caption"], 30)
        if key in seen:
            continue
        seen.add(key)
        out.append({"date": p.get("date"), "type": p.get("type"), "caption": p["caption"]})
        if len(out) == k:
            break
    return out


def prefill(account, posts, a):
    region, region_why = guess_region(account, a)
    at = account.get("account_type")
    at = at if at in ("creator", "business") else None
    langs = (a or {}).get("content", {}).get("languages", [])
    lang = None
    if langs:
        code = langs[0]["code"]
        lang = {"hi-Latn": "hinglish", "zh/ja": None, "latin-other": None}.get(code, code)
    ng = (a or {}).get("niche_guess") or {}
    niche = ng.get("label") if ng.get("label") not in (None, "unknown") else None
    sugg = {"region": region, "niche": niche, "account_type": at, "language": lang}
    why = {"region": region_why,
           "niche": f"keyword guess, confidence {ng.get('confidence', 'low')}. Confirm in the user's words",
           "account_type": f"from {account.get('source')}" if at else "unknown. Ask: creator or business?",
           "language": "dominant script in captions" if lang else "not clear"}
    parts = ["python3 ~/.claude/skills/ig/state.py set"]
    flags = {"region": "--region", "niche": "--niche", "account_type": "--account-type", "language": "--language"}
    for k, flag in flags.items():
        if sugg[k]:
            v = sugg[k]
            parts.append(f'{flag} "{v}"' if " " in v else f"{flag} {v}")
    return {"suggested": sugg, "why": why, "command": " ".join(parts),
            "typical_captions": typical_captions(posts, a)}


# ---------------------------------------------------------------- cli

def _require_scan():
    acc, posts = load_scan()
    if acc is None:
        print("no scan yet. Run one of: scan.py api / scan.py ingest --captured FILE / scan.py dyi PATH",
              file=sys.stderr)
        return None, None
    return acc, posts


def _load_analysis():
    return _read_json(os.path.join(data_dir(), "account.json"))


def main(argv=None):
    ap = argparse.ArgumentParser(description="Read the account we are growing and profile it.")
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("api", help="read via the Instagram API (IG_ACCESS_TOKEN in env)")
    s.add_argument("--max", type=int, default=MAX_POSTS)
    s.add_argument("--insights", action="store_true", help="also read per-post insights")
    s.add_argument("--replace", action="store_true", help="start the scan over instead of merging")
    s = sub.add_parser("dyi", help="read a Download Your Information export (zip or folder)")
    s.add_argument("path")
    s.add_argument("--followers", type=int, help="follower count, which the export does not hold")
    s.add_argument("--handle")
    s.add_argument("--stories", action="store_true", help="include stories")
    s.add_argument("--replace", action="store_true")
    s = sub.add_parser("ingest", help="read a captured JSON file (kweo, screenshots, manual)")
    s.add_argument("--captured", required=True, action="append",
                   help="captured JSON; repeat to merge several (profile + posts + insights jobs)")
    s.add_argument("--replace", action="store_true")
    s = sub.add_parser("analyze", help="write account.md and account.json")
    s.add_argument("--json", action="store_true")
    s.add_argument("--today", help=argparse.SUPPRESS)
    s = sub.add_parser("context", help="the short context block for other skills")
    s.add_argument("--json", action="store_true")
    s = sub.add_parser("to-ledger", help="copy scanned posts into the ledger")
    s.add_argument("--dry-run", action="store_true")
    s.add_argument("--json", action="store_true")
    s = sub.add_parser("prefill", help="suggest state.py set values and typical captions")
    s.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)

    if args.cmd in ("api", "dyi", "ingest"):
        try:
            if args.cmd == "api":
                client = APIClient(os.environ.get("IG_ACCESS_TOKEN"))
                acc, posts, raw, notes = from_api(client, max(1, min(args.max, 1000)), args.insights)
            elif args.cmd == "dyi":
                acc, posts, raw, notes = from_dyi(args.path, args.stories)
                if args.followers is not None:
                    acc["followers"] = args.followers
                if args.handle:
                    acc["handle"] = args.handle.lstrip("@").lower()
            else:
                acc, posts, raw, notes, stash = from_captured(args.captured)
        except Blocked as e:
            print(f"kweo hit a login wall: {e}", file=sys.stderr)
            print("Nothing was saved. Ask the user to log in to Instagram in kweo themselves, "
                  "then run the reader again.", file=sys.stderr)
            return 3
        except APIError as e:
            print(f"API: {e}", file=sys.stderr)
            if "not set" in str(e):
                print("Set it in your shell (export IG_ACCESS_TOKEN=...) and run again. "
                      "Do not paste it into the chat.", file=sys.stderr)
            return 2
        except (OSError, ValueError, zipfile.BadZipFile) as e:
            print(f"could not read the source: {e}", file=sys.stderr)
            return 2
        if args.cmd != "ingest":
            stash = []
        acc_all, posts_all, more = save_scan(acc, posts, acc["source"], raw, replace=args.replace,
                                             insights=stash)
        print_ingest_summary(acc_all, posts_all, len(posts), acc["source"], notes=list(notes) + more)
        return 0

    if args.cmd == "analyze":
        acc, posts = _require_scan()
        if acc is None:
            return 2
        today = dt.date.fromisoformat(args.today) if args.today else None
        a = analyze(acc, posts, today)
        md_path = os.path.join(data_dir(), "account.md")
        old_read = None
        try:
            with open(md_path, encoding="utf-8") as f:
                old_read = extract_claude_read(f.read())
        except OSError:
            pass
        os.makedirs(data_dir(), exist_ok=True)
        with open(md_path + ".tmp", "w", encoding="utf-8") as f:
            f.write(to_markdown(a, old_read))
        os.replace(md_path + ".tmp", md_path)
        _write_json(os.path.join(data_dir(), "account.json"), a)
        if args.json:
            print(json.dumps(a, indent=2, ensure_ascii=False))
        else:
            render_summary(a)
            print(f"  wrote {md_path}")
            print(f"  wrote {os.path.join(data_dir(), 'account.json')}\n")
        return 0

    if args.cmd == "context":
        a = _load_analysis()
        if not a:
            print("no account profile yet. Run /ig-scan (scan.py analyze).", file=sys.stderr)
            return 2
        read = None
        try:
            with open(os.path.join(data_dir(), "account.md"), encoding="utf-8") as f:
                read = extract_claude_read(f.read())
        except OSError:
            pass
        lines = context_block(a, load_profile_json(), read)
        if args.json:
            print(json.dumps({"lines": lines, "text": "\n".join(lines)}, indent=2, ensure_ascii=False))
        else:
            print("\n".join(lines))
        return 0

    if args.cmd == "to-ledger":
        acc, posts = _require_scan()
        if acc is None:
            return 2
        try:
            summ = to_ledger(posts, _load_analysis(), dry_run=args.dry_run)
        except RuntimeError as e:
            print(str(e), file=sys.stderr)
            return 2
        if args.json:
            print(json.dumps(summ, indent=2))
        else:
            lead = "would " if args.dry_run else ""
            print(f"  {lead}create     {summ['created']}")
            print(f"  {lead}update     {summ['updated']}")
            print(f"  unchanged  {summ['unchanged']}")
            if summ["skipped"]:
                print(f"  skipped    {summ['skipped']} (no date and no link)")
            print("")
        return 0

    if args.cmd == "prefill":
        acc, posts = _require_scan()
        if acc is None:
            return 2
        a = _load_analysis() or analyze(acc, posts)
        pf = prefill(acc, posts, a)
        if args.json:
            print(json.dumps(pf, indent=2, ensure_ascii=False))
            return 0
        print("\nPREFILL  ·  suggestions only. Confirm with the user before saving.")
        print("=" * 64)
        for k, v in pf["suggested"].items():
            print(f"  {k:<13} {v or '-':<28} {pf['why'][k]}")
        print("-" * 64)
        print(f"  {pf['command']}")
        if pf["typical_captions"]:
            print("\nTYPICAL CAPTIONS (for drafting voice.md, with the user's approval)")
            print("-" * 64)
            for i, c in enumerate(pf["typical_captions"], 1):
                text = " ".join(c["caption"].split())
                print(f"  {i}. {c['date']} {c['type']}: {text[:280]}{'...' if len(text) > 280 else ''}")
        print("")
        return 0
    return 1


if __name__ == "__main__":
    sys.exit(main())
