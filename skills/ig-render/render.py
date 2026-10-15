#!/usr/bin/env python3
"""
render.py - turn approved carousel or story copy into the PNG files Instagram
actually takes.

/ig-carousel and /ig-story write the words. This builds the images: one HTML
page per slide, screenshotted by headless Chrome at the exact pixel size, then
checked by reading the PNG header. No PDF, no upload, no network.

  carousel  1080x1350 (4:5)   slide-01.png ...  + grid-preview.png + alt-text.txt
  story     1080x1920 (9:16)  frame-01.png ...  + alt-text.txt

Spec (JSON)
  {"kind": "carousel", "handle": "@name", "alt": "alt text for the cover",
   "slides": [{"title": "THE $18,000 CLAUSE",
               "body": "One line I now put in every contract."},
              {"role": "recap", "title": "The four lines",
               "list": ["Payment on delivery", "..."]},
              {"role": "cta", "title": "Comment CONTRACT", "body": "..."}]}

  {"kind": "story",
   "frames": [{"title": "Third refund request this year.",
               "note": "selfie, walking"},
              {"title": "Have you been burned by a late approval?",
               "sticker": "poll: Yes / Not yet"}]}

Brand (JSON, optional): bg, fg, accent, font_display, font_body, handle.
Looked up in --brand, then brand.json in the active account's data folder
($IG_DATA_DIR, else the active account from /ig-account, else
~/.claude/instagram), then the built-in default.

Usage
  python3 render.py spec.json --out ./out
  python3 render.py spec.json --out ./out --brand brand.json --keep-html
  python3 render.py story.json --out ./out --kind story

Chrome is found at $CHROME_PATH, then the usual macOS app paths, then
chromium / google-chrome on PATH.
"""

import argparse
import concurrent.futures
import html
import json
import os
import re
import shutil
import struct
import subprocess
import sys
import tempfile
from pathlib import Path

CAROUSEL = (1080, 1350)
STORY = (1080, 1920)
MAX_SLIDES = 20          # Instagram's cap per carousel.
MIN_SLIDES = 5           # Under this the swipe never starts.
MAX_FRAMES = 7           # Past this the tap-forward rate climbs.
MIN_FONT = 32            # Read on a phone at a third of real size.
COVER_SAFE = 120         # Cover text stays clear of the outer 120px.
STORY_TOP, STORY_BOTTOM = 250, 1600   # Profile row above, reply bar below.
BODY_WORDS = 25          # More than this on one slide and it is two slides.
COVER_WORDS = 6          # A cover hook longer than this does not read at thumbnail.
TITLE_WORDS = 7          # Slide headline: three to seven words.
SHRINK_WARN = 0.7        # Title ended below 70% of its full size: too long.

DEFAULT_BRAND = {
    "bg": "#F6F3EE",
    "fg": "#16181D",
    "accent": "#E4572E",
    "font_display": '"Avenir Next", "Helvetica Neue", -apple-system, Helvetica, Arial, sans-serif',
    "font_body": '-apple-system, "Helvetica Neue", Helvetica, Arial, sans-serif',
    "handle": "",
}

CHROME_CANDIDATES = [
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
    "/Applications/Chromium.app/Contents/MacOS/Chromium",
    "/Applications/Google Chrome Canary.app/Contents/MacOS/Google Chrome Canary",
]
CHROME_ON_PATH = ["chromium", "google-chrome", "chromium-browser", "google-chrome-stable", "chrome"]


class SpecError(Exception):
    pass


# ---------------------------------------------------------------- colour

HEX_RE = re.compile(r"^#(?:[0-9a-fA-F]{3}|[0-9a-fA-F]{6})$")


def parse_hex(value):
    if not isinstance(value, str) or not HEX_RE.match(value.strip()):
        raise SpecError(f"colour {value!r} is not a hex colour like #16181D")
    h = value.strip()[1:]
    if len(h) == 3:
        h = "".join(c * 2 for c in h)
    return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))


def luminance(rgb):
    def chan(c):
        c = c / 255
        return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4
    r, g, b = (chan(c) for c in rgb)
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def contrast(a, b):
    la, lb = sorted((luminance(parse_hex(a)), luminance(parse_hex(b))), reverse=True)
    return (la + 0.05) / (lb + 0.05)


