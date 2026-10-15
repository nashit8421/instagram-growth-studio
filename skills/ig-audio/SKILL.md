---
name: ig-audio
description: >-
  Pick the song or sound for a Reel - what is trending right now, whether the
  user's account can actually use it, and whether it fits the reel's mood and
  cut pace - then say exactly how to use it. Use when the user asks "which
  song should I use", "trending audio", "trending sounds", "what music for
  this reel", "best song for reach", "add music", or has a REEL READY block
  from /ig-reel and needs a sound.
---

# ig-audio

Picks the sound for one Reel and says how to use it.

**Account context.** Before recommending anything, read `account.md` in the
active account's data folder, or run `python3 ~/.claude/skills/ig-scan/scan.py context`.
It has this account's niche, size tier, audience language, cadence and what
already performs for it. Fit the advice to that. If it is missing, suggest
/ig-scan once and carry on.

One tool lives in this folder and it runs:

```bash
python3 audio.py add --name "..." --artist "..." --source instagram --region IN \
    --reels-count 8K --trend rising --bpm 104 --mood upbeat --business-ok unknown
python3 audio.py suggest --reel-length 28 --mood upbeat --account creator --top 5
python3 audio.py suggest --reel-length 28 --voiceover yes --script script.txt
python3 audio.py list
python3 audio.py prune --older-than 28
```

## Say this first, every time

Audio is one factor among many. The hook, the first two seconds and how much
of the reel people watch decide far more. A good sound gives a reel a better
start. It does not make it go viral, and nothing here promises that. Never
tell the user a sound "will" boost reach. Say it "gives it a better shot".

## Where the list lives

`$DATA/sounds.csv`. `$DATA` is `$IG_DATA_DIR` if set. Otherwise, if
`$IG_HOME/active-account` holds a handle and `$IG_HOME/accounts/<handle>/`
exists, that folder. Otherwise `$IG_HOME` (default `~/.claude/instagram`).

Columns: `name, artist, source, region, reels_count, first_seen, last_seen,
trend, bpm, mood, business_ok, url, notes`, plus `prev_reels_count, prev_seen`
at the end so growth between two sightings survives. Empty cell means unknown.

## Step 1: get the reel

If there is a `REEL READY` block from `/ig-reel` in the conversation, take
the length from it and save the script to a file for `--script`. Otherwise
ask one batched question:

- How long is the reel, roughly?
- Is your voice the content (talking head, voiceover), or is it music-led?
- What should it feel like: upbeat, calm, dramatic, funny, emotional, lofi?
- **Business or creator account?** (Settings, Account type and tools.) This
  decides which music they can use at all. Ask, never guess.
- Which country is most of the audience in?

## Step 2: refresh what is trending

Trends move in days. If `audio.py list` shows nothing seen in the last week,
refresh before suggesting. Browse through **`/ig-kweo`**: kweo MCP tools first
(`mcp__kweo__browser_new_tab`, `mcp__kweo__browser_navigate`,
`mcp__kweo__browser_read`, `mcp__kweo__browser_run_task`), then Claude in
Chrome, then WebSearch/WebFetch for public pages, then ask the user. Follow
its Instagram rules exactly: **read only**. Never like, follow, comment, post,
save or use a sound. Human speed. The user is present.

**Instagram (the source that matters).** The audio picker is in the app only.
The web cannot read it. So:

1. Ask the user to open the Reels editor, tap the music note, open
   **Trending**, and screenshot the list. Claude reads the screenshot. A sound
   with a small **upward arrow** next to it is one Instagram marks as trending.
2. Ask them to tap 2 or 3 of the most promising sounds and screenshot each
   **sound page**. It shows how many reels use it. That number is
   `--reels-count`.
3. Professional accounts may also have **Professional Dashboard, Trending
   audio**: the top sounds used in the last few days. Third-party guides say
   it rolled out US-first, so it may not be there. If it is, a screenshot of
   it is the best single source.
4. **Business accounts: the picker itself is the eligibility test.** If a
   sound shows up when they search it in their own picker, they can use it
   (`--business-ok yes`). If it does not, `--business-ok no`. A sound they
   only saw on someone else's reel is `unknown` until checked.

