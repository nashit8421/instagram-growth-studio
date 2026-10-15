---
name: ig-ledger
description: >-
  The results log for every post - what was posted, which hook formula it
  used, and the numbers it got - plus an audit that does the maths in code.
  Use when the user says "log this post", "add my numbers", "import my
  insights", "update the ledger", "what's working for me", "audit my posts",
  pastes per-post insights, has a Meta Business Suite CSV export, or has just
  said "yes" to a draft from /ig-reel, /ig-carousel, /ig-story or /ig-caption.
---

# ig-ledger

The rest of the pack writes posts. This one remembers how they did.

Instagram's in-app insights only reach back about 90 days. After that the
numbers are gone. The ledger is the long-term memory: one row per post, the
hook formula it used, and the results. After about 30 rows it can tell you
which formulas work for this account, not for accounts in general.

Two scripts live in this folder and they both run. Run them from this skill's
own folder (Claude Code gives you the base directory when the skill loads).
Stdlib Python, no installs, no network. Nothing is uploaded. Everything stays
in `posts.csv` in the active account's data folder: run
`python3 ~/.claude/skills/ig-account/account.py path` (see /ig-account;
defaults to `~/IGStudio`).

```bash
python3 ledger.py add --format reel --hook-formula 3 --theme pricing \
    --first-line "Nobody tells you your first 30 reels are practice" --length 27
python3 ledger.py update P0012 --views 12,400 --reach 9,870 --shares 88 \
    --saves 140 --follows 41 --skip-rate 31 --nonfollower-pct 62 --avg-watch 9
python3 ledger.py import ~/Downloads/export.csv --dry-run
python3 ledger.py import ~/Downloads/export.csv
python3 ledger.py list --last 10
python3 audit.py
python3 audit.py --format reel --since 2026-06-01
```

Add `--json` to `list` or `audit.py` when another skill needs the numbers.

## When to log

**The moment the user says "yes" to a draft.** That is in /ig-reel,
/ig-carousel, /ig-story, /ig-caption, or anywhere else a post gets approved.
Run `ledger.py add` with what you already know:

- `--format` reel, carousel, story or photo. Required.
- `--hook-formula` the id from `ig-reel/hooks.json`. This is the column the
  audit learns from, so never leave it out when you know it.
- `--first-line` the spoken hook or the cover line, word for word.
- `--theme` one or two words. Keep the same words across posts ("pricing",
  not "pricing" one week and "rates" the next), or the groups split.
- `--length` seconds, for reels.
- `--trial` if it goes out as a trial reel. `--test-id T001 --variant A` if it
  is half of an A/B test.

It prints the new id and nothing else, for example `P0014`. Tell the user the
id. They will need it to add numbers later.

Still append to `log.md` if the skill you came from says to. The ledger does
not replace it, it adds the results that `log.md` never had.

## Adding the numbers

Wait at least 48 hours after posting, a week is better. Then either:

**Paste.** The user pastes or screenshots the post's insights. Read off the
numbers and run `ledger.py update ID` with whatever is there. Leave out what
is not. An empty cell means unknown, never zero. Skip rate and non-follower
share are percentages (31, not 0.31).

**Import.** For many posts at once: Meta Business Suite, then Insights, then
Content, then Export. Pick the date range and download the CSV. Run
`ledger.py import FILE.csv --dry-run` first and show the summary, then run it
for real. It matches rows by permalink, then by same date plus the opening of
the caption. Anything it cannot match becomes a new row marked `imported`.

Imported rows have no hook formula and no theme, because the export does not
know them. Go through the new ids with the user and fill those in with
`update`. A row without a hook formula still counts toward the median, it just
cannot teach you anything about hooks.

The export usually has no non-follower share and no average watch time. Those
come from the per-post insights screen. Add them by hand for the posts that
matter most: the top and bottom five.

## The audit

`audit.py` replaces the hand maths in /ig-audit. When the user asks what is
working, run it first and work from its output, not from screenshots.

What it computes:

- **Median views**, from the account's own posts. Trial reels are left out
  because they only go to non-followers. Stories are left out because they
  mostly go to followers. Audit either one on its own with `--format`.
- **Outlier multiple** per post: views over that median.
- **Sends, saves and follows per reach**, skip rate, non-follower share.
- **Top 5 and bottom 5** by outlier multiple, and the averages of each.
- **Group means** by hook formula, format, length bucket (under 15s, 15 to
  30s, 30 to 60s, over 60s) and theme, each with its n. Groups under 3 posts
  are marked thin.
- **Profile check.** Reels reaching mostly non-followers (50% or more) but
  converting under 0.2% follows per reach is a profile problem, not a hook
  problem. Send the user to /ig-profile.

It always prints n. Under 10 posts it says the patterns cannot be trusted
yet. Between 10 and 29 it calls them an early signal. At 30 and up, patterns
are visible. Repeat that to the user in plain words. Do not dress up a thin
group as a finding.

Then write the WHAT THE DATA SAYS and STOP / DO MORE part of the /ig-audit
report yourself, from these numbers, with the n attached to every claim.

## Feeding the rest of the pack

After about 30 posts, the hook formula table is the most useful thing the
user owns. Hand it to /ig-plan so next week leans on the formulas that beat
this account's median, and drops the ones that sit under 1x. Hand the
skip-rate comparison to /ig-reel: if the top five skip far less than the
bottom five, the hook is the whole story.

## Rules

- Never invent numbers. If the user does not have a metric, leave it empty.
- Never write to the ledger by hand-editing the CSV in a way that breaks the
  header. Use the scripts.
- Never publish anything. This skill only records and counts.
