---
name: ig-grow
description: >-
  The free audience-growth coach for Instagram. Tracks follower growth, finds
  the one bottleneck (reach, conversion, consistency or retention), and turns
  it into this week's ranked actions, each handed to the right ig- skill. Use
  when the user says "grow my audience", "get more followers", "grow my
  Instagram", "why am I not growing", "growth plan", "how do I go viral",
  "weekly review", or wants to know what to do this week to grow.
---

# ig-grow

The head coach. The rest of the pack writes, edits, logs and checks. This
decides what to do this week to grow, keeps score in followers, and hands
each job to the skill that does it.

**Account context.** Before recommending anything, read `account.md` in the
active account's data folder, or run `python3 ~/.claude/skills/ig-scan/scan.py context`.
It has this account's niche, size tier, audience language, cadence and what
already performs for it. Fit the advice to that. If it is missing, suggest
/ig-scan once and carry on.

Run it once a week, same day. That is the whole system.

## Said once, plainly

Growth here is free and real. No paid ads, no bought followers, no
follow/unfollow, no engagement pods, and no automation of likes, follows,
comments or DMs. Instagram removes inauthentic likes and follows and
restricts accounts that use these tools (see `references.md`). This skill
never posts and never touches Instagram. The user does every action by hand.

And no guarantee of going viral. Nobody can promise it. The aim is
repeatable outliers: reels that do 3x your own median, often enough that
the follower line bends.

## The tool

One script, stdlib Python, no installs, no network. Run it from this folder.

```bash
python3 grow.py checkin --followers 861 [--following 302] [--posts 59] [--date 2026-10-15]
python3 grow.py report [--weeks 4] [--json]
python3 grow.py plan [--json]
python3 grow.py milestones [--json]
```

- **checkin** appends one row to `followers.csv` (same date replaces). Prints
  net growth for the week and the month, growth rate, the trend against the
  previous weeks, and a projection to the next milestone (1k, 5k, 10k, 50k,
  100k) at the current pace. It is a projection. Say so.
- **report** prints the GROWTH REPORT: followers gained, follows per reach
  per post (which posts actually converted), which formats, themes and hook
  formulas converted, the non-follower share by week, posts per week against
  the target of 4, trial reels and collabs used, engagement-round days, and
  the ONE bottleneck.
- **plan** prints up to 7 ranked actions for this week, each with the skill
  that does it. With no data it prints the onboarding plan.
- **milestones** lists milestones hit and when.

`--today YYYY-MM-DD` pins the date for backfills.

## Data

The data dir is `$IG_DATA_DIR` if set. Otherwise, if
`$IG_HOME/active-account` names a handle and `$IG_HOME/accounts/<handle>/`
exists, that folder (set by `/ig-account`). Otherwise `$IG_HOME`, default
`~/.claude/instagram`.

| file | who writes it | ig-grow |
| --- | --- | --- |
| `followers.csv` | this skill | reads and appends |
| `posts.csv` | `/ig-ledger` | reads via `ledger.load_rows()` |
| `snapshots.csv` | `/ig-perf` | reads, if present |
| `trends.md` | `/ig-trends` | reads, if present |
| `plan.md`, `voice.md`, `engaged.md` | `/ig-plan`, `/ig-reel`, `/ig-comment` | reads, if present |

Collabs are counted from the word "collab" in a ledger row's `notes`. Tell
the user to log it that way: `ledger.py update P0021 --notes "collab @peer"`.

## The weekly loop

1. **Check in.** Ask the user for today's follower count, or read it from
   their public profile with `/ig-kweo` (read only: look, never tap follow,
   like, comment or send). Run `grow.py checkin --followers N`.
2. **Fill the gaps.** If posts from last week have no numbers, get them in
   with `/ig-ledger` or `/ig-perf` first. A report on empty rows is a guess.
3. **Report.** Run `grow.py report`. Read the bottleneck to the user in one
   sentence, with the number behind it.