# ---------------------------------------------------------------- brand

def data_dir():
    """The active account's data folder. Same rule as ig-account/account.py:
    $IG_DATA_DIR, else $IG_HOME/accounts/<active-account>/ if it exists,
    else $IG_HOME (default ~/.claude/instagram)."""
    env = os.environ.get("IG_DATA_DIR")
    if env:
        return Path(env).expanduser()
    home = Path(os.environ.get("IG_HOME") or "~/.claude/instagram").expanduser()
    try:
        h = (home / "active-account").read_text(encoding="utf-8").strip().lstrip("@").strip().lower()
    except OSError:
        h = ""
    if h and re.match(r"^[a-z0-9._]{1,30}$", h) and ".." not in h and (home / "accounts" / h).is_dir():
        return home / "accounts" / h
    return home


def font_stack(value, fallback):
    """A brand font name becomes a CSS stack with system fallbacks.
    Anything that could break out of the style block is stripped."""
    if not value or not isinstance(value, str):
        return fallback
    clean = re.sub(r"[^A-Za-z0-9 ,\"'\-_.]", "", value).strip()
    if not clean:
        return fallback
    if "," not in clean:
        clean = '"' + clean.strip("\"'") + '"'
    return clean + ", " + fallback


def load_brand(path=None):
    """Returns (brand, source, warnings)."""
    source = "built-in default"
    raw = {}
    if path:
        p = Path(path).expanduser()
        if not p.exists():
            raise SpecError(f"brand file not found: {p}")
        raw, source = json.loads(p.read_text()), str(p)
    else:
        p = data_dir() / "brand.json"
        if p.exists():
            raw, source = json.loads(p.read_text()), str(p)
    if not isinstance(raw, dict):
        raise SpecError("brand file must be a JSON object")
    brand = dict(DEFAULT_BRAND)
    for key in ("bg", "fg", "accent", "handle"):
        if raw.get(key):
            brand[key] = str(raw[key]).strip()
    for key in ("bg", "fg", "accent"):
        parse_hex(brand[key])
    brand["font_display"] = font_stack(raw.get("font_display"), DEFAULT_BRAND["font_display"])
    brand["font_body"] = font_stack(raw.get("font_body"), DEFAULT_BRAND["font_body"])
    warnings = []
    ratio = contrast(brand["fg"], brand["bg"])
    if ratio < 4.5:
        warnings.append(f"text contrast fg/bg is {ratio:.1f}:1, under the 4.5:1 minimum. "
                        "Darken fg or lighten bg.")
    acc = contrast(brand["accent"], brand["bg"])
    if acc < 3:
        warnings.append(f"accent contrast on bg is {acc:.1f}:1, under 3:1. "
                        "Accent text will be hard to read.")
    return brand, source, warnings


# ---------------------------------------------------------------- text fit

def char_em(ch, display):
    """Rough advance width in em. Deliberately generous so the estimate
    errs towards smaller type, never towards overflow."""
    if ch == " ":
        return 0.30
    if ch in "MW@%":
        return 0.95 if display else 0.85
    if ch in "mw":
        return 0.85 if display else 0.80
    if ch.isupper():
        return 0.72 if display else 0.68
    if ch.isdigit():
        return 0.62
    if ch in "ilj.,:;'!|":
        return 0.30
    if ch.isalpha():
        return 0.61 if display else 0.53
    return 0.60


def text_width(text, size, display):
    return sum(char_em(c, display) for c in text) * size


def wrap_lines(text, size, width, display):
    """Greedy word wrap. Returns (line count, longest single word fits)."""
    total = 0
    word_fits = True
    space = char_em(" ", display) * size
    for para in str(text).split("\n"):
        words = para.split()
        if not words:
            total += 1
            continue
        lines, cur = 1, 0.0
        for w in words:
            ww = text_width(w, size, display)
            if ww > width:
                word_fits = False
            if cur == 0:
                cur = ww
            elif cur + space + ww <= width:
                cur += space + ww
            else:
                lines += 1
                cur = ww
        total += lines
    return total, word_fits


