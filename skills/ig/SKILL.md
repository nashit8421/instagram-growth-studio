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
   fits this account's niche, size and audience. If there is more than one account (`/ig-account list`), confirm
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
| voice | /ig-reel's voice step | `voice.md`: the language on camera and the hard no's, drafted from the scan, no confirm needed. Never the tone of a post |
| baseline | /ig-grow | `grow.py checkin --followers N` |
| profile_score | /ig-profile | user has the rewrites (they edit Instagram themselves) |
| perf | /ig-perf | `perf.py check` for every post listed |
| weekly_review | /ig-grow | checkin, report, plan. The plan's actions become the next steps |
| viral | /ig-viral | `viral.json` + `swipe.md`: reels going viral in the niche now, ranked by how far each beat its own account. Every planned post copies one. Redone every 14 days |
| trends | /ig-trends | `trends.md` written (browse through /ig-kweo rules) |
| plan | /ig-plan | `plan.md` written: each slot copies a reel from viral.json, plus trends.md and the growth plan |
| calendar | /ig-calendar | events created after the user said yes, or .ics written |
| create_today | the route shown | draft approved, files made, logged with /ig-ledger |
| engage | /ig-comment | user has their comments to post by hand |

## Autopilot: the whole week as post kits (IG Studio)

When the prompt says **Autopilot**, prepare the week end to end and ask the
user nothing. IG Studio's home screen shows the result, so the deliverable is
a file, `week.json`, not a chat message. Budget: one run, about 15 minutes
(25 when the viral research has to be redone).

**Every post copies a reel that went viral in the niche.** Not the account's
own past posts and not its old captions: those are the ones that did not
travel. The hook shape, the structure, the pace, the tone and energy, the
on-screen text style and the caption pattern come from the viral reel. The
account supplies only the person, their situation and their facts.

```bash
S=~/.claude/skills
python3 $S/ig/week.py monday                  # the Monday to plan (Mon-Wed: this week, Thu-Sun: next)
python3 $S/ig-trends/moments.py --region IN   # the moments: X trends 24h + news, 3 seconds
python3 $S/ig/week.py schema                  # the exact shape, filled in
python3 $S/ig-viral/swipe.py --reader $KIT/reader-*.json --out "$DATA/swipe.md"   # also writes $DATA/viral.json
python3 $S/ig/week.py check "$DATA/week.json" --fix --json   # --fix copies each model's facts from viral.json
python3 $S/ig/week.py plan-md "$DATA/week.json"
# the kit tools: drafts go in KIT=$DATA/.studio/kit/<week_of>/ (not the data folder itself)
python3 $S/ig-reel/hookscore.py FILE --json   # one hook per line; exit 1 = best hook under 70
python3 $S/ig-reel/beats.py FILE --target 25 --json      # one line per beat
python3 $S/ig-caption/caption.py FILE --json  # exit 1 = verdict not READY
python3 $S/ig-human/humanize.py FILE --json   # {text, report}
python3 $S/ig-human/detect.py FILE --json     # human score; aim for 70+
python3 $S/ig-audio/audio.py suggest --reel-length 25 --mood dramatic --account creator --voiceover yes --region IN --json
```

Exit code 1 from hookscore or caption means "weak", not "broken": rewrite and run
it again. Do not read the scripts' source; the lines above are all you need.

1. **Where are we.** `state.py --json`. Read `account.md` (the niche, the
   audience, the size), `profile.json`, `trends.md` and `viral.json` if they
   exist. Read `voice.md` only for the language spoken on camera and the
   things the user won't say. It is not a style guide.
2. **Scan if needed.** No scan, or older than 30 days: run /ig-scan on the
   active handle with kweo and do its Step 3 (save profile, voice, ledger,
   baseline). If kweo is not ready and there is no scan, say so in one line
   and stop: there is nothing true to plan from.
3. **Bottleneck.** Check in followers if there is no check-in today (scan
   count), then `grow.py report` and `grow.py plan`.
4. **What is going viral.** If `viral.json` is missing or over 14 days old,
   run /ig-viral in autopilot mode (its "Autopilot" section): pick 5 to 7
   accounts yourself, read each with an `ig-kweo-reader` "reels" job on
   `model: "haiku"`, one at a time, then `swipe.py --reader`. About 15
   minutes. Only numbers seen on a page go in.
5. **Moments and trends.** Always run `ig-trends/moments.py --region <R>`
   first, even when `trends.md` is fresh: it takes 3 seconds and it is what
   catches the week's big moment (a launch, a final, a meme). Do /ig-trends
   Step 2 for the top MOMENTs (judge, check creators on Instagram, log the
   bridge as a reel). If `trends.md` is missing or over 7 days old, do the
   rest of /ig-trends too.
6. **The slots.** Follow /ig-plan: 4 to 5 posts, at least 3 reels, the type
   mix, the audience's evening, dated trends on their dates. Each slot is one
   viral reel from `viral.json`: the biggest multiples first, never the same
   model twice in a week unless the list is short, and a format the user can
   actually film. A dated trend is shot in the shape of a viral reel too.
   **The week's biggest moment gets a post** when it has an honest bridge to
   the niche. If the week starts more than a day away, make it a `now`
   post (id `now`, dated today or tomorrow, before `week_of`): a moment is
   worth most in its first 3 days. Its model is the biggest reel already
   riffing on it if one is in viral.json, else the viral reel whose shape
   fits. If no moment fits, say so in `assumptions`, naming the top 3 you
   passed on and why.
