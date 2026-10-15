---
name: ig-trends
description: >-
  Find what is going viral right now in the user's country and in their niche,
  then blend the two into reel ideas: the trend brings the timing, the niche
  brings the substance. Scores each idea on momentum, niche fit, proof, format,
  brand safety and time left. Use when the user says "what's going viral",
  "what's trending in <country>", "trends in my niche", "viral right now",
  "what should I jump on", "virality blast", or wants timely ideas this week.
---

# ig-trends

/ig-viral looks inside the niche. This skill also looks outside it, at what
the whole country is talking about this week, and builds a bridge between the
two. A trend alone gets views from people who will never follow. A niche post
alone gets no lift. The bridge gets both: the trend is the hook, the niche is
the reason to follow.

**Account context.** Before recommending anything, read `account.md` in the
active account's data folder, or run `python3 ~/.claude/skills/ig-scan/scan.py context`.
It has this account's niche, size tier, audience language, cadence and what
already performs for it. Fit the advice to that. If it is missing, suggest
/ig-scan once and carry on.

Said once, plainly: **nobody can guarantee a reel goes viral.** This finds
what is moving and ranks bets. The user still has to make a good reel, and
most good reels still do not blow up.

One tool lives in this folder:

```bash
python3 trends.py add ...      # log a trend you saw
python3 trends.py blend ...    # rank the bridges, write trends.md
python3 trends.py list         # what is logged
python3 trends.py prune        # drop dead trends
```

Data lives in `$DATA`: `$IG_DATA_DIR` if set, else the active account folder
(`$IG_HOME/accounts/<handle>/`, when `$IG_HOME/active-account` names one and
the folder exists), else `$IG_HOME` (default `~/.claude/instagram`).

## Browsing

All browsing goes through **/ig-kweo**. Read its rules before opening
Instagram. The short version: read only, human speed, a handful of pages, the
user present, never log in for them, never like, follow, comment, save or send,
and every `browser_run_task` goal ends with "Read and report only."

Public sources below are fine at normal pace with whatever browser this
session has, or WebFetch for the ones marked so.

## Step 1: inputs

Get three things. Read `$DATA/voice.md` first and only ask for what is not
there.

1. **Region.** A country code: IN, US, GB, AE. From voice.md, the account, or
   ask.
2. **Niche.** In a few words: "freelance contracts", "home workouts for
   new mums".
3. **Languages** the user posts in. A Hindi trend is no use to an English-only
   account, and the reverse.

Also pull **Proof I can use** from voice.md. `trends.py blend` reads it on its
own. If it is empty, every idea comes back with `{{your number}}` in it, and
that is correct.

## Step 2: region-wide, what the whole country is on

Spend about 15 minutes. For each item worth keeping, log it:

```bash
python3 trends.py add --source google --region IN --kind topic \
  --name "ITR filing deadline" --rank 3 --growth "+400%" \
  --first-seen 2026-10-13 --url "https://trends.google.com/trending?geo=IN"
```

`--kind` is one of `topic` (a news thing or search spike), `hashtag`,
`song`, `format` (a reusable shape: "POV: you are the client"), `meme`.
`--first-seen` matters most. It drives the decay. If unsure, use the date the
source says it started, not today.

Sources, verified 2026-10-15. Swap `IN` for the user's country.

| source | URL | login | how |
| --- | --- | --- | --- |
| Google Trends, trending now, 24h | `https://trends.google.com/trending?geo=IN&hours=24` | no | browser. Shows volume, growth %, start time. |
| Google Trends, past 7 days | `https://trends.google.com/trending?geo=IN&hours=168` | no | browser. Better for things still rising. |
| Google Trends RSS | `https://trends.google.com/trending/rss?geo=IN` | no | WebFetch works. Titles and approx traffic only. |
| Google Trends, related queries | `https://trends.google.com/explore?geo=IN&date=now%207-d&q=<niche term>` | no | browser. "Rising" queries for the niche. |
| TikTok Creative Center, hashtags | `https://ads.tiktok.com/business/creativecenter/inspiration/popular/hashtag/pc/en` | partial | browser. Set country and 7 days. Newer route: `https://ads.tiktok.com/creative/creativeCenter/trends/hashtag?countryCode=US&period=7` |
| TikTok Creative Center, songs | `https://ads.tiktok.com/business/creativecenter/inspiration/popular/music/pc/en` | partial | browser. "Breakout" songs are the leading indicator for Reels audio. |
| TikTok Creative Center, creators / videos | `.../inspiration/popular/creator/pc/en`, `.../inspiration/popular/pc/en` (newer: `/creative/creativeCenter/trends/video?countryCode=US&period=7`) | partial | browser. |
| YouTube Charts | `https://charts.youtube.com/charts/TopShortsSongs/in/weekly` | no | browser (it is a script page, WebFetch gets only the title). Top Shorts songs by country. |
| YouTube Shorts | `https://www.youtube.com/shorts` | optional | kweo. The feed is personalised, so treat it as a sample, not a chart. |
| Google News, top stories | `https://news.google.com/rss?hl=en-IN&gl=IN&ceid=IN:en` | no | WebFetch works. Change `hl`, `gl`, `ceid` per country and language. |
| Instagram Reels tab | `https://www.instagram.com/reels/` | yes | kweo, the user's own session, read only. Scroll a few, note audio and format. |
| Instagram Explore | `https://www.instagram.com/explore/` | yes | kweo, read only. Personalised too. |

