---
name: ig-viral
description: >-
  Go and find the reels that are actually working right now in the user's
  niche, rank them by how far each beat its own account, name the hook formula
  each one used, and turn that into a swipe file they can shoot from. Use when
  the user says "find viral videos", "what's working right now", "what are
  people posting in my niche", "reverse engineer this account", "build me a
  swipe file", "why is this reel doing numbers", or asks what to make next and
  has no evidence to answer with.
---

# ig-viral

The research skill. Everything else in this pack writes; this one goes and
looks. Run it monthly, not daily. Formulas last a season.

**Account context.** Before recommending anything, read `account.md` in the
active account's data folder, or run `python3 ~/.claude/skills/ig-scan/scan.py context`.
It has this account's niche, size tier, audience language, cadence and what
already performs for it. Fit the advice to that. If it is missing, suggest
/ig-scan once and carry on.

One tool lives in this folder and it runs:

```bash
DATA=$(python3 ~/.claude/skills/ig-account/account.py path)
python3 swipe.py captured.tsv --out "$DATA/swipe.md"     # also writes $DATA/viral.json
```

`DATA` is the active account's data folder (see /ig-account; defaults to
`~/IGStudio`).

**This is where the pack's posts come from.** /ig Autopilot, /ig-plan and
/ig-reel copy the reels in `viral.json`: their hook shape, structure, pace and
tone. The user's own past posts are not the template; they are what did not
travel.

## The one idea that makes this worth doing

**Raw views are not evidence.** An account with two million followers doing
400,000 views had a quiet Tuesday. An account with four thousand followers
doing 400,000 views found something, and that something is copyable.

So everything here ranks on the **outlier multiple**: views divided by that
account's own recent median. Anything above 3x is a signal. Anything below 1.5x
is that account's normal day and it teaches you nothing, no matter how big the
number looks.

Collect accounts **within about 10x of the user's own size**. A formula that
works at 2M followers often works because it is at 2M followers.

## Step 1: pick the accounts

Ask the user for 6 to 12 accounts, or propose them and get approval:

- **4 direct** - same niche, same offer, slightly ahead.
- **4 adjacent** - different niche, same audience. This is where formats get
  borrowed from before anybody in the niche has them.
- **2 to 4 outsized** - much bigger accounts, for format only, never for
  cadence or tone.

Also ask them to open their own **Saved collection**. It is the fastest and
most relevant corpus that exists and it is already filtered by their taste.

## Step 2: go and look

Use whatever browsing tool this session actually has: an in-app browser, a
browser extension connected to the user's own Chrome, or a computer-use tool.
Browsing by hand is fine at this volume. Ten accounts, a dozen reels each, is
small enough to read.

If the user wants view counts at scale, there is an official way. Since June
2025 Meta's Business Discovery API returns other professional accounts' Reel
`view_count`. It needs the Instagram API with Facebook Login and a Facebook
Page linked to the user's professional account. That is the compliant route.
Never scrape.

**Rules that are not negotiable:**

- **Never log into Instagram on the user's behalf and never ask for a
  password.** If a page needs a login, the user is the one who is already
  logged in. Drive their browser with them present, or ask them to paste.
- **This is reading, not scraping.** Ten accounts, a dozen reels each, at human
  speed. Automated collection at volume violates Instagram's Terms of Use and
  gets accounts action-blocked. Do not build a crawler, do not use a scraping
  service, and do not loop this in the background.
- **Copy the formula, never the video.** The hook shape, the structure, the
  length, the pattern of cuts, the tone and energy. Not their script word for
  word, not their footage, not their edit. Attribute every row in the swipe
  file to the account it came from.

**What to capture per reel**, in the creator's own words:

| field | notes |
| --- | --- |
| account | handle |
| followers | from the profile |
| median | eyeball the last 12 reels and take the middle view count |
| views | this reel |
| hook | the first line, spoken or on screen, verbatim including bad grammar |
| on_screen | the first text card, if different |
| length | seconds |
| cta | what they asked for at the end |
| url | the reel's link, so the user can watch the original |
| structure | the beats in one line: "hook, 3 jump-cut fails, the fix, loop line" |
| sound | the audio it uses, if shown |
| caption | the caption's first line |

Median is the important one. Without it you are back to ranking by follower
count, which is the thing this skill exists to stop.

**When Instagram will not show you enough:** the same hook grammar runs on
YouTube Shorts, where view counts and transcripts are public and no login is
involved. It is a legitimate second corpus, and the spoken hook is easier to
get:

```bash
# view counts for a channel's shorts
python3 -m yt_dlp --flat-playlist --playlist-end 40 -J \
  "https://www.youtube.com/@HANDLE/shorts" > channel.json

# the spoken first line of one short, from its auto-captions
python3 -m yt_dlp --skip-download --write-auto-subs --sub-langs "en.*" \
  --sub-format json3 -o hook "https://www.youtube.com/watch?v=VIDEO_ID"
```

