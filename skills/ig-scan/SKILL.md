---
name: ig-scan
description: >-
  Read the Instagram account the user is growing (their own, or a client's
  they manage), go through its posts, and write an account profile - niche,
  size, cadence, what performs, voice - that every other ig- skill uses as
  context. Use when the user says "scan my account", "analyze my instagram",
  "look at my profile", "understand my account", "audit my whole account",
  "here is my handle", names a new client handle, or on the first run of /ig.
---

# ig-scan

Every other skill gives better advice when it knows the account. This one
reads it once, writes down what it found, and keeps it fresh every month.

Output, in the active account's data folder
(`DATA=$(python3 ~/.claude/skills/ig-account/account.py path)`):

- `account.md` - the profile, for the user and for Claude. Has a
  "Claude's read" section that you write and that survives rescans.
- `account.json` - the same numbers for scripts. `/ig` reads it.
- `scan/` - the normalized posts, the account header, and the raw source.

One script lives in this folder. Run it from here. Stdlib Python.

```bash
python3 scan.py ingest --captured "$DATA/scan/captured-kweo.json"   # kweo, screenshots, manual
python3 scan.py dyi ~/Downloads/instagram-handle-2026-10-01.zip --followers 18400
python3 scan.py api --insights            # only if IG_ACCESS_TOKEN is set in the shell
python3 scan.py analyze                   # writes account.md + account.json
python3 scan.py context                   # 10-15 lines for other skills
python3 scan.py prefill                   # suggested profile values + 3 typical captions
python3 scan.py to-ledger --dry-run       # then without --dry-run
```

## Rules. Not negotiable.

- **Only accounts the user owns, or manages for a client.** Not competitors,
  not exes, not "just look at this person". Research on other accounts
  belongs to /ig-viral and stays at the level of public posts.
- **Read only.** Nothing is posted, liked, followed, saved, commented or sent.
  Browsing follows /ig-kweo: human speed, the user present, no background runs.
- **Never log in for the user.** Never ask for a password, a 2FA code or a
  cookie. If kweo hits a login wall, the user logs in themselves, in kweo.
- **Tokens stay in the environment.** If the user goes the API route, they
  set `IG_ACCESS_TOKEN` in their own shell. Do not ask them to paste it into
  the chat. Do not echo it, write it to a file, or put it in a command line.
  `scan.py` reads it from the env and redacts it from every error.
- **Never invent numbers.** A metric that was not on the page is null.

## Step 1. Which account, and how to read it

Ask once, in one message, if you do not already know:
"Which Instagram account are we growing? Your handle, and how should I read
it: kweo browser (default, you stay logged in there), your data export,
screenshots, or an official API token?"

If the handle is not the active account, set it up first with /ig-account
(`account.py new HANDLE` then `account.py use HANDLE`), so the files land in
that account's folder.

Then pick the source, in this order.

### 1. kweo (default)

The user is already logged in to Instagram in kweo, so this needs no keys.

1. Run `python3 ~/.claude/skills/ig-kweo/kweo_check.py --json`.
2. **Not ready:** show its `next` step in one line, then offer the export
   or screenshot route below. Do not block on it.
3. **Ready:** launch the `ig-kweo-reader` agent (Agent tool,
   `subagent_type: ig-kweo-reader`) with job `profile`:
   *"Job: profile. Handle: @HANDLE. Latest 24 posts. Write the captured JSON
   to $DATA/scan/captured-kweo.json."* Use the real path.
4. **More history** (if the account posts often and 24 posts cover under
   about two months): from the profile file's grid URLs, or the user's list,
   launch up to 2 more readers in parallel with job `posts`, each on a
   different slice of URLs, writing `captured-kweo-2.json`,
   `captured-kweo-3.json`. Never more than 3 readers at once, about 60 posts
   in total. Each reader gets its own kweo tab, so the user's tabs are left
   alone.
5. **Own professional account:** offer one more reader with job `insights`
   for the latest 12 post URLs (reach, saves, shares, skip rate, watch time).
   Ask first. It writes `captured-kweo-insights.json`.
6. Ingest all of them in one call. Posts are merged by URL; insights fill
   numbers onto the matching posts:

```bash
python3 scan.py ingest --captured "$DATA/scan/captured-kweo.json" \
    --captured "$DATA/scan/captured-kweo-2.json" --captured "$DATA/scan/captured-kweo-insights.json"
```

If any file has `"blocked": "login"`, `ingest` exits 3 and saves nothing.
Tell the user: "Instagram wants you to log in. Open kweo, log in to Instagram
yourself, then tell me and I will read it again." Then re-run the readers.

### 2. Download Your Information export

Best for full history and for captions. In Instagram: **Accounts Center →
Your information and permissions → Download your information**, pick the
account, choose **JSON** (not HTML), a date range (all time), low media
quality. Meta emails a link; it can take hours.

