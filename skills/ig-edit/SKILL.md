---
name: ig-edit
description: >-
  Turn the user's raw footage into a Reel on their own Mac - cut the pauses,
  crop to 9:16, burn in captions inside the safe zone, put the hook card up
  from frame 1, and write an Instagram-safe 1080x1920 MP4. Use when the user
  says "edit my video", "cut this into a reel", "cut the pauses", "add
  captions to my video", "make this vertical", "turn my recording into a
  reel", or hands over a raw .mov or .mp4 file. Also cuts clips out of a long
  video for /ig-repurpose.
---

# ig-edit

The quick cut. For a directed edit (mood, cold open, caption design, grade,
sound, a storyboard to approve first) use /ig-direct.

/ig-reel writes the script. The user shoots it. This turns the recording into
the file they upload. It runs ffmpeg on their machine. Nothing is uploaded and
nothing is posted.

```bash
python3 edit.py raw.mov --out reel.mp4 --cut-silence --script script.txt \
    --hook-text "5 HOURS -> 20 MIN"
python3 edit.py long.mp4 --out clip.mp4 --start 00:14:20 --end 00:14:58 --cut-silence
python3 edit.py raw.mov --out reel.mp4 --dry-run          # the plan, no encode
python3 cover.py reel.mp4 --at 1.2 --out cover.jpg        # cover frame
```

ffmpeg is required. If it is missing, the script says `brew install ffmpeg`
and stops. Do not install it for the user. Ask.

## What it does

1. **Probes** the file: length, size, rotation, frame rate, audio.
2. **Cuts the pauses** with `--cut-silence`. A pause goes when it is quieter
   than `--silence-db` (-35) for at least `--min-silence` (0.45s). Each kept
   stretch keeps `--pad` (0.12s) either side. Cut on the sentence, not on the
   breath: a breath is shorter than 0.45s, so it stays. Gaps under 0.2s are
   not worth a jump cut and are merged.
3. **Frames it 9:16** at 1080x1920. Landscape gets a centre crop. `--crop
   none` fits the whole frame on a blurred copy of itself. `--crop auto` (the
   default) centre-crops anything up to 2:1 and blur-fits wider than that.
4. **Captions**, from the first of these it has:
   - `--srt FILE`, timed against the input file. It is remapped through the cuts.
   - a local Whisper: `whisper-cli` / `whisper-cpp` with a ggml model,
     `mlx_whisper`, `faster_whisper`, or the `whisper` CLI. Word timing.
   - `--script FILE`, one line per beat, spread over the speech. If the number
     of lines matches the number of pauses, line N goes on stretch N.
     Otherwise it is spread by word count. **Approximate.** The report says so.
5. **Burns them in** as ASS: bold white, dark outline, six words or fewer per
   card, broken at commas where it can. Bottom of the safe zone, clear of the
   right 230px. `--captions srt` writes the .srt only, for Instagram's own
   caption tool. `--captions none` skips them.
6. **Hook card** with `--hook-text`: up from frame 1 for 2.5 seconds, upper
   middle of the safe zone, white on a dark box. `->` becomes an arrow.
7. **Encodes** H.264 High, yuv420p, 30 fps, about 9 Mbps, AAC 48 kHz,
   `+faststart`. A file with no audio gets a silent track.
8. **Writes** next to `--out`: the MP4, `.srt`, `.ass`, `edit-report.json`,
   and `check/` with three PNG frames that have the covered parts of the
   screen shaded red. `--cover-at 1.2` also saves `reel-cover.jpg`.

Other flags: `--max-length 90` (over it, the tail is dropped at a pause),
`--lang en` for Whisper, `--no-transcribe`, `--no-check-frames`, `--preset
fast|medium|slow`, `--json`.

## The flow

**From /ig-reel.** The user shot the script. They hand over the file.

1. Save the script exactly as written in the REEL READY block, one line per
   beat, to `script.txt` next to the footage. Take the hook card text from the
   on-screen list, the first card.
2. Run a dry run first on anything long. It is quick and shows the cuts:

   ```bash
   python3 edit.py raw.mov --out reel.mp4 --cut-silence --script script.txt \
       --hook-text "5 HOURS -> 20 MIN" --dry-run
   ```

