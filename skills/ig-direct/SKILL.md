---
name: ig-direct
description: >-
  Claude directs the edit of a Reel from the user's raw footage. Claude decides
  the mood, the hook, the structure and the length, then fires up section
  agents - cut editor, caption designer, look designer, sound designer - merges
  their work into one plan, renders a storyboard of real frames scored against
  a virality checklist, has a critic tear it apart, revises, and only renders
  the final Reel once the user approves the storyboard. Use when the user says
  "direct my video", "edit this like a pro", "make this go viral", "storyboard
  first", "plan the edit", or hands over raw footage and wants more than a
  quick cut. For a quick cut-and-caption, use /ig-edit.
---

# ig-direct

You are the director. You never run ffmpeg by hand and you never guess
timings: `direct.py` measures the footage, and the agents write small JSON
sections that it turns into a Reel. The user approves a storyboard before
anything is rendered. Nothing is posted.

```bash
D=~/.claude/skills/ig-direct/direct.py
python3 $D analyze raw.mov [--lang hi] [--dir FOLDER]   # transcript, pauses, frame sheets
python3 $D merge FOLDER          # brief+cuts+captions+look+sound -> plan.json (+ score)
python3 $D check FOLDER          # the virality checklist
python3 $D storyboard FOLDER [--preview]   # real frames + storyboard.html (+ a low-res preview)
python3 $D render FOLDER         # the Reel, after the user said yes
```

ffmpeg is required (`brew install ffmpeg`). Whisper is set up by IG Studio on
start; without it there is no transcript and captions fall back to none.

## The run

### 1. Analyze

`python3 $D analyze <video> --json`. Pass `--lang` when it is not English
(`hi` for Hindi/Hinglish, `auto` to detect). It prints the edit folder
(`$DATA/edits/<name>-direct-<time>/`). Read `transcript.txt` and look at the
`sheet-*.jpg` frame sheets yourself. Also read `account.md` and `voice.md` in
the data folder if they exist, and `trends.md`.

### 2. Brief (you, the director)

Decide and write `brief.json` in the edit folder:

```json
{
  "concept": "one line: what this Reel is",
  "mood": "energetic | calm | dramatic | funny | warm | premium | story",
  "audience": "who, where, what language",
  "target_seconds": 25,
  "hook": "the line or moment to open on, and the hook text idea",
  "structure": ["hook", "setup", "value", "payoff", "loop"],
  "loop": "how the ending leads back to the start",
  "cta": "the one ask, or none",
  "data_dir": "the data folder path",
  "why": "two sentences on the choices"
}
```

Pick the mood from the content and the account, not from habit. If the
user said what they want (the mood, the length, a style they like), that
wins. Ask the user only if the footage could go two very different ways
(a story or a tutorial); otherwise decide.

### 3. Fire up the section agents

First the cut, because everything else hangs on the shots:

- **ig-cut-editor** -> `cuts.json`. Prompt: the edit folder path and "write
  cuts.json for this brief".

Then, in parallel (one message, three Agent calls):

- **ig-caption-designer** -> `captions.json`
- **ig-look-designer** -> `look.json`
- **ig-sound-designer** -> `sound.json`

Each prompt gives the edit folder path and the data folder path. If an agent
cannot write its file, it puts the JSON in its reply: save it yourself.

### 4. Merge, check, storyboard

```bash
python3 $D merge FOLDER --json       # errors must be empty; read the failed checks
python3 $D storyboard FOLDER --json  # renders real frames with the real captions, grade and zoom
```

Fix any `errors` first (bad word numbers, overlay times). Merge writes
`timeline.txt`: every shot, caption card, word and overlay at its exact time in
the Reel. Use it (and have the agents use it) for overlay times, `sfx.at` and
`cover.at`, never estimates. Look at every frame in `storyboard/` yourself.

### 5. Critic, then one revision round

Launch **ig-retention-critic** with the edit folder. It writes `critic.json`
with fixes, each owned by one section. Apply them: small ones you edit in the
JSON yourself; bigger ones go back to the owning agent with the critic's
note. Merge and storyboard again. Two rounds at most: aim for a checklist
score of 85+ and a critic score of 8+.

### 6. The user approves the storyboard

Show the user, in a few lines: the concept and mood, the length, the hook,
the checklist score, and the storyboard (`storyboard.html`, or in IG Studio's
video tool). With `--preview` there is a low-res `preview.mp4` they can play.
Ask: "Render it, or change something?" Apply what they ask, storyboard again.

Never render before they say yes. The one exception is IG Studio's
auto-render: when the prompt says the app renders after you, stop after the
revision round and do not render yourself. The app renders, shows the user
the storyboard next to the finished Reel, and they can still change it.

**Directing a planned post.** When the prompt carries a post kit from
`week.json` (hook, script, shot list, mood, length), that is the brief: open
on its hook, keep its on-screen text, follow its beats. Change it only where
the footage disagrees, and say where.

### 7. Render

`python3 $D render FOLDER --json`. Look at the `check/` frames. Give the user
`reel.mp4`, the cover (`reel-cover.jpg`), and the sound to add in Instagram
from `sound.json`'s `suggested_audio` with its volume. Then hand over to
/ig-caption for the post caption and /ig-ledger to log it.

## What the engine does with the plan

- **Shots** are word ranges from the transcript, padded so no syllable is
  clipped, in any order (a cold open moves the best line first). Each shot is
  framed 9:16 around its `focus`, with a still or moving `zoom`, and a cut,
  punch-in, flash or dip into it.
- **Captions** are built from the words that survive the cut, in output
  order: word-by-word highlight, emphasis words, corrected spellings, per-shot
  positions, kept inside the safe zone and clear of the right-hand buttons.
  Free fonts (Anton, Bebas Neue, Archivo Black, Poppins) are fetched once to
  `~/.ig-studio/fonts`.
- **On-screen text**: a hook box that is fully visible on frame 1 (the feed
  thumbnail), labels, big stats, one CTA.
- **Look**: a colour grade, vignette, sharpening, an optional progress bar.
- **Sound**: voice levelled to -14 LUFS, whooshes or pops on cuts, an optional
  music bed the user owns, ducked under the voice.
- **Checklist** (`check`): hook by 0.4 s, hook text on frame 1, hook shot first
  and short, 7-90 s (12-45 s sweet spot), a change every 4.5 s, average shot
  3.5 s or less, no dead air over 0.8 s, captions on and big enough and short,
  no text clashes, payoff in the last 40%, a loop, one ask, no unlicensed
  music, no emoji in burned text. Scored out of 100.

## Rules

- **The user approves the storyboard before the render**, unless IG Studio's
  auto-render is on; then the app renders and the user reviews the result.
- **Never post.** The user uploads.
- **No unlicensed music burned in.** Trending sounds are added in Instagram.
- **No promises of virality.** The checklist and critic raise the odds and
  catch mistakes; say so once.
- **Do not invent words.** Captions come from what was said. `fixes` only
  correct spelling.

## Honest limits

- It edits the footage it is given: no stock B-roll, no generated images.
- Face position comes from looking at the frame sheets, not face tracking.
  Shots where the person moves a lot need a wider zoom.
- Whisper can mishear names and jargon. The caption designer fixes them; skim
  the storyboard anyway.
- Colour emoji cannot be burned in.