**TikTok Creative Center (leading indicator, public).** Songs often trend on
TikTok before Reels. Third-party guides put the lag at days, not weeks; no
platform has published a number, so treat it as a hint, not a rule. Open
`https://ads.tiktok.com/business/creativecenter/inspiration/popular/music/pc/en`
with kweo, set the country to the audience's and the period to 7 days, and
read the top 20 with their rank. Use a `browser_run_task` goal phrased as
reading, ending with "Read and report only." Add them with `--source tiktok`.
They still have to be found in the Instagram picker before they are usable;
the tool flags every TikTok sound for that.

**Instagram Audio API (optional, not required).** Meta's `GET /ig_audio`
(Instagram API with Facebook Login, a Business or Creator account linked to a
Facebook Page, `instagram_basic` + `instagram_content_publish`) returns
trending music or original sounds when called without a search query, and can
search by keyword. It only returns audio cleared for third-party use, so its
list is not the same as the app's. Mention it to users who already have a
Meta app. Never set one up just for this skill.

## Step 3: add what was found

One `add` per sound. Re-adding a sound with a new reel count records the
growth since the last sighting. If `--trend` is left off on a re-add, growth
sets it (5%+ a day rising, flat or down fading, between that peaking).

```bash
python3 audio.py add --name "Golden Hour Loop" --artist "Mira K" --source instagram \
    --region IN --reels-count 9.8K --bpm 104 --mood upbeat --business-ok no
```

Only fill `--bpm` and `--mood` if you actually know them (the user says, or
the sound is well known). A guessed BPM is worse than none. Never invent a
reel count.

## Step 4: rank

```bash
python3 audio.py suggest --reel-length 28 --mood upbeat --account business \
    --voiceover yes --script script.txt --region IN --top 5
```

What it weighs, and every threshold is a named constant at the top of
`audio.py` with a comment, because they are rules of thumb, not Instagram
facts:

| factor | weight | rule of thumb |
| --- | --- | --- |
| momentum | 40% | rising beats peaking beats fading. Instagram reel count sweet spot about 1k to 50k: enough proof, not yet crowded. Under 300 is unproven, past 200k is saturated. TikTok counts run on a 10x scale. Growth per day between sightings, 10%+ is hot. |
| freshness | 20% | full marks for the first week after first seen, half by three weeks, then halves weekly. A sighting older than 7 days is flagged: re-check it. |
| mood | 20% | exact match, near neighbour (calm and lofi), or a mismatch. |
| BPM vs cuts | 20% | the song's tempo band against the cut pace. With `--script`, `/ig-reel`'s `beats.py` times each beat and the tool checks whether one beat lands on 2, 4, 8 or 16 beats of the song. |

Then the multipliers. **Business account:** `business_ok=no` is removed and
listed as left out; `unknown` is kept at 0.7x and flagged "search it in your
picker". **Other region:** 0.8x.

## Step 5: present the top 3

For each pick, in short sentences:

- **Why**, from the tool's `why` line. Trend, reel count, growth, age, mood,
  tempo.
- **Flags**, verbatim. Never drop "business use unknown".
- **How to use it.** Land the drop on the payoff, not the hook. The hook has
  to read on frame 1 on its own. With a script, the tool names the payoff beat
  and its timecode and the cut length that sits on the song's grid.
- **Volume.** Music-led: full. Voiceover: music at **10-20%**, voice at 100%.
  The voice comes first. If a word is hard to hear, the music is too loud.
- **"Add it inside Instagram when you post"**, from the audio picker. That
  keeps it licensed and puts the reel on the sound's page, where people
  browsing that sound find it.

**When the voice is the content**, always offer the original-audio option
too. Post with their own voice as the sound and rename it in the app before
posting. If others reuse it, their reels show on the sound page credited to
the user, which links back to them. A trending track under the voice is still
possible; tell them to check the audio label on the preview to see whose
sound page the reel joins.

Fit with `/ig-reel`'s rule: **do not build a reel around a trending sound the
account cannot use.** If the only good fit is `business_ok=no` on a business
account, say so and pick the best usable one, or recommend original audio.

