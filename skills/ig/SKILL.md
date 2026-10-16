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

One command. It reads where the account is and drives the other 26 skills
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
   skill's instructions fully. When a step has an `ask`, first try to answer
   it yourself (the scan, the profile, kweo). Ask the user only when there is
   no reasonable guess, and then one short question.
3. **After each step, run `state.py` again** and take the new first step.
   Steps disappear as their files appear, so the list is the progress bar.
4. **Keep going** until only `engage` is left, or the user says stop. Then
   give a short wrap-up: what got done, what is waiting on the user (film,
   post, send numbers later), and when to run `/ig` again.

Do not dump the whole list on the user, and do not narrate each step or
ask permission between them. Run setup, check-in and planning in one go and
answer with the week: "Here's the plan for this week" and "What you need to
do". Then one line of what you assumed, which the user can correct.

## The steps, and what each one does

| key | skill | done when |
|---|---|---|
| scan | /ig-scan | `account.json` + `account.md` written from the real account (kweo by default). First on a new account; it prefills profile and voice. Comes back as non-blocking `rescan` after 30 days |
| profile | this skill | `state.py set --region --niche --account-type` saved from /ig-scan's `prefill` and Claude's read, no confirm needed |
| voice | /ig-reel's voice step | `voice.md` drafted from their own captions and saved, no confirm needed |
| baseline | /ig-grow | `grow.py checkin --followers N` |
| profile_score | /ig-profile | user has the rewrites (they edit Instagram themselves) |
| perf | /ig-perf | `perf.py check` for every post listed |
| weekly_review | /ig-grow | checkin, report, plan. The plan's actions become the next steps |
| trends | /ig-trends | `trends.md` written (browse through /ig-kweo rules) |
| plan | /ig-plan | `plan.md` written, using trends.md and the growth plan |
| calendar | /ig-calendar | events created after the user said yes, or .ics written |
| create_today | the route shown | draft approved, files made, logged with /ig-ledger |
| engage | /ig-comment | user has their comments to post by hand |

## Autopilot: the whole week as post kits (IG Studio)

When the prompt says **Autopilot**, prepare the week end to end and ask the
user nothing. IG Studio's home screen shows the result, so the deliverable is
a file, `week.json`, not a chat message. Budget: one run, about 10 minutes.

```bash
S=~/.claude/skills
python3 $S/ig/week.py monday                  # the Monday to plan (Mon-Wed: this week, Thu-Sun: next)
python3 $S/ig/week.py schema                  # the exact shape, filled in
python3 $S/ig/week.py check "$DATA/week.json" --fix --json
python3 $S/ig/week.py plan-md "$DATA/week.json"
# the kit tools: drafts go in $DATA/.studio/kit/<week_of>/ (not the data folder itself)
python3 $S/ig-reel/hookscore.py FILE --json   # one hook per line; exit 1 = best hook under 70
python3 $S/ig-reel/beats.py FILE --target 25 --json      # one line per beat
python3 $S/ig-caption/caption.py FILE --json  # exit 1 = verdict not READY
python3 $S/ig-human/humanize.py FILE --json   # {text, report}
python3 $S/ig-human/detect.py FILE --json     # human score; aim for 70+
python3 $S/ig-audio/audio.py suggest --reel-length 25 --mood dramatic --account creator --voiceover yes --region IN --json
```

Exit code 1 from hookscore or caption means "weak", not "broken": rewrite and run
it again. Do not read the scripts' source; the lines above are all you need.

1. **Where are we.** `state.py --json`. Read `account.md`, `voice.md`,
   `profile.json`, `trends.md`, `swipe.md` if they exist.
2. **Scan if needed.** No scan, or older than 30 days: run /ig-scan on the
   active handle with kweo and do its Step 3 (save profile, voice, ledger,
   baseline). If kweo is not ready and there is no scan, say so in one line
   and stop: there is nothing true to plan from.
3. **Bottleneck.** Check in followers if there is no check-in today (scan
   count), then `grow.py report` and `grow.py plan`.
4. **Trends.** If `trends.md` is missing or over 7 days old, run /ig-trends
   (web search when kweo is off). Keep it to the few searches that matter.
