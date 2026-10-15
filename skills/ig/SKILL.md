---
name: ig
description: >-
  The single entry point for the whole Instagram pack. Works out where the
  account is (setup, weekly review, checks due, today's post) and runs the
  right skills in order, only stopping to ask the user when it needs their
  input or approval. Use when the user types /ig, says "start", "what do I do
  today", "run my Instagram", "do the next thing", "let's go", or is not sure
  which ig- skill to use.
---

# ig

One command. It reads where the account is and drives the other 24 skills
from there. The user answers questions and approves things. Claude does the
rest.

```bash
python3 state.py              # where we are + ordered next steps
python3 state.py --json
python3 state.py set --region IN --niche "freelance contracts" --account-type creator
```

## The loop

1. **Run `state.py --json`.** Say the active account and the stage in one
   line. Once `scan` is in the state, read `account.md` in the data folder
   (or `python3 ~/.claude/skills/ig-scan/scan.py context`) so every step
   fits this account's niche, size and what already works for it. If there is more than one account (`/ig-account list`), confirm
   which one before doing anything.
2. **Take the first step in `next`.** Invoke its skill and follow that
   skill's instructions fully. When the step has an `ask`, ask exactly that,
   batched into one message, and wait.
3. **After each step, run `state.py` again** and take the new first step.
   Steps disappear as their files appear, so the list is the progress bar.
4. **Keep going** until only `engage` is left, or the user says stop. Then
   give a short wrap-up: what got done, what is waiting on the user (film,
   post, send numbers later), and when to run `/ig` again.

Do not dump the whole list on the user. Show the next one or two steps, do
them, move on.

## The steps, and what each one does

| key | skill | done when |
|---|---|---|
| scan | /ig-scan | `account.json` + `account.md` written from the real account (kweo by default). First on a new account; it prefills profile and voice. Comes back as non-blocking `rescan` after 30 days |
| profile | this skill | `state.py set --region --niche --account-type` saved (confirm /ig-scan's `prefill` suggestions) |
| voice | /ig-reel's voice step | `voice.md` written in the data folder from their own captions |
| baseline | /ig-grow | `grow.py checkin --followers N` |
| profile_score | /ig-profile | user has the rewrites (they edit Instagram themselves) |
| perf | /ig-perf | `perf.py check` for every post listed |
| weekly_review | /ig-grow | checkin, report, plan. The plan's actions become the next steps |
| trends | /ig-trends | `trends.md` written (browse through /ig-kweo rules) |
| plan | /ig-plan | `plan.md` written, using trends.md and the growth plan |
| calendar | /ig-calendar | events created after the user said yes, or .ics written |
| create_today | the route shown | draft approved, files made, logged with /ig-ledger |
| engage | /ig-comment | user has their comments to post by hand |

## Today's post, end to end

For a **reel**: /ig-reel (hooks scored, script, beat sheet, humanized) →
if two hooks are close, offer /ig-test → /ig-audio for the sound → the user
films → /ig-edit on their file → /ig-caption → the user posts → log with
/ig-ledger → remind them /ig-perf will ask for numbers at 1h, 24h, 72h, 7d.

For a **carousel**: /ig-carousel → user approves copy → /ig-render →
/ig-caption → user posts → /ig-ledger.

Wait for the user at: approving copy, filming, posting, and any calendar
change. Everything between those points runs without asking.

## Rules that do not bend

- **Nothing is posted, liked, followed, commented or sent by Claude.** Every
  skill ends in copy-ready text or files. The user posts.
- **Ask before anything outward-facing**: calendar events, emails, anything
  that leaves the machine.
- **Browsing follows /ig-kweo**: read only on Instagram, human speed, the user
  present. If kweo is not connected, say once how to connect it
  (`kweo_check.py` prints the steps) and carry on with web search.
- **Never invent numbers.** Unknown proof stays `{{your number}}`.
- **No promises of virality.** The pack improves the odds and measures what
  works. Say that once, not every turn.
- All files live in the active account's data folder. `state.py` and every
  script resolve it the same way: `IG_DATA_DIR`, else the active account, else
  `~/.claude/instagram`.
