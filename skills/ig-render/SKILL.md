---
name: ig-render
description: >-
  Turn approved carousel or story copy into the PNG files Instagram takes -
  1080x1350 carousel slides with a grid-crop preview, 1080x1920 story frames
  with sticker placeholders, and the alt text to paste. Use when the user says
  "make the slides", "render the carousel", "make the images", "story images",
  "export the carousel", or has approved copy from /ig-carousel or /ig-story
  and needs the files.
---

# ig-render

/ig-carousel and /ig-story write the words. This makes the pictures. Instagram
does not take PDFs, so every slide comes out as its own PNG at the exact size
the app wants. Headless Chrome draws each one from HTML, then the script reads
the PNG header to check the size.

Nothing is uploaded. The user posts it.

## When to run it

**After the user approves the copy.** Not before. Rendering copy that is still
changing wastes a round and makes people attached to bad slides. If the copy
has not been through `/ig-human` yet, do that first.

## Steps

1. **Write the spec** from the approved copy. Use the user's words exactly. Do
   not tighten or rewrite them here. Save it next to where the files will go.

   Carousel:

   ```json
   {"kind": "carousel", "handle": "@name",
    "alt": "Cover slide reading: The $18,000 clause. One line I now put in every contract.",
    "slides": [
      {"role": "cover", "title": "THE $18,000 CLAUSE", "body": "One line I now put in every contract."},
      {"title": "What it says", "body": "Payment on delivery, not on approval."},
      {"role": "recap", "title": "The four lines", "list": ["...", "..."]},
      {"role": "cta", "title": "Comment CONTRACT", "body": "I will send you the full clause."}
    ]}
   ```

   Slide 1 is the cover unless told otherwise. A slide with `list` is a recap.
   Mark the last slide `"role": "cta"` to centre it.

   Story:

   ```json
   {"kind": "story", "frames": [
     {"title": "Third refund request this year.", "body": "Same reason.", "note": "selfie, walking"},
     {"title": "Burned by a late approval?", "sticker": "poll: Yes / Not yet"}
   ]}
   ```

   `sticker` draws a dashed box that says where to put it. `note` is what to
   shoot under the card. Both show up in the to-do list the script prints.

2. **Render.**

   ```bash
   python3 ~/.claude/skills/ig-render/render.py spec.json --out ./carousel-clause
   python3 ~/.claude/skills/ig-render/render.py story.json --out ./story-tue
   ```

   Options: `--brand brand.json`, `--kind carousel|story`, `--keep-html`.

3. **Look at the files before handing them over.** Use Read on the PNGs. At a
   minimum read the cover, one body slide and `grid-preview.png`. For stories,
   read the sticker frame. Check for:
   - words cut off or touching an edge
   - a title so small it no longer reads at thumbnail size
   - anything important inside the red strips on the grid preview

   If something is wrong, fix the copy in the spec (shorter title, split the
   slide) and render again. Do not hand over a slide you have not looked at.

4. **Hand over** the folder path, the file list, the warnings, and the alt text.

## What it makes

| kind | files | size |
| --- | --- | --- |
| carousel | `slide-01.png` ... | 1080x1350 (4:5) |
| carousel | `grid-preview.png` | the cover with the 3:4 profile-grid crop shaded |
| story | `frame-01.png` ... | 1080x1920 (9:16) |
| both | `alt-text.txt` | cover alt text plus one line per slide |

Built in, so you do not have to ask for it:

- Slide numbers (3/8) on every slide but the cover.
- The handle small in the bottom corner of every carousel slide.
- Cover text stays clear of the outer 120px.
- Story text stays between y=250 and y=1600, clear of the profile row and the
  reply bar.
- No type under 32px. Titles shrink to fit and never overflow.
- One accent colour.

## Warnings and what to do

| warning | fix |
| --- | --- |
| title shrank / over 6 or 7 words | cut words, or split the slide in two |
| body over 25 words | split the slide |
| under 5 slides | the swipe never starts. Add a stake or recap slide |
| more than 20 slides | an error. Instagram's cap is 20 |
| contrast under 4.5:1 | change `fg` or `bg` in the brand file |

## Brand

The script looks for a brand in this order: `--brand file`, then
`brand.json` in the active account's data folder (`python3
~/.claude/skills/ig-account/account.py path`, see /ig-account; defaults to
`~/IGStudio`), then a plain built-in look. Copy `brand.example.json`
there to start one. Each account keeps its own brand.

```json
{"bg": "#F6F3EE", "fg": "#16181D", "accent": "#E4572E",
 "font_display": "Avenir Next", "font_body": "Helvetica Neue", "handle": "@you"}
```

Fonts must already be on the machine. Nothing is downloaded. If the project
has a brand skill or design system, copy its colours in here. Do not invent a
palette.

## Telling the user

```
RENDERED  ·  8 slides  ·  ./carousel-clause

slide-01.png ... slide-08.png   1080x1350
grid-preview.png                cover is safe in the grid crop
alt-text.txt                    paste the first line into the cover's alt text

Upload in file order: slide-01 first.
Alt text: Advanced settings > Accessibility > Write alt text.
```

For stories, add: stickers go on in the Instagram app, on the dashed box. The
box is a guide. Drag the sticker over it and size it to cover the dashes.

Chrome is needed. Set `CHROME_PATH` if it lives somewhere unusual. If none is
found, the script says so and stops.