3. Run it for real, without `--dry-run`.
4. **Look at the frames before handing it over.** Read the three PNGs in
   `check/` with the Read tool. If you need another moment, take it:

   ```bash
   python3 cover.py reel.mp4 --check 0.5 5 12 --out-dir check
   ```

   Check for:
   - the hook card readable at frame 1, nothing touching the red
   - a caption over the user's face or a product on screen
   - a caption on screen when the wrong line is being said (script captions)
   - a centre crop that cut the user out of frame. Re-run with `--crop none`.

   If the captions are wrong, fix the cause: a better script split, an SRT,
   or `--crop none`. Do not hand over a file you have not looked at.
5. **The user watches it.** Say what to watch for: the cuts, and the caption
   timing if it came from the script.
6. **Log it.** On "yes", hand over to `/ig-ledger` with the hook formula, the
   first line and the output length from the report. It prints the post id.

**From /ig-repurpose.** The user has a long video and you have the
timestamps of the moment. Cut it out and edit it in one go:

```bash
python3 edit.py podcast.mp4 --out tue.mp4 --start 00:14:20 --end 00:14:58 \
    --cut-silence --hook-text "STOP RUNNING DISCOVERY CALLS"
```

Start a second or two early and end late. The silence cut trims the dead
edges. An SRT of the long video still works: its times are read against the
input file, so pass it as it is.

## Reading the report

```
EDITED  ·  reel.mp4
======================================================================
  input       raw.mov  1920x1080 landscape, 30 fps, 20.0s, audio
  length      20.0s -> 14.6s
  cut         5.4s in 5 cuts  (quieter than -35 dB for 0.45s+, 0.12s pad)
  first word  0.13s
  frame       1080x1920, centre crop, H.264 high + AAC, 30 fps
  hook card   "5 HOURS -> 20 MIN"  0:00.0 - 0:02.5
  captions    6 cards, burned in, from script
              approximate: 3 lines spread over 4 speech runs by word count
```

| warning or symptom | what to do |
| --- | --- |
| dead air before hook | the first word is after 0.5s. Use `--cut-silence` or a later `--start` |
| over 90s | 15 to 45s is the working range. Cut a beat, or split it into two Reels |
| under 7s | the loop counts inflate and nothing else does |
| timed from the script | watch the captions through. An SRT or Whisper fixes it |
| blown up a lot | the crop is enlarging a small picture. Shoot vertical next time |
| no sound above -35 dB | the mic was off or quiet. Try `--silence-db -45` |
| cut too much, words clipped | raise `--pad` to 0.2, or `--min-silence` to 0.7 |

## Whisper

IG Studio installs it on every start if it is missing (whisper.cpp and the
multilingual base model on a Mac with Homebrew, a private faster-whisper
elsewhere). This script never installs anything. With whisper.cpp it asks for
token-level timing (`--dtw`), which puts word starts within a frame or two.
`python3 edit.py --whisper-check` says what it found. Without it, captions come
from `--script` (approximate) or are skipped, and the report says so.

Models are looked for in `$WHISPER_MODEL`, the data folder's `models/`,
`~/.ig-studio/models`, `~/.cache/whisper.cpp` and Homebrew's share folder.

The data folder is `$IG_DATA_DIR`, else the active account's folder under
`~/IGStudio/accounts/`, else `~/IGStudio`.

## Honest limits

- **No B-roll.** It cuts and captions the footage it is given. Frame changes
  every beat still have to be shot.
- **No music.** Add it in Instagram, where the tracks are licensed. Music
  burned in here can get the Reel muted.
- **Script captions are approximate.** They are spread over where the user was
  talking, not matched to the words. Without Whisper or an SRT, say so.
- **Silence is not the same as a finished sentence.** A long thinking pause
  mid-sentence gets cut. Room noise above -35 dB means nothing gets cut.
- **The crop is dumb.** Centre crop does not follow a face. If the user stood
  off-centre, use `--crop none`.
- **No colour, no stabilisation, no zooms.** Do those in an editor if needed.
- **Never posts.** The user uploads it.

## Tests

```bash
python3 -m unittest discover -s tests
```

They make their own test clips with ffmpeg in temp folders and never touch
`~/IGStudio`.
