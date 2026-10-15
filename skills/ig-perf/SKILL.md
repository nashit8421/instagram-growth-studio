---
name: ig-perf
description: >-
  Follow one reel or post through its first week - log every check of its
  numbers, show the curve, compare it to the account at the same age, name the
  single biggest problem, and say what to do now and in the next reel. Use when
  the user asks "how is my reel doing", "check my reel", "is this reel
  working", "why is this reel stuck", "update the numbers on" a post, "reel
  performance", or sends a screenshot of a reel's insights or retention graph.
---

# ig-perf

/ig-audit looks back at many posts. This one watches one post while it is
still alive, when there is still something to do about it.

**Account context.** Before recommending anything, read `account.md` in the
active account's data folder, or run `python3 ~/.claude/skills/ig-scan/scan.py context`.
It has this account's niche, size tier, audience language, cadence and what
already performs for it. Fit the advice to that. If it is missing, suggest
/ig-scan once and carry on.

A reel's life is mostly decided in its first 72 hours. The ledger keeps the
final totals. ig-perf keeps the curve: one row per check, so you can see
whether a post is climbing, done, or stuck on one fixable problem.

One script lives in this folder. Run it from this skill's own folder. Stdlib
Python, no installs, no network.

```bash
python3 perf.py check P0004 --views 3,400 --reach 2,900 --shares 9 --saves 31 \
    --follows 6 --skip-rate 41 --nonfollower-pct 58 --avg-watch 11 --source screenshot
python3 perf.py status P0004
python3 perf.py status P0004 --script script.txt
python3 perf.py due
python3 perf.py retention P0004 --points "0:100,1:82,3:61,10:40,20:22" --script script.txt
```

Add `--json` to any of them when another skill needs the numbers.

## Where the files are

Same data dir as the rest of the pack: `$IG_DATA_DIR`, else the active
account folder (`~/IGStudio/accounts/<handle>/` when
`~/IGStudio/active-account` names one), else `~/IGStudio`.

- `snapshots.csv`: one row per check. `post_id, taken_at, hours_since_post`,
  the metrics, `source` and `notes`. Empty means unknown, never zero.
- `retention.csv`: retention graph points, one row per reading.
- `posts.csv`: the ledger. Every check brings the post's row up to the latest
  totals. A backfilled older check does not overwrite newer numbers.

The post has to be in the ledger first. If it is not, log it with
`/ig-ledger` (`ledger.py add --format reel --hook-formula N ...`) and use the id.

## When to check

At **1h, 24h, 72h and 7d** after posting. Those are the checkpoints the
timeline lines up and the account comparison uses.

- **1h**: did the first wave go? Reply to every comment now.
- **24h**: the real first read. Skip rate and watch time are settled enough.
- **72h**: most reels have had their run. Has it travelled to non-followers?
- **7d**: the final shape. Stalled or still going.

Run `perf.py due` at the start of any Instagram conversation. It lists posts
from the last 9 days whose current checkpoint has no check yet. Remind the
user in one line ("P0004 is at 24h, want to read its numbers?"). Do not nag.

## Getting the numbers

**From the app.** Open the reel, tap **View insights** (on the reel itself, or
from the professional dashboard). The useful ones:

- Views and accounts reached, and the share of reach from **non-followers**.
- **Skip rate**: the share who swiped away in the first 3 seconds.
- **Average watch time**, and the **retention graph** (how many are still
  watching at each second).
- Interactions: likes, comments, **shares** (sends), **saves**, **follows**.

**From a screenshot.** If the user sends a screenshot of insights, read the
numbers off it yourself and run `check` with `--source screenshot`. Say which
numbers you read so they can correct a misread. If a number is cut off or
blurry, leave it out. Never guess.

**From a retention graph screenshot.** Read 5 to 8 points off the curve as
`seconds:percent`, always including 0s, about 3s, and the steepest drops.
Run `retention` with them, and with `--script` if the script is around (from
/ig-reel or log.md). It names the steepest drops and the lines that sit on
them. A graph read by eye is approximate. Say so.

**From the kweo browser.** If the `ig-kweo` skill is available and the user
is logged in to their own account there, you may open their own reel's
insights and read the numbers. Read-only, their own session, their own
insights only. Use `--source kweo`. Never use it to look at anyone else's
private data.

`--hours` is the age of the post. Or give `--at "YYYY-MM-DD HH:MM"` for when
the numbers were read (default now) and `--posted-at` once, and the age is
worked out. After the first check the post time is remembered. Without either,
the post is assumed to have gone up at noon on its ledger date, and the
report says so.

## Reading the status

`status` prints, in order:

- **TIMELINE**: every check, labelled with the checkpoint it counts as, and
  any checkpoint that was missed.
- **VELOCITY**: views per hour between the last two checks. Slowing is
  normal. Accelerating means a second wave. Stalled means under a tenth of
  its average hourly rate.
- **VERSUS YOUR ACCOUNT**: the outlier multiple. Against other posts at the
  same age when 3 or more have checks near it, else against the ledger median
  (which flatters old posts, and the report says so). Always with n.
- **DIAGNOSIS**: the single biggest problem, then the others. Rules of thumb,
  in this order, because an earlier one hides the later ones:

| rule | fires when | what it means |
| --- | --- | --- |
| hook | skip rate over 45% | rewrite the first 2s. Names the formula used and two others from `ig-reel/hooks.json`, the account's own winners first |
| middle | watch under 40% of length, skip OK | shorten, new frame every beat, re-run beats.py |
| nothing to send | sends under 0.5% of reach, watch OK | add a takeaway line, a claim worth forwarding |
| not travelling | under 30% non-followers after 24h | trial reel, collab, reply-with-reel |
| profile | 50%+ non-followers, follows under 0.2% of reach | /ig-profile |
| ran its course | stalled after 72h, nothing else wrong | carousel, reply to comments with reels |

  Under 1,000 reach the report warns that one send moves the rates a lot.
  Metrics that were not given are listed as not checked, never assumed.

- **IMPROVE**: 3 actions for this post now and 3 lessons for the next reel.

With `--script`, the average watch time is mapped onto the beat sheet from
`ig-reel/beats.py`, so "they leave at 8s" becomes "they leave in beat 3".

## What to tell the user

Lead with the one problem and the one thing to do now. Then the numbers. Keep
the n and the noise warnings in. A 1.4x on 600 views is a good day, not a
finding. Do not dress up the multiple.

Then hand the lessons on:

- Hook and middle lessons go into the next **/ig-reel**: the formula to try,
  the length to aim for, the beat to cut.
- "Make another like this", "plan a trial reel a week", "turn it into a
  carousel" go into **/ig-plan** for this week.
- A profile problem goes to **/ig-profile**. A follow-up reel answering a
  comment starts in **/ig-reply** then **/ig-reel**.

## Rules

- Never post, like, comment, reply or DM. This skill reads and counts. The
  user does every action in the app.
- Never invent numbers. Unknown stays empty.
- Use the scripts to write the CSVs. Do not hand-edit them.
- Thresholds are rules of thumb, named at the top of `perf.py`. Say so when
  a call is close to a line.
