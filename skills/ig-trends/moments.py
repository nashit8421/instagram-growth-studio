#!/usr/bin/env python3
"""moments.py - what the internet is talking about right now, in one call.

Google Trends' hourly feed is search spikes of a few hundred searches. It
misses the moments creators actually make reels about (a product launch the
whole world is laughing at, a match, a meme). This reads two public places
where those show up, once each:

  - X trends for the last 24 hours, region and worldwide (trends24.in): a
    topic that stayed on the list for many hours is big; one hour is noise.
  - Google News top stories, region and US.

A topic that is trending on X and is also in the news headlines is marked as
a moment. Claude still judges each one (taste, safety, whether it fits the
niche) and checks on Instagram that creators are riffing on it.

Usage
  python3 moments.py --region IN
  python3 moments.py --region IN --json
  python3 moments.py --x-html t24.html --news-rss news.xml   # offline, for tests

Stdlib only. Two to four page loads per run, nothing logged in.
"""

import argparse
import datetime as dt
import html
import json
import re
import sys
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET

UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_0) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Safari/605.1.15"
T24 = {"IN": "india", "US": "united-states", "GB": "united-kingdom", "AE": "united-arab-emirates",
       "PK": "pakistan", "BD": "bangladesh", "CA": "canada", "AU": "australia", "SG": "singapore",
       "NG": "nigeria", "ID": "indonesia", "PH": "philippines", "SA": "saudi-arabia", "DE": "germany",
       "FR": "france", "BR": "brazil", "MX": "mexico", "JP": "japan", "ES": "spain", "IT": "italy"}
NEWS = {"IN": ("en-IN", "IN", "IN:en"), "US": ("en-US", "US", "US:en"), "GB": ("en-GB", "GB", "GB:en")}
BLOCK_RE = re.compile(r'data-timestamp=["\']?([\d.]+)["\']?[^>]*>.*?<ol[^>]*>(.*?)</ol>', re.S)
LINK_RE = re.compile(r'class=["\']?trend-link["\']?[^>]*>(.*?)</a>', re.S)
WORD_RE = re.compile(r"[^\W_]+", re.U)     # "Jio's" -> jio, s (the s is dropped as too short)
STOP = {"the", "a", "an", "of", "in", "on", "and", "for", "to", "vs", "with", "at", "is", "day", "live", "news"}


def fetch(url, timeout=15):
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept-Language": "en"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read().decode("utf-8", "replace")


# ---------------------------------------------------------------- X trends

def parse_x(page, now=None):
    """[(timestamp, [names...]), ...], newest first, from a trends24.in page."""
    snaps = []
    for ts, body in BLOCK_RE.findall(page):
        names = [html.unescape(re.sub(r"<[^>]+>", "", n)).strip() for n in LINK_RE.findall(body)]
        snaps.append((float(ts), [n for n in names if n]))
    snaps.sort(key=lambda s: -s[0])
    if now is not None:
        snaps = [s for s in snaps if now - s[0] <= 24 * 3600]
    return snaps


def x_hours(snaps):
    """{name: {"hours": snapshots seen in, "best": best rank, "first": ts, "last": ts}}."""
    out = {}
    for ts, names in snaps:
        for rank, n in enumerate(names, 1):
            key = n.lower()
            e = out.setdefault(key, {"name": n, "hours": 0, "best": rank, "first": ts, "last": ts})
            e["hours"] += 1
            e["best"] = min(e["best"], rank)
            e["first"] = min(e["first"], ts)
            e["last"] = max(e["last"], ts)
    return out


# ---------------------------------------------------------------- news

def parse_news(xml_text):
    """[{"title", "source", "date"}] from a Google News RSS feed."""
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError:
        return []
    items = []
    for it in root.iter("item"):
        title = (it.findtext("title") or "").strip()
        src = (it.findtext("source") or "").strip()
        if src and title.endswith(" - " + src):
            title = title[: -len(src) - 3]
        items.append({"title": title, "source": src, "date": (it.findtext("pubDate") or "").strip()})
    return items


def news_url(region):
    hl, gl, ceid = NEWS.get(region, (f"en-{region}", region, f"{region}:en"))
    return "https://news.google.com/rss?" + urllib.parse.urlencode({"hl": hl, "gl": gl, "ceid": ceid})


# ---------------------------------------------------------------- moments

def words(text):
    """Content words, with #CamelCase hashtags split: #TeslaRoadster -> tesla, roadster."""
    text = re.sub(r"#(\w+)", lambda m: re.sub(r"(?<=[a-z])(?=[A-Z])", " ", m.group(1)), text)
    return [w.lower() for w in WORD_RE.findall(text) if w.lower() not in STOP and len(w) > 1]


def in_headline(name, headline_words):
    w = words(name)
    return bool(w) and all(x in headline_words for x in w)