def fit_size(text, width, height, hi, lo, line_height, display):
    """Largest size in [lo, hi] where text fits the box. (size, fits)."""
    if not text:
        return hi, True
    size = hi
    while size >= lo:
        n, ok = wrap_lines(text, size, width, display)
        if ok and n * size * line_height <= height:
            return size, True
        size -= 2
    return lo, False


def block_height(text, size, width, line_height, display):
    if not text:
        return 0
    n, _ = wrap_lines(text, size, width, display)
    return n * size * line_height


# ---------------------------------------------------------------- html

def title_checks(label, title, size, hi, fits, max_words, warnings):
    """One warning per slide title, worst problem first."""
    words = len(title.split())
    if not fits:
        if any(text_width(w, MIN_FONT, True) > 700 for w in title.split()):
            warnings.append(f"{label}: title has a word too long for one line. It will break mid-word.")
        else:
            warnings.append(f"{label}: title does not fit even at the smallest size. Split this slide.")
    elif size < hi * SHRINK_WARN:
        warnings.append(f"{label}: title shrank to {size}px to fit ({words} words). "
                        f"Cut it to {max_words} words or split this slide.")
    elif words > max_words:
        shrunk = f", and shrank to {size}px to fit" if size < hi else ""
        warnings.append(f"{label}: title is {words} words, over {max_words}{shrunk}. "
                        "Cut words or split this slide.")


def esc(text):
    return html.escape(str(text or ""), quote=True).replace("\n", "<br>")


BASE_CSS = """
*{box-sizing:border-box;margin:0;padding:0}
html,body{width:%(w)dpx;height:%(h)dpx;overflow:hidden}
body{background:%(bg)s;color:%(fg)s;font-family:%(fb)s;position:relative;
  -webkit-font-smoothing:antialiased;text-rendering:geometricPrecision}
.display{font-family:%(fd)s;font-weight:800;letter-spacing:-0.01em;
  line-height:1.04;text-wrap:balance;overflow-wrap:break-word}
.body{line-height:1.32;overflow-wrap:break-word;opacity:.86}
.rule{width:96px;height:10px;background:%(accent)s;border-radius:5px}
.meta{position:absolute;font-size:32px;font-weight:600;letter-spacing:.02em}
.handle{opacity:.62}
.num{color:%(accent)s;font-variant-numeric:tabular-nums}
.fit{position:absolute;display:flex;flex-direction:column;overflow:hidden}
"""

# Belt and braces: the Python estimate sizes the type, this shrinks it further
# in the browser if the real font still overflows. Never below MIN_FONT.
FIT_JS = """
<script>
(function(){
  var MIN=%d;
  document.querySelectorAll('.fit').forEach(function(box){
    var els=box.querySelectorAll('[data-shrink]');
    for(var i=0;i<80 && (box.scrollHeight>box.clientHeight+1 || box.scrollWidth>box.clientWidth+1);i++){
      var moved=false;
      els.forEach(function(el){
        var s=parseFloat(getComputedStyle(el).fontSize);
        if(s>MIN){el.style.fontSize=Math.max(MIN,s-2)+'px';moved=true;}
      });
      if(!moved)break;
    }
  });
})();
</script>
""" % MIN_FONT


def page(brand, size, inner):
    w, h = size
    css = BASE_CSS % {"w": w, "h": h, "bg": brand["bg"], "fg": brand["fg"],
                      "accent": brand["accent"], "fb": brand["font_body"],
                      "fd": brand["font_display"]}
    return ("<!doctype html><html><head><meta charset=\"utf-8\">"
            f"<style>{css}</style></head><body>{inner}{FIT_JS}</body></html>")


def slide_role(slide, index, total):
    role = str(slide.get("role") or "").lower()
    if role in ("cover", "recap", "cta", "body", "stake"):
        return "body" if role == "stake" else role
    if index == 0:
        return "cover"
    if slide.get("list"):
        return "recap"
    return "body"