7. **A kit per post.** For every slot write what the user needs to make it
   without asking anyone:
   - `model`: `ref` (its id in viral.json), `copy` (what is copied, one line
     each: hook shape, structure, pace and cuts, tone, on-screen text,
     caption pattern), and `change` (what is the user's own). `check --fix`
     fills in the account, link, views or likes and the multiple from
     viral.json; never type those yourself. `why` says it plainly: "Copies
     @x's reel, 22x their usual likes." Claim only what is known: the hook
     line, the caption and the numbers come from the page. You have not
     watched the video, so for pace and shots the first todo is to watch the
     original (its link is on the post), unless viral.json has a structure.
   - **Copy the shape, never the reel.** Same hook grammar, same beats in the
     same order, same length within a few seconds, same energy. Never their
     words line for line, their footage or their edit: a re-upload or a
     word-for-word copy gets muted or reported, and it isn't the user's.
   - **The tone is the model's.** Do not soften it toward the user's old
     captions. Language: the audience's (account.md). A model in another
     language lends its shape, not its words.
   - `hook`: the model's hook rewritten for the user. Score 3 to 5 candidates
     with `ig-reel/hookscore.py` and keep the best; put its score in
     `hook.score`. The scorer reads English: for a Hindi, Hinglish or other
     non-English hook, keep the audience's language and treat the score as a
     guide, not a gate.
   - `script`: the model's structure as timed beats (`t`, `say`,
     `on_screen`, `shot`). Time it with `ig-reel/beats.py`.
   - `direction`: the director's notes for filming on a phone, in the same
     vocabulary as /ig-direct: `concept`, `mood`, `setup` (location, light,
     framing, wardrobe, props), numbered `shots` (frame, action, line,
     seconds), `delivery` tips, `takes`, and `avoid` (Instagram's buttons
     cover the bottom fifth and the right edge). Recreate the model's framing,
     cuts and look, concrete enough that a friend holding the phone could
     shoot it.
   - `caption`: the model's caption pattern under /ig-caption's rules (the
     first line survives "... more", one ask, 3 hashtags). Lint with
     `ig-caption/caption.py`.
   - `sound`: the model's sound if it is still usable, else /ig-audio's pick,
     with how to add it in Instagram.
   - `cover`: the cover text and which frame.
   - Carousels get `slides` instead of a script and shots.
   - Never invent facts: an event, a client, a number. Where the user has to
     supply one, the script says so in braces, like `{{your number}}`, and
     the shot tells them what to film.
   - Run every caption and script line through `ig-human/humanize.py`.
8. **Around the posts.** `stories` per day, the `engage` round, and `todo`:
   only what the user does with their hands (film, post, comment, send
   numbers), dated. Batch filming the day before, or two reels per setup.
   The first todo: watch the model reels (their links are on each post).
9. **Write and check.** Write `week.json` in the data folder, run `check
   --fix` until it says OK, then `plan-md` so plan.md, /ig-calendar and
   state.py stay in step.

End with three short lines: the headline, the first thing to do and when,
and what you assumed. The user changes anything by telling Claude; a change
to one post rewrites that post in `week.json` and runs `check` again.

## Daily: today's trend reel (IG Studio)

When the prompt says **Daily**, add one reel for one day that rides what
everyone is talking about. Ask nothing. About 5 minutes. The prompt names
the file, the post id and the date.

1. `python3 ~/.claude/skills/ig-trends/moments.py --region <R>`. Read the
   MOMENTs from the top. Skip deaths, attacks and disasters always, and
   politics, religion and court cases unless the account already posts them.
2. Pick the one with an honest bridge to the niche, using what the account
   really has (account.md, the week's kits). Write the bridge as a reel, not a
   pairing: what is on screen in the first second. If kweo is connected, one
   `ig-kweo-reader` "explore" job on
   `https://www.instagram.com/explore/search/keyword/?q=<words>` shows whether
   creators are already riffing on it; note the biggest one's link.
3. Write the post with the full kit, as in Autopilot step 7: hook, script,
   direction, caption, sound, cover, and a `model` from viral.json (the
   viral reel whose shape fits; if viral.json is missing, do /ig-viral's
   Autopilot first). Add `moment`: `name`, `hours_on_x`, `headline`, and
   `reel` (that link, if you saw one). Short: 10 to 25 seconds, one setup,
   filmable today. Add a todo to film it.
4. `week.py check --fix` until OK, and `plan-md` if it is the latest week.
5. If nothing fits, change nothing and end with `SKIP:` and why, naming the
   moments you passed on. A forced bridge is worse than no post.

## Today's post, end to end

For a **reel**: pick a model from `viral.json` → /ig-reel in its shape (hooks scored, script, beat sheet, humanized) →
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

- **Copy what went viral, not the account's past.** Posts take their hook,
  structure, pace and tone from reels that beat their own account in this
  niche (`viral.json`). The user's old posts and voice.md never set the style;
  voice.md gives only the language and the hard no's. Copy the shape, never
  the words, footage or edit.
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