def build(x_region, x_world, news, top=15):
    """Rank topics: in the news and on X first, then by hours on X."""
    heads = [(n, set(words(n["title"]))) for n in news]
    merged = {}
    for scope, table in (("region", x_region), ("world", x_world)):
        for key, e in table.items():
            m = merged.setdefault(key, {"name": e["name"], "hours": 0, "where": [], "best": e["best"],
                                        "first": e["first"], "last": e["last"]})
            m["hours"] = max(m["hours"], e["hours"])
            m["where"].append(scope)
            m["best"] = min(m["best"], e["best"])
            m["first"], m["last"] = min(m["first"], e["first"]), max(m["last"], e["last"])
    # "Tesla" and "Tesla Roadster" are one moment: fold the shorter into the longer name.
    keys = sorted(merged, key=lambda k: -len(words(merged[k]["name"])))
    for k in keys:
        wk = set(words(merged[k]["name"]))
        for big in keys:
            if big == k or big not in merged or k not in merged:
                continue
            wb = set(words(merged[big]["name"]))
            if wk and wk < wb:
                b, m = merged[big], merged.pop(k)
                b["hours"] = max(b["hours"], m["hours"])
                b["best"] = min(b["best"], m["best"])
                b["where"] = sorted(set(b["where"]) | set(m["where"]))
                b["first"], b["last"] = min(b["first"], m["first"]), max(b["last"], m["last"])
                break
    out = []
    for m in merged.values():
        hits = [n for n, hw in heads if in_headline(m["name"], hw)]
        m["news"] = [h["title"] for h in hits[:2]]
        m["moment"] = bool(hits)
        out.append(m)
    out.sort(key=lambda m: (not m["moment"], -m["hours"], m["best"]))
    for m in out:
        m["first_seen"] = dt.datetime.fromtimestamp(m.pop("first"), dt.timezone.utc).strftime("%Y-%m-%d %H:%M")
        m["last_seen"] = dt.datetime.fromtimestamp(m.pop("last"), dt.timezone.utc).strftime("%Y-%m-%d %H:%M")
    return out[:top]


def run(region, world="US", x_html=None, x_world_html=None, news_rss=None, now=None, top=15):
    region = region.upper()
    notes = []
    now = now if now is not None else dt.datetime.now(dt.timezone.utc).timestamp()

    def x_for(code, given):
        if given is not None:
            return parse_x(given, now)
        slug = T24.get(code, "") if code != "WORLD" else ""
        if code != "WORLD" and not slug:
            notes.append(f"no X trends page known for {code}")
            return []
        try:
            return parse_x(fetch(f"https://trends24.in/{slug + '/' if slug else ''}"), now)
        except Exception as e:                      # network, blocked, layout changed
            notes.append(f"X trends {code}: {e}")
            return []

    snaps_r = x_for(region, x_html)
    snaps_w = x_for("WORLD", x_world_html) if (x_html is None or x_world_html is not None) else []
    news = []
    if news_rss is not None:
        news = parse_news(news_rss)
    else:
        for code in dict.fromkeys([region, world.upper()]):
            try:
                got = parse_news(fetch(news_url(code)))
                news += [dict(n, region=code) for n in got[:40]]
            except Exception as e:
                notes.append(f"news {code}: {e}")
    if snaps_r == [] and x_html is None:
        notes.append("no X trends read; moments rest on the news alone")
    return {"region": region, "snapshots": len(snaps_r), "news": len(news),
            "moments": build(x_hours(snaps_r), x_hours(snaps_w), news, top),
            "headlines": [n["title"] for n in news[:20]], "notes": notes}


def render(r, out=sys.stdout):
    p = lambda *a: print(*a, file=out)  # noqa: E731
    p(f"\nMOMENTS  ·  {r['region']}  ·  X: {r['snapshots']} hourly lists  ·  news: {r['news']} headlines")
    p("=" * 78)
    for m in r["moments"]:
        tag = "MOMENT" if m["moment"] else "x only"
        p(f"  {tag:<6}  {m['hours']:>2}h on X ({'/'.join(m['where'])}, best #{m['best']})  {m['name']}")
        for h in m["news"]:
            p(f"            news: {h[:90]}")
    p("-" * 78)
    p("TOP HEADLINES")
    for h in r["headlines"][:12]:
        p(f"  - {h[:96]}")
    for n in r["notes"]:
        p(f"  note: {n}")
    p("\n  Hours on X = how many hourly lists it was on in the last 24h. MOMENT = also in the news.")
    p("  Judge each one: taste, safety, a real bridge to the niche. Then check Instagram.\n")


def main(argv=None):
    ap = argparse.ArgumentParser(description="What the internet is talking about right now.")
    ap.add_argument("--region", default="IN", help="country code, e.g. IN, US, GB")
    ap.add_argument("--world", default="US", help="second news edition (default US)")
    ap.add_argument("--top", type=int, default=15)
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--x-html", help=argparse.SUPPRESS)
    ap.add_argument("--x-world-html", help=argparse.SUPPRESS)
    ap.add_argument("--news-rss", help=argparse.SUPPRESS)
    ap.add_argument("--now", type=float, help=argparse.SUPPRESS)
    a = ap.parse_args(argv)
    read = lambda p: open(p, encoding="utf-8").read() if p else None  # noqa: E731
    r = run(a.region, a.world, read(a.x_html), read(a.x_world_html), read(a.news_rss), a.now, a.top)
    if a.json:
        print(json.dumps(r, ensure_ascii=False, indent=2))
    else:
        render(r)
    return 0 if (r["moments"] or r["headlines"]) else 1


if __name__ == "__main__":
    sys.exit(main())