```bash
python3 scan.py dyi ~/Downloads/instagram-HANDLE-DATE.zip --followers N
```

It reads the zip in place (nothing extracted), finds
`your_instagram_activity/content/posts_*.json` and `reels.json` wherever
they sit, repairs the export's broken accents and scripts (Meta writes
UTF-8 as Latin-1 escapes), and counts followers from the followers list when
present. Exports have **no likes, comments or views**. Ask the user for the
follower count if it is missing, and pair the export with a kweo profile
read for recent numbers: both can be ingested, they merge.

### 3. Screenshots or paste

Ask for: the top of the profile (name, bio, followers, following, posts),
the grid, and for the latest 12 or so posts the caption and the numbers
(insights screenshots are best). Read them and write the captured JSON
yourself, `"source": "screenshot"`, to `$DATA/scan/captured-screens.json`,
then `scan.py ingest --captured` it. Copy captions verbatim. Unknown is null.

### 4. Official API (advanced, optional)

For users with a professional account and a developer app who already have an
Instagram API with Instagram Login token (scope `instagram_business_basic`,
plus `instagram_business_manage_insights` for `--insights`). They run
`export IG_ACCESS_TOKEN=...` in their own shell, then:

```bash
python3 scan.py api --max 200 --insights
```

Read-only GETs to `graph.instagram.com` (`/me`, `/me/media` with paging,
`/{media-id}/insights`). Version defaults to v25.0; override with
`IG_API_VERSION`. Metrics the API refuses for a post type are skipped and
listed, not fatal.

Captured schema, for kweo files, screenshots and manual entry:

```json
{"handle":"","name":"","bio":"","website":"","followers":0,"following":0,"posts_count":0,
 "account_type":"creator|business|unknown","category":"","source":"kweo|screenshot|manual",
 "posts":[{"date":"YYYY-MM-DD","type":"reel|carousel|photo|story","caption":"",
   "likes":null,"comments":null,"views":null,"url":"","pinned":false}],
 "notes":""}
```

Extra fields are ignored. Numbers can be `"12.4K"` or `"1,204"`.

## Step 2. Analyze

```bash
python3 scan.py analyze
```

It computes size tier (nano under 10k, micro to 100k, mid to 500k, macro to
1M, mega above), cadence and consistency, format mix and how it shifted,
median numbers, engagement rate per format, each post's multiple over the
account median, top and bottom 5, keywords, hashtags vs the 5-tag cap, theme
clusters, languages by script (Hindi, Urdu, Hinglish and others), asks, hook
formulas (the 26 from ig-reel/hooks.json), emoji, then ranks format, formula,
theme and caption length by mean outlier multiple. Groups under 3 posts are
marked thin. It ends with a keyword NICHE GUESS, the worst habit, and how sure
it is.

Then **read `account.md` and a dozen of the actual captions**, and replace
the placeholder under `## Claude's read` with five short lines:

- Niche, in one line (the user's words if they gave them)
- Audience: who, where, what language
- What the account is for: sell, leads, personal brand, community
- What is working, with the numbers that show it
- Three opportunities that fit this account, each tied to a finding

`analyze` keeps that section on every rescan.

## Step 3. Show, confirm, hand off

Show a short summary, not the whole file: handle, tier, niche guess,
cadence, best format and formula, worst habit, and the caveats. Then:

1. **Confirm the niche.** "From your posts this looks like X for Y. Right?"
   Fix Claude's read with their answer.
2. **Prefill the profile.** Run `scan.py prefill`. Show the suggested region,
   niche, account type and language with the reason for each. Save only what
   the user confirms: `python3 ~/.claude/skills/ig/state.py set ...`.
3. **Voice.** `prefill` also prints the 3 most typical captions. Offer to
   draft `voice.md` from them. Write it only after the user approves the
   draft.
4. **Ledger.** `scan.py to-ledger --dry-run`, say what it would add, then run
   it. It matches by permalink, then date plus first line, never duplicates,
   and never blanks a number already logged.
5. **Next:** /ig-grow for this week's plan, or back to /ig.

## How other skills use this

Before recommending anything, other skills read `account.md` (or run
`scan.py context`) and fit advice to this account: its size tier, its niche,
its audience language, what has already worked for it, and its worst habit.
A micro account and a mega account need different advice.

## Be honest about the sample

Fewer than 12 posts is a hint, not a finding. A ranking group with fewer than
3 posts is thin. Likes-only data says less than views. The account age from a
kweo or API read is a minimum. Say these out loud when they apply; `analyze`
lists them under "How sure is this".

Rescan monthly. `/ig` adds a rescan step when `account.json` is over 30 days
old.