Take every caption word with a timestamp under 3.0 seconds. That is the hook,
as said, not as written.

## Step 3: rank it

Fill a tab-separated file with a header row and run the script:

```
account	followers	median	views	hook	url	length	structure
@someone	48000	11000	412000	nobody tells you your first 30 reels are supposed to flop	https://www.instagram.com/reel/AbC/	21	hook, 3 quick fails, the fix, loop line
```

Only `views` and `hook` are required. Leave a cell empty rather than guess it.

```bash
DATA=$(python3 ~/.claude/skills/ig-account/account.py path)
python3 swipe.py captured.tsv --out "$DATA/swipe.md"
```

It computes the outlier multiple, names the hook formula using the same 26
formulas `/ig-reel` writes from, scores each hook with `hookscore.py`, and
prints what separates the top third from the bottom third.

## Step 4: say what it means, carefully

Report three things and no more:

1. **Which formulas over-index** in the top third, with counts. Two formulas
   appearing four times each across six accounts is a finding. One appearing
   twice is not.
2. **What the top third have in common structurally** that the bottom third do
   not: hook length, whether the payoff is visual, whether the first frame
   moves, where the ask is.
3. **The unclassified rows.** Every hook the classifier could not name is
   either noise or a formula that is not in `hooks.json` yet. Read them by
   hand. This is the most valuable column in the output and it is the reason
   the script prints the count.

Then state the sample size and the confidence in plain words. Forty reels
across six accounts supports a claim. Twelve does not, and saying so is the
difference between research and horoscopes.

## Step 5: turn it into something to shoot

For the top three formulas, write **the user's version**: their own story,
their own number, in the shape that is working. Hand each one to `/ig-reel`
with the formula id already chosen.

Never hand back "make a reel like this one". Hand back a hook line they could
say tomorrow.

## Output

```
SWIPE  ·  38 reels  ·  7 accounts  ·  baseline: account median

OUTLIERS (above 3x)
  38.4x  hook 86  #3  Nobody Tells You   @acct_a    412,000  (median 10,700)
  11.2x  hook 79  #9  The Steal          @acct_c    180,000  (median 16,100)
  ...

WHAT IS OVER-INDEXING
  #3 Nobody Tells You   x5 in the top third, 0 in the bottom
  #2 Negative Command   x4
  median hook length    8 words up top, 19 at the bottom

UNCLASSIFIED (6)
  Two of these are the same shape and it is not in hooks.json: a hook that
  opens on someone else's comment read out loud. Worth adding.

YOUR VERSION
  #3  "Nobody tells you the first 20 proposals are supposed to lose."
  ...
```

Write the swipe file to `swipe.md` in the active account's data folder.
`/ig-reel` and `/ig-plan` both read it, which is the point: after this runs once, the rest of
the pack is working from the user's own evidence instead of from defaults.

## Autopilot (IG Studio, /ig Autopilot)

When /ig Autopilot calls this, ask nothing and approve nothing: pick the
accounts yourself, read, rank, write. About 10 minutes.

1. **Accounts.** 8 to 12: direct (same niche and audience), adjacent (same
   audience, another niche) and 2 big ones for format. Find them from
   `swipe.md` and `engaged.md` if they exist, the niche's hashtag pages, and a
   web search like "viral <niche> reels <region> <month year>". Bigger than
   the user is fine here: this is for the format, not the cadence.
2. **Read them, fast.** With kweo, start the `ig-kweo-reader` agent with
   `model: "haiku"`, one account per job and one job at a time, with the
   prompt: `reels job: @<handle>, 10 reels, write $KIT/reader-<handle>.json`
   (`KIT` is `$DATA/.studio/kit/<week>/`). Each job takes a few minutes.
   Read 5 to 7 accounts, and stop starting new ones after 15 minutes.
   Instagram's web pages show likes, not views, on other people's reels, so
   the ranking is likes against the account's own median likes. That is
   fine and the files say so.
   Without kweo: web search and public pages only, and YouTube Shorts with
   `yt_dlp` if it is installed (`source` youtube), into `captured.tsv`.
3. **Rank.** `swipe.py --reader $KIT/reader-*.json --out "$DATA/swipe.md"`
   (or `swipe.py $KIT/captured.tsv --out ...` for the TSV). It works out each
   account's median itself and writes `viral.json` with an id per reel (V01
   is the biggest outlier). The hook is the caption's first line unless you
   saw the spoken line or on-screen text. Aim for 30+ reels across 5+
   accounts; with fewer, say so in the week's assumptions.
4. **Never invent a row.** Views and a baseline you did not see on a page
   mean the reel is left out. A short honest list beats a long made-up one.

Nothing is posted, followed, liked or messaged by this skill. It reads.