4. **Plan.** Run `grow.py plan`. Show the list as is. Do not pad it past 7.
5. **Hand off, in order.** Walk the list top to bottom, one skill at a time.
   Finish one before starting the next. Typical owners:
   `/ig-profile`, `/ig-reel`, `/ig-test`, `/ig-dm`, `/ig-reply`,
   `/ig-trends`, `/ig-audio`, `/ig-perf`, `/ig-edit`, `/ig-repurpose`,
   `/ig-plan`, `/ig-comment`, `/ig-caption`, `/ig-viral`.
6. **Calendar.** Offer `/ig-calendar` to put the week's posts and the daily
   engagement rounds in Google Calendar.
7. **Next week, repeat.** Same day. The check-in is the scoreboard.

## The bottleneck

Checked in pipeline order, because an upstream failure hides the rest.
Thresholds are named constants at the top of `grow.py`, with the reasoning.
They are rules of thumb, not Meta numbers.

| order | bottleneck | fires when | meaning | first move |
| --- | --- | --- | --- | --- |
| 1 | consistency | under 3 feed posts a week | too few chances to be found | `/ig-plan`, `/ig-repurpose` |
| 2 | retention | median reel skip rate over 50% | the hook loses the room | `/ig-reel`, `/ig-test`, `/ig-edit` |
| 3 | reach | median non-follower share under 30% (or reach under 0.5x followers) | reels stay with followers | `/ig-trends`, `/ig-test`, `/ig-dm` collab |
| 4 | conversion | under 0.2% follows per reach | they watch, they do not follow | `/ig-profile` |

If nothing is under its line, the report names the stage closest to it, so
the week still has one focus. Under 5 posts with numbers, every call is
marked early. Say so.

Remember the line from `/ig-audit`: a reel with views and no follows is a
profile problem. A reel with no views is a hook problem.

## Free growth playbook

Grounded in `references.md`. Instagram's own words where possible.

- **Sends beat likes for strangers.** Mosseri names watch time, likes per
  reach and sends per reach as the top signals, with sends weighing slightly
  more for non-followers. Make things people forward to one friend.
- **The first 2 seconds.** Watch time is the top signal for both followers
  and non-followers. Skip rate is the hook's grade. Fix it before anything.
- **Originality.** Instagram is pulling reposts and aggregators out of
  recommendations, and says 75% of recommendations now come from original
  posts. Watermarked or recycled reels get shown less. Shoot your own.
  Export from Edits or your editor without another app's watermark.
- **Trial Reels.** Shown to non-followers first. A miss costs nothing with
  followers. Use one a week for a new format or a hook test (`/ig-test`).
- **Collabs.** A collab post reaches both audiences and sits on both grids.
  One pitch a week to a peer your size (`/ig-dm`).
- **Reply with a reel.** Turn the best question in your comments into a reel.
  The comment becomes a sticker and the asker gets the answer (`/ig-reply`).
- **Search-friendly captions.** Keywords and hashtags in the caption, not
  the comments. Name field and bio in the words people search
  (`/ig-caption`, `/ig-profile`).
- **Consistency.** Instagram says the best way to grow is original content,
  posted consistently. This pack's target is 4 a week, 3 of them reels. That
  number is ours, not Instagram's.
- **Profile conversion.** Every reel that travels sends strangers to the
  profile. It has three seconds to say what they get by following.
- **Community, early.** Reply to comments in the first hour, and do a
  20-minute round of real comments on other accounts before posting
  (`/ig-comment`). By hand.

What does not move growth much: the exact posting hour, hashtag counts,
and anything bought. Check the hook first.

## Files

- `grow.py`: the tool.
- `references.md`: sources, with dates and URLs.
- `tests/test_grow.py`: `python3 -m unittest discover -s tests`. Temp dirs
  only. Never touches `~/.claude/instagram`.