def carousel_slide_html(slide, index, total, brand, handle, warnings):
    w, h = CAROUSEL
    role = slide_role(slide, index, total)
    title = str(slide.get("title") or "").strip()
    body = str(slide.get("body") or "").strip()
    items = [str(x).strip() for x in (slide.get("list") or []) if str(x).strip()]
    label = f"slide {index + 1}"
    parts = []

    if body and len(body.split()) > BODY_WORDS:
        warnings.append(f"{label}: body is {len(body.split())} words, over {BODY_WORDS}. "
                        "Split this slide.")

    if role == "cover":
        pad = COVER_SAFE + 24
        box_w = w - 2 * pad
        top, bottom = pad, h - pad - 70   # leave room for the handle line
        avail = bottom - top - 10 - 48      # rule + gap
        body_size, body_ok = fit_size(body, box_w, 300, 48, 36, 1.32, False)
        bh = block_height(body, body_size, box_w, 1.32, False)
        t_size, t_ok = fit_size(title, box_w, avail - bh - (44 if body else 0), 168, 72, 1.04, True)
        title_checks(label, title, t_size, 168, t_ok, COVER_WORDS, warnings)
        if not body_ok:
            warnings.append(f"{label}: cover subline is too long. Cut it to one line.")
        parts.append(
            f'<div class="fit" style="left:{pad}px;top:{top}px;width:{box_w}px;'
            f'height:{bottom - top}px;justify-content:center;gap:0">'
            f'<div class="rule" style="margin-bottom:48px"></div>'
            f'<div class="display" data-shrink style="font-size:{t_size}px">{esc(title)}</div>'
            + (f'<div class="body" data-shrink style="font-size:{body_size}px;margin-top:44px">'
               f'{esc(body)}</div>' if body else "")
            + "</div>")
        if handle:
            parts.append(f'<div class="meta handle" style="left:{pad}px;bottom:{pad - 8}px">'
                         f'{esc(handle)}</div>')
        parts.append(f'<div class="meta num" style="right:{pad}px;bottom:{pad - 8}px">'
                     f'Swipe &rarr;</div>')
        alt = f"{title.rstrip('.')}. {body}" if body else title
        return page(brand, CAROUSEL, "".join(parts)), alt

    pad = 96
    box_w = w - 2 * pad
    top, bottom = 180, h - 170
    num = f"{index + 1}/{total}"
    parts.append(f'<div class="meta num" style="right:{pad}px;top:84px">{num}</div>')
    if handle:
        parts.append(f'<div class="meta handle" style="left:{pad}px;bottom:84px">{esc(handle)}</div>')

    if role == "recap":
        list_text = "\n".join(items)
        n_items = max(1, len(items))
        avail = bottom - top - 10 - 40
        t_size, t_ok = fit_size(title, box_w, 260, 84, 48, 1.04, True)
        th = block_height(title, t_size, box_w, 1.04, True)
        item_w = box_w - 92
        li_size, li_ok = 46, False
        while li_size >= MIN_FONT:
            lh = sum(block_height(it, li_size, item_w, 1.25, False) for it in items)
            if lh + (n_items - 1) * li_size * 0.75 <= avail - th - 56:
                li_ok = True
                break
            li_size -= 2
        li_size = max(li_size, MIN_FONT)
        if not (t_ok and li_ok):
            warnings.append(f"{label}: recap does not fit at {MIN_FONT}px. "
                            "Shorten the items or split this slide.")
        lis = "".join(
            f'<li style="display:flex;gap:28px;align-items:baseline;margin-top:{int(li_size * 0.75) if i else 0}px">'
            f'<span class="num" style="font-weight:800;min-width:64px;font-family:inherit">'
            f'{i + 1:02d}</span><span>{esc(it)}</span></li>'
            for i, it in enumerate(items))
        parts.append(
            f'<div class="fit" style="left:{pad}px;top:{top}px;width:{box_w}px;'
            f'height:{bottom - top}px;justify-content:center">'
            f'<div class="rule" style="margin-bottom:40px"></div>'
            f'<div class="display" data-shrink style="font-size:{t_size}px;margin-bottom:56px">{esc(title)}</div>'
            f'<ol data-shrink style="list-style:none;font-size:{li_size}px;line-height:1.25;font-weight:500">'
            f'{lis}</ol></div>')
        return page(brand, CAROUSEL, "".join(parts)), title + ": " + "; ".join(items)

    center = role == "cta"
    avail = bottom - top - 10 - 44
    body_size, body_ok = fit_size(body, box_w, 520, 48 if center else 46, 34, 1.32, False)
    if not body_ok:
        warnings.append(f"{label}: body does not fit. Split this slide.")
    bh = block_height(body, body_size, box_w, 1.32, False)
    t_hi = 120 if center else 104
    t_size, t_ok = fit_size(title, box_w, avail - bh - (48 if body else 0), t_hi, 48, 1.04, True)
    title_checks(label, title, t_size, t_hi, t_ok, TITLE_WORDS, warnings)
    talign = "center" if center else "left"
    rule_style = "margin:0 auto 44px" if center else "margin-bottom:44px"
    body_html = ""
    if body:
        extra = f";color:{brand['accent']};opacity:1;font-weight:700" if center else ""
        body_html = (f'<div class="body" data-shrink style="font-size:{body_size}px;margin-top:48px;'
                     f'text-align:{talign}{extra}">{esc(body)}</div>')
    parts.append(
        f'<div class="fit" style="left:{pad}px;top:{top}px;width:{box_w}px;'
        f'height:{bottom - top}px;justify-content:center;align-items:stretch">'
        f'<div class="rule" style="{rule_style}"></div>'
        f'<div class="display" data-shrink style="font-size:{t_size}px;text-align:{talign}">{esc(title)}</div>'
        f'{body_html}</div>')
    alt = f"{title.rstrip('.')}. {body}" if body else title
    return page(brand, CAROUSEL, "".join(parts)), alt