5. **The slots.** Follow /ig-plan: 4 to 5 posts, at least 3 reels, the type
   mix, the audience's evening, dated trends on their dates.
6. **A kit per post.** For every slot write what the user needs to make it
   without asking anyone:
   - `hook`: the spoken first line and the on-screen text, from /ig-reel's
     formulas. Score 3 to 5 candidates with `ig-reel/hookscore.py` and keep
     the best; put its score in `hook.score`. The scorer reads English: for
     a Hinglish or other non-English voice, keep the hook in the account's
     own language and treat the score as a guide, not a gate.
   - `script`: timed beats (`t`, `say`, `on_screen`, `shot`). Time it with
     `ig-reel/beats.py`. Reels 15 to 35 seconds unless the idea needs more.
   - `direction`: the director's notes for filming on a phone, in the same
     vocabulary as /ig-direct: `concept`, `mood`, `setup` (location, light,
     framing, wardrobe, props), numbered `shots` (frame, action, line,
     seconds), `delivery` tips, `takes`, and `avoid` (Instagram's buttons
     cover the bottom fifth and the right edge). Concrete enough that a
     friend holding the phone could shoot it.
   - `caption`: /ig-caption rules (the first line survives "... more", one
     ask, 3 hashtags). Lint with `ig-caption/caption.py`.
   - `sound`: /ig-audio's pick, with how to add it in Instagram.
   - `cover`: the cover text and which frame.
   - Carousels get `slides` instead of a script and shots.
   - Never invent facts: an event, a client, a number. Where the user has to
     supply one, the script says so in braces, like `{{your number}}`, and
     the shot tells them what to film.
   - Run every caption and script line through `ig-human/humanize.py`.
7. **Around the posts.** `stories` per day, the `engage` round, and `todo`:
   only what the user does with their hands (film, post, comment, send
   numbers), dated. Batch filming the day before, or two reels per setup.
8. **Write and check.** Write `week.json` in the data folder, run `check
   --fix` until it says OK, then `plan-md` so plan.md, /ig-calendar and
   state.py stay in step.

End with three short lines: the headline, the first thing to do and when,
and what you assumed. The user changes anything by telling Claude; a change
to one post rewrites that post in `week.json` and runs `check` again.

## Today's post, end to end

For a **reel**: /ig-reel (hooks scored, script, beat sheet, humanized) →
if two hooks are close, offer /ig-test → /ig-audio for the sound → the user
films → /ig-direct on their file (storyboard, the user approves, then the
render; /ig-edit for a quick cut) → /ig-caption → the user posts → log with
/ig-ledger → remind them /ig-perf will ask for numbers at 1h, 24h, 72h, 7d.

For a **carousel**: /ig-carousel → user approves copy → /ig-render →
/ig-caption → user posts → /ig-ledger.

Wait for the user at: approving copy, filming, posting, and any calendar
change. Everything between those points runs without asking.

## Rules that do not bend

- **Decide, don't ask.** Anything local and reversible (niche, region,
  language, voice.md, the ledger, the check-in, the plan) Claude decides,
  saves and states as an assumption. The user corrects it in one sentence.
  Stop only for: things only the user can do (film, post, log in), anything
  outward-facing (calendar, profile edits, messages), and approving copy
  that will be posted.

- **Nothing is posted, liked, followed, commented or sent by Claude.** Every
  skill ends in copy-ready text or files. The user posts.
- **Ask before anything outward-facing**: calendar events, emails, anything
  that leaves the machine.
- **Browsing follows /ig-kweo**: read only on Instagram, human speed, the user
  present. If kweo is not connected, say once how to connect it
  (`kweo_check.py` prints the steps) and carry on with web search.
- **Never invent numbers.** Unknown proof stays `{{your number}}`.
- **Position on the essence, not on one post.** The account is who is in it,
  their relationship and the feeling, in the user's own niche words. One
  post's joke is a content angle, never the bio, name, grid theme or niche,
  least of all from a handful of posts.
- **No promises of virality.** The pack improves the odds and measures what
  works. Say that once, not every turn.
- All files live in the active account's data folder. `state.py` and every
  script resolve it the same way: `IG_DATA_DIR`, else the active account, else
  `~/IGStudio`.