Notes on what changed or did not load:

- **YouTube's Trending page is gone.** It was retired in July 2025.
  `youtube.com/feed/trending` still returns a page, but it is no longer a
  country chart. Use YouTube Charts and the
  Shorts feed instead. Creators also get an "Inspiration" tab in YouTube
  Studio.
- **TikTok Creative Center did not answer from this machine** (connection
  timed out), so the URLs above come from TikTok's documented routes, not a
  live check. Basic top lists show without login. Deeper filters and full
  lists ask for a free TikTok for Business login, which the user does
  themselves. TikTok has been blocked in India since 2020, so expect no
  India data there. For an IN account, skip it and lean on Google Trends, YouTube Charts and the
  Reels tab.
- **Instagram pages need the user's login.** Never anyone else's. Never log in
  for them.
- **Reels tab, Explore and the Shorts feed are personalised.** They show what
  the user's account is shown, not what the country is watching. Good for
  audio and format, weak as a chart. Rank them lower.

Instagram's own trending audio: inside the app, the audio page shows an arrow
next to trending tracks. If the user reads it out, log it as `--kind song
--source instagram`.

## Step 3: the niche, what is working in it

Run the /ig-viral method for the niche. Accounts within about 10x of the
user's size, outlier multiple over each account's own median, `swipe.py` to
rank and name the formulas. If `$DATA/swipe.md` is under a month old, read it
instead of redoing it.

Log the 3 to 6 strongest niche patterns as niche angles:

```bash
python3 trends.py add --scope niche --source instagram --region IN \
  --kind format --name "reading a bad clause out loud with a red pen" \
  --niche-match 3
```

Add niche hashtags from TikTok Creative Center (industry filter) and rising
related queries from Google Trends the same way, `--scope niche`.

For every region trend, also set `--niche-match 0-3` when you can judge it:

| score | means |
| --- | --- |
| 3 | the trend is about the niche, or bends to it in one step |
| 2 | a clear bridge exists and does not feel forced |
| 1 | a stretch. The audience would see the seam. |
| 0 | no honest bridge. Leave it alone. |

Without it the script guesses from shared words and marks the guess with `?`.

## Step 4: blend

```bash
python3 trends.py blend --niche "freelance contracts" --region IN --top 10
```

It pairs every live region trend with every niche angle and scores the pair:

- **Momentum** (40%). Rank and growth, decayed by age. Each kind has a
  half-life: memes and news topics 4 days, hashtags 7, songs 18, formats 30.
  Phase is rising, peaking or fading.
- **Niche fit** (30%). The 0-3 above.
- **Angle strength** (10%). How strong the niche pattern is.
- **Proof** (10%). Whether voice.md has a real number that fits.
- **Format fit** (10%). How naturally the kind becomes a reel.
- **Brand safety.** Deaths, disasters, attacks and the like are **excluded**
  and listed apart. Politics, religion, courts, fights between countries are
  **flagged** and docked 30%. Anything from news is flagged until a human
  reads it. Override with `--safety ok|flag|exclude` on `add` when the words
  lie, both ways.
- **Ship by.** The date the trend passes one half-life, or 2 days if it
  already has. After that, skip it.

It prints a VIRALITY BLAST board and writes `$DATA/trends.md`, which /ig-plan
and /ig-reel read. Run `trends.py prune` first each time. It drops anything
past its lifespan (memes and topics 10 days, hashtags 21, songs 35,
formats 75).

The script ranks. Claude then reads the top 10 and writes each bridge as a
sentence: what the trend is, what the niche angle is, and why someone who
came for the trend would stay for the niche. If that sentence will not come,
the bridge is fake. Drop it, whatever the score.

**Brand safety is a judgement, not a word list.** Read every flagged item
before using it. Never put a tragedy in a hook. Never make a joke out of
someone getting hurt. If in doubt, leave it out and say why.

## Step 5: hand off the top 3

For each of the top 3, give /ig-reel:

- the bridge sentence
- the hook formula id from the board (a starting point; /ig-reel can change it)
- the proof line, or `{{your number}}`
- the ship-by date
- a **sound slot**: the song if the trend is one, else `{{pick with /ig-audio}}`

## Output

```
VIRALITY BLAST  ·  freelance contracts  ·  region IN  ·  2026-10-15
==============================================================================
  1.  84  Diwali bonus  (topic, google)
        momentum  88 rising   day 1, ship by 2026-10-18   niche fit 3/3   format fit 2/3
        bridge: Diwali bonus  ->  reading a bad clause out loud with a red pen
        hook formula #9 The Steal   proof: Recovered Rs 40,000 for a client
        sound: {{pick with /ig-audio}}
  ...
LEFT OUT, NOT SAFE TO RIDE
  Stadium stampede  (stampede)

TOP 3 FOR /ig-reel
  1. "Your client's Diwali bonus is not your invoice. Here is the clause."
     #9 The Steal, ship by Sat. Sound: pick with /ig-audio.
  ...

Sources read: Google Trends IN 24h and 7d, Google News IN, Reels tab (8 reels).
Not reached: TikTok Creative Center (not available in IN).
This ranks bets. Nobody can promise a reel goes viral.
```

Always list which sources were read and which were not. A board built from
two sources is a thinner bet than one built from five, and the user should
know which one they are holding.

Nothing is posted, liked, followed, saved or messaged by this skill. It reads.