def story_frame_html(frame, index, brand, warnings):
    w, h = STORY
    title = str(frame.get("title") or frame.get("text") or "").strip()
    body = str(frame.get("body") or "").strip()
    sticker = str(frame.get("sticker") or "").strip()
    label = f"frame {index + 1}"
    pad = 96
    box_w = w - 2 * pad
    top, bottom = STORY_TOP + 30, STORY_BOTTOM - 30
    sticker_h = 0
    parts = []
    if sticker:
        kind, _, opts = sticker.partition(":")
        kind = kind.strip().upper() or "STICKER"
        sticker_h = 300
        s_top = bottom - sticker_h
        parts.append(
            f'<div style="position:absolute;left:{pad + 60}px;top:{s_top}px;width:{box_w - 120}px;'
            f'height:{sticker_h}px;border:5px dashed {brand["accent"]};border-radius:36px;'
            f'display:flex;flex-direction:column;align-items:center;justify-content:center;gap:18px;'
            f'text-align:center;padding:0 40px">'
            f'<div style="font-size:40px;font-weight:800;color:{brand["accent"]};letter-spacing:.02em">'
            f'add {esc(kind)} sticker here</div>'
            + (f'<div style="font-size:34px;opacity:.75">{esc(opts.strip())}</div>' if opts.strip() else "")
            + '<div style="font-size:32px;opacity:.55">in the Instagram app</div></div>')
        bottom = s_top - 80
    avail = bottom - top - 10 - 44
    body_size, body_ok = fit_size(body, box_w, 520, 52, 36, 1.32, False)
    bh = block_height(body, body_size, box_w, 1.32, False)
    t_size, t_ok = fit_size(title, box_w, avail - bh - (48 if body else 0), 124, 56, 1.06, True)
    if not (t_ok and body_ok):
        warnings.append(f"{label}: text does not fit between y={STORY_TOP} and y={STORY_BOTTOM}. "
                        "One idea per frame. Split this frame.")
    parts.insert(0,
        f'<div class="fit" style="left:{pad}px;top:{top}px;width:{box_w}px;'
        f'height:{bottom - top}px;justify-content:center">'
        f'<div class="rule" style="margin-bottom:44px"></div>'
        f'<div class="display" data-shrink style="font-size:{t_size}px;line-height:1.06">{esc(title)}</div>'
        + (f'<div class="body" data-shrink style="font-size:{body_size}px;margin-top:48px">{esc(body)}</div>'
           if body else "")
        + "</div>")
    alt = f"{title.rstrip('.')}. {body}" if body else title
    return page(brand, STORY, "".join(parts)), alt