## Rules

- **Never download, rip, record or re-upload audio.** No yt-dlp on songs, no
  screen recording a track, no "add it in CapCut and upload". Music is added in
  the Instagram app at posting time. Anything else risks the reel being muted
  or blocked and is not licensed.
- **Never suggest switching account type to get around the music rules.**
  Business to creator changes what the picker shows; it does not make a
  promotional post non-commercial. If the user asks, say that plainly and let
  them decide.
- **Never promise reach.** Audio is one input.
- **Never invent data.** No made-up reel counts, BPMs or trend states.
- **Read only on Instagram**, per `/ig-kweo`.
- `prune --older-than 28` once a month. A sound nobody has seen in four weeks
  is history.

## Verified facts (checked October 2026)

- **Business accounts and music.** Instagram's Help Center: the music library
  is "intended for personal, non-commercial use", "certain business accounts
  and certain types of posts do not have access to the library", and those
  accounts "may be able to use Meta's Sound Collection" (royalty-free, cleared
  for commercial use). Creator accounts generally keep the full library.
  Availability also varies by country.
  https://help.instagram.com/402084904469945 ,
  Meta Music Guidelines: https://www.facebook.com/legal/music_guidelines
  (commercial use without a licence is restricted; short clips recommended;
  music as a "listening experience" can be blocked). No 2026 change found.
  Secondary: https://usethirdchair.com/blog/instagram-sound-library-rules-for-creators-and-brands
- **Where trending audio shows.** Audio picker Trending section and the upward
  arrow: https://www.veed.io/learn/trending-audio-on-instagram . Professional
  Dashboard, Trending audio (top sounds of the last few days, US-first rollout):
  https://www.websitebuilderexpert.com/news/find-trending-instagram-audios/ ,
  https://napoleoncat.com/blog/how-to-find-trending-audio-on-instagram/ . The
  sound page shows how many reels use it:
  https://maketecheasier.com/how-to-find-trending-audio-instagram . These are
  third-party guides; Instagram does not document the arrow threshold.
- **TikTok Creative Center songs**, filterable by country and period, popular
  vs breakout, business-approved filter:
  https://ads.tiktok.com/business/creativecenter/inspiration/popular/music/pc/en ,
  https://www.socialmediatoday.com/news/tiktok-adds-insights-on-the-latest-trending-songs-by-region-to-its-trend-di/617331 ,
  https://www.shopify.com/blog/how-to-find-trending-sounds-tiktok .
  TikTok-leads-Reels: https://www.kapwing.com/resources/trending-reels-songs/
  (pattern, no measured lag).
- **Instagram Audio API** (updated June 2026, Facebook Login only, trending by
  default, third-party-cleared audio only):
  https://developers.facebook.com/docs/instagram-platform/content-publishing/audio-api/ ,
  changelog https://developers.facebook.com/documentation/instagram-platform/changelog
- **Original audio** is attributed to the creator and reels using it appear
  on its audio page: https://help.instagram.com/329208821595430 . Renaming it
  before posting: https://publer.com/help/en/article/how-to-rename-the-original-audio-for-reels-1aqq2g1

## Example

```
/ig-audio  (after a REEL READY: 28s, voiceover, business account, India)
```

```
AUDIO PICKS  ·  28s reel  ·  business account  ·  mood upbeat  ·  voiceover
script: 9 beats, ~27.6s, 3.1s a beat (medium cuts, timed with beats.py)
left out 2 not cleared for business accounts: Golden Hour Loop - Mira K, ...

1. Tiny Victory - Meta Sound Collection   score 86
   why:  rising; 1,500 reels, proven and not crowded; first seen 5 days ago; ...
   - Land the drop on the payoff, beat 8 at about 0:20.
   - Volume: music at 10-20%, voice at 100%.

ORIGINAL AUDIO
   Your voice is the content, so original audio is a real option. ...
```

Run `examples/demo.sh` to see the full output on 10 made-up sounds in a
throwaway folder.

## Tests

```bash
python3 -m unittest discover -s tests
```

Temp dirs only. Never touches `~/.claude/instagram` or `~/.claude/skills`.