def grid_preview_html(cover_png, brand):
    """The cover as the 3-column profile grid shows it: a 3:4 tile cut from
    the middle of the 4:5 image. 1350 * 3/4 = 1012.5 wide, so 33.75px goes
    off each side."""
    cw, ch = CAROUSEL
    visible = ch * 3 / 4
    strip = (cw - visible) / 2
    W, H = 1600, 1540
    x0, y0 = 48, 150
    tile_w = 400
    tile_h = tile_w * 4 / 3
    scale = tile_h / ch
    src = esc(cover_png)
    inner = f"""
<div style="position:absolute;left:{x0}px;top:52px;font-size:40px;font-weight:800">Profile grid crop</div>
<div style="position:absolute;left:{x0}px;top:104px;font-size:30px;opacity:.7">The grid shows the middle 3:4 of the cover. Shaded strips ({strip:.2f}px each side) are cut off.</div>
<div style="position:absolute;left:{x0}px;top:{y0}px;width:{cw}px;height:{ch}px;overflow:hidden;box-shadow:0 0 0 2px rgba(0,0,0,.15)">
  <img src="{src}" style="display:block;width:{cw}px;height:{ch}px">
  <div style="position:absolute;left:0;top:0;width:{strip}px;height:{ch}px;background:repeating-linear-gradient(45deg,rgba(220,0,60,.55) 0 10px,rgba(0,0,0,.45) 10px 20px)"></div>
  <div style="position:absolute;right:0;top:0;width:{strip}px;height:{ch}px;background:repeating-linear-gradient(45deg,rgba(220,0,60,.55) 0 10px,rgba(0,0,0,.45) 10px 20px)"></div>
  <div style="position:absolute;left:{strip}px;top:0;width:{visible}px;height:{ch}px;outline:4px dashed rgba(220,0,60,.9);outline-offset:-4px"></div>
  <div style="position:absolute;left:{COVER_SAFE}px;top:{COVER_SAFE}px;right:{COVER_SAFE}px;bottom:{COVER_SAFE}px;border:2px dotted rgba(0,120,255,.7)"></div>
</div>
<div style="position:absolute;left:{x0 + cw + 48}px;top:{y0}px;width:{tile_w}px">
  <div style="font-size:32px;font-weight:700;margin-bottom:20px">In the grid</div>
  <div style="width:{tile_w}px;height:{tile_h:.2f}px;overflow:hidden;position:relative;box-shadow:0 0 0 2px rgba(0,0,0,.15)">
    <img src="{src}" style="position:absolute;width:{cw * scale:.2f}px;height:{tile_h:.2f}px;left:{-strip * scale:.2f}px;top:0">
  </div>
  <div style="font-size:28px;opacity:.7;margin-top:24px;line-height:1.35">Red dashes: the grid tile.<br>Blue dots: the {COVER_SAFE}px safe line the cover text keeps inside.</div>
  <div style="font-size:28px;opacity:.7;margin-top:24px;line-height:1.35">If any word touches the red strips, it will be cut in the grid.</div>
</div>"""
    css = ("*{box-sizing:border-box;margin:0;padding:0}"
           f"html,body{{width:{W}px;height:{H}px;overflow:hidden}}"
           f"body{{background:#EDEDED;color:#111;font-family:{DEFAULT_BRAND['font_body']};position:relative}}")
    return (f"<!doctype html><html><head><meta charset=\"utf-8\"><style>{css}</style></head>"
            f"<body>{inner}</body></html>"), (W, H)


# ---------------------------------------------------------------- chrome

def find_chrome():
    env = os.environ.get("CHROME_PATH")
    if env:
        if Path(env).exists() or shutil.which(env):
            return shutil.which(env) or env
        raise SpecError(f"CHROME_PATH is set to {env} but nothing is there.")
    for c in CHROME_CANDIDATES:
        if Path(c).exists():
            return c
    for name in CHROME_ON_PATH:
        found = shutil.which(name)
        if found:
            return found
    return None


def png_size(path):
    with open(path, "rb") as f:
        head = f.read(24)
    if len(head) < 24 or head[:8] != b"\x89PNG\r\n\x1a\n" or head[12:16] != b"IHDR":
        raise ValueError(f"{path} is not a PNG")
    return struct.unpack(">II", head[16:24])


def screenshot(chrome, html_path, png_path, size):
    w, h = size
    with tempfile.TemporaryDirectory(prefix="ig-render-chrome-") as profile:
        cmd = [chrome, "--headless=new", "--disable-gpu", "--hide-scrollbars",
               "--force-device-scale-factor=1", f"--window-size={w},{h}",
               "--no-first-run", "--no-default-browser-check", "--disable-extensions",
               "--disable-background-networking", "--disable-component-update",
               "--disable-sync", "--no-pings", "--allow-file-access-from-files",
               "--virtual-time-budget=3000", f"--user-data-dir={profile}",
               f"--screenshot={png_path}", Path(html_path).resolve().as_uri()]
        try:
            proc = subprocess.run(cmd, capture_output=True, text=True, timeout=90)
        except subprocess.TimeoutExpired:
            raise RuntimeError(f"Chrome timed out rendering {html_path}")
    if not Path(png_path).exists():
        tail = (proc.stderr or "").strip().splitlines()[-3:]
        raise RuntimeError(f"Chrome wrote no PNG for {html_path}: " + " | ".join(tail))
    got = png_size(png_path)
    if got != (w, h):
        raise RuntimeError(f"{png_path} came out {got[0]}x{got[1]}, expected {w}x{h}. "
                           "This Chrome sizes headless windows differently.")
    return got


def render_all(chrome, jobs, workers=4):
    """jobs: list of (html_path, png_path, size). Runs Chrome in parallel."""
    with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as pool:
        futs = [pool.submit(screenshot, chrome, *j) for j in jobs]
        return [f.result() for f in futs]


# ---------------------------------------------------------------- main

def load_spec(path):
    try:
        spec = json.loads(Path(path).read_text())
    except json.JSONDecodeError as e:
        raise SpecError(f"{path} is not valid JSON: {e}")
    if not isinstance(spec, dict):
        raise SpecError("spec must be a JSON object")
    return spec


def build(spec, out, brand, kind, keep_html, chrome):
    """Writes everything. Returns (written [(name, w, h)], warnings, notes)."""
    warnings, notes = [], []
    out.mkdir(parents=True, exist_ok=True)
    handle = str(spec.get("handle") or brand.get("handle") or "").strip()
    if handle and not handle.startswith("@"):
        handle = "@" + handle

    pages = []   # (html_text, stem, size)
    alts = []
    if kind == "carousel":
        slides = spec.get("slides") or []
        if not isinstance(slides, list) or not slides:
            raise SpecError("carousel spec needs a non-empty \"slides\" list")
        if len(slides) > MAX_SLIDES:
            raise SpecError(f"{len(slides)} slides. Instagram takes {MAX_SLIDES} at most. Cut it down.")
        if len(slides) < MIN_SLIDES:
            warnings.append(f"only {len(slides)} slides. Under {MIN_SLIDES} and the swipe never starts.")
        if not handle:
            warnings.append("no handle set. Add \"handle\" to the spec or brand.json so screenshots travel with your name.")
        for i, s in enumerate(slides):
            if not isinstance(s, dict):
                raise SpecError(f"slide {i + 1} must be an object with title/body")
            doc, alt = carousel_slide_html(s, i, len(slides), brand, handle, warnings)
            pages.append((doc, f"slide-{i + 1:02d}", CAROUSEL))
            alts.append(alt)
    else:
        frames = spec.get("frames") or spec.get("slides") or []
        if not isinstance(frames, list) or not frames:
            raise SpecError("story spec needs a non-empty \"frames\" list")
        if len(frames) > MAX_FRAMES:
            warnings.append(f"{len(frames)} frames. Past {MAX_FRAMES} the last ones play to nobody.")
        for i, f in enumerate(frames):
            if not isinstance(f, dict):
                raise SpecError(f"frame {i + 1} must be an object")
            doc, alt = story_frame_html(f, i, brand, warnings)
            pages.append((doc, f"frame-{i + 1:02d}", STORY))
            alts.append(alt)
            if f.get("note"):
                notes.append(f"frame {i + 1}: shoot {f['note']} (put this card over it, or post it as is)")
            if f.get("sticker"):
                notes.append(f"frame {i + 1}: add the {str(f['sticker']).partition(':')[0].strip()} "
                             "sticker in the Instagram app, on the dashed box")

    html_dir = out if keep_html else Path(tempfile.mkdtemp(prefix="ig-render-html-"))
    try:
        jobs = []
        for doc, stem, size in pages:
            hp = html_dir / f"{stem}.html"
            hp.write_text(doc, encoding="utf-8")
            jobs.append((hp, out / f"{stem}.png", size))
        render_all(chrome, jobs)
        written = [(f"{stem}.png", *size) for _, stem, size in pages]

        if kind == "carousel":
            cover = (out / "slide-01.png").resolve().as_uri()
            doc, size = grid_preview_html(cover, brand)
            hp = html_dir / "grid-preview.html"
            hp.write_text(doc, encoding="utf-8")
            screenshot(chrome, hp, out / "grid-preview.png", size)
            written.append(("grid-preview.png", *size))
    finally:
        if not keep_html:
            shutil.rmtree(html_dir, ignore_errors=True)

    lines = []
    cover_alt = str(spec.get("alt") or "").strip()
    if kind == "carousel":
        if not cover_alt:
            warnings.append("no \"alt\" in the spec. Using slide 1 text as the cover alt text.")
            cover_alt = alts[0]
        lines.append("COVER ALT TEXT (Advanced settings > Accessibility > Write alt text)")
        lines.append(cover_alt)
        lines.append("")
        lines.append("PER SLIDE")
        for i, a in enumerate(alts):
            lines.append(f"Slide {i + 1}: {a}")
    else:
        lines.append("STORY FRAMES (alt text per frame)")
        for i, a in enumerate(alts):
            lines.append(f"Frame {i + 1}: {a}")
    (out / "alt-text.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")
    written.append(("alt-text.txt", None, None))
    return written, warnings, notes


def main(argv=None):
    ap = argparse.ArgumentParser(description="Render approved carousel or story copy to Instagram-sized PNGs.")
    ap.add_argument("spec", help="spec JSON file")
    ap.add_argument("--out", required=True, help="output folder")
    ap.add_argument("--brand", help="brand JSON (default: brand.json in the active account's data folder, then built-in)")
    ap.add_argument("--kind", choices=["carousel", "story"], help="override the spec's kind")
    ap.add_argument("--keep-html", action="store_true", help="keep the per-slide HTML next to the PNGs")
    args = ap.parse_args(argv)

    try:
        spec = load_spec(args.spec)
        kind = args.kind or str(spec.get("kind") or "carousel").lower()
        if kind not in ("carousel", "story"):
            raise SpecError(f"kind must be carousel or story, not {kind!r}")
        slides = spec.get("slides") or []
        if kind == "carousel" and isinstance(slides, list) and len(slides) > MAX_SLIDES:
            raise SpecError(f"{len(slides)} slides. Instagram takes {MAX_SLIDES} at most. Cut it down.")
        brand, source, warnings = load_brand(args.brand)
        chrome = find_chrome()
        if not chrome:
            raise SpecError("No Chrome or Chromium found. Install Google Chrome, or set CHROME_PATH "
                            "to the browser binary.")
        out = Path(args.out).expanduser()
        written, w2, notes = build(spec, out, brand, kind, args.keep_html, chrome)
        warnings += w2
    except SpecError as e:
        print(f"error: {e}", file=sys.stderr)
        return 2
    except RuntimeError as e:
        print(f"error: {e}", file=sys.stderr)
        return 3

    print(f"\n  {kind.upper()}  ·  brand: {source}")
    print(f"  out: {out.resolve()}\n")
    for name, w, h in written:
        print(f"  {name:<20} {w}x{h}" if w else f"  {name}")
    if notes:
        print("\n  TO DO IN THE APP")
        for n in notes:
            print(f"  - {n}")
    if warnings:
        print("\n  WARNINGS")
        for wmsg in warnings:
            print(f"  ! {wmsg}")
    else:
        print("\n  no warnings")
    if kind == "carousel":
        print("\n  Upload order = file order. Nothing was uploaded.")
    else:
        print("\n  Post in file order. Nothing was posted.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
