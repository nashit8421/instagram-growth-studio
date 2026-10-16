# Instagram Growth Studio

**27 Claude skills, seven agents and a one-click app that help you grow an Instagram account for free.**
Scan your account, find what's going viral in your region and niche, write and score
Reels, edit your raw video, pick a trending sound, track every post, and get a weekly
growth plan. Nothing is ever posted for you: these skills write, you post.

> **Built on [instagram-agent-skill](https://github.com/Jakeschincariol/instagram-agent-skill)
> by [Jake Schincariol](https://opusjake.ai).** His 13 skills, hook formulas, hook scorer,
> humanizer and research are the foundation of this repo, and his full commit history is
> kept here. This fork fixes a few bugs in the original (bug fixes offered back upstream)
> and adds 13 skills plus a desktop app on top. If you only want the original pack, use his repo.

## What's different from the original

| | Original | This fork |
|---|---|---|
| Skills | 13 | 27, including `/ig`, a single entry point that runs the rest in order |
| App | none | **IG Studio**: double-click, opens in your browser, everything has a button |
| Your account | you describe it | `/ig-scan` reads it (through your logged-in [kweo](https://kweo.ai) browser, your data export, screenshots, or the official API) |
| Results | free-text `log.md` | a real results log, audit in code, per-reel checks at 1h/24h/72h/7d with a diagnosis |
| Growth | weekly plan | a growth coach that finds your one bottleneck and ranks this week's actions |
| Trends | your niche | your region **and** your niche, blended into ideas, with brand-safety filtering |
| Sound | not covered | trending sound picks your account type can actually use |
| Hooks | scored | scored, then A/B tested with Instagram Trial Reels |
| Visuals | copy only | carousel and story PNGs, and raw video cut into a captioned 9:16 Reel |
| Video editing | none | **Claude directs**: a director and four specialist agents plan the hook, cuts, captions, look and sound, show you a scored storyboard, then render |
| Languages | English only (Hindi/Urdu scripts scored wrong) | any script |
| Accounts | one | several (yours and clients), kept separate |

## Quick start

**The app (easiest).** Download this repo (green **Code** button → **Download ZIP**, then unzip)
and double-click the launcher for your computer, right in the main folder:

| Mac | Windows | Linux |
|---|---|---|
| **IG Studio.app** | **IG Studio.bat** | **IG Studio.desktop** |

It opens in your browser. The first time, it offers to install the skills into Claude Code
with one click (any existing ones are backed up first). It needs Python 3.9+, and
[Claude Code](https://claude.com/claude-code) for the AI parts. More in [app/README.md](app/README.md).

**The skills, in Claude Code.**

```bash
git clone https://github.com/nashit8421/instagram-growth-studio.git
cp -r instagram-growth-studio/skills/ig* ~/.claude/skills/
cp instagram-growth-studio/platform.json ~/.claude/skills/
cp instagram-growth-studio/agents/*.md ~/.claude/agents/
```

Then type `/ig`. It scans your account, sets you up, and walks you through each step,
only stopping when it needs your input or approval.

Optional: [kweo](https://kweo.ai) lets the skills read your Instagram through the browser
you're already logged into, with no API keys. `/ig-kweo` shows how to connect it.
`ffmpeg` is needed for video editing and Chrome for carousel images. IG Studio sets up Whisper
for word-timed captions by itself on first launch (Homebrew's whisper-cpp on a Mac, otherwise a
private faster-whisper install in `~/.ig-studio`), in the background, with no admin password.

## All the skills

**Start here:** `/ig` runs everything in order.

| skill | what it does | from |
| --- | --- | --- |
| `/ig-scan` | Reads your account and works out niche, size, cadence and what performs | new |
| `/ig-grow` | Weekly growth coach: follower check-in, the one bottleneck, this week's actions | new |
| `/ig-trends` | What's viral in your region and niche, blended into "virality blast" ideas | new |
| `/ig-audio` | Trending sounds your account can use, matched to your reel | new |
| `/ig-reel` | Hooks from 26 formulas, scored; script; on-screen text; timed beat sheet | original |
| `/ig-test` | A/B test two hooks with Trial Reels, with an honest noise check | new |
| `/ig-direct` | Claude directs the edit: mood, hook, shots, captions, grade, sound. Storyboard first, render on your OK | new |
| `/ig-edit` | Quick edit: cut pauses, 9:16, captions, hook card | new |
| `/ig-caption` | The caption, linted against the feed cut and the 5-hashtag cap | original |
| `/ig-carousel` | Carousel copy, cover first | original |
| `/ig-render` | Carousel and story PNGs, grid-crop preview, alt text | new |
| `/ig-story` | The daily story sequence and stickers | original |
| `/ig-human` | Strips AI-sounding words and invisible characters, scores the draft | original |
| `/ig-ledger` | Results log for every post, audit in code | new |
| `/ig-perf` | Follows a reel through its first week and says how to fix it | new |
| `/ig-audit` | Post-mortem on what you posted | original |
| `/ig-plan` | The week: what, which format, when, who to engage | original |
| `/ig-calendar` | The plan as Google Calendar reminders (asks first) or an .ics file | new |
| `/ig-profile` | Profile scored out of 100, rewritten in fix-first order | original |
| `/ig-viral` | Outlier reels in your niche, ranked, as a swipe file and `viral.json`: every planned post copies one | original |
| `/ig-repurpose` | One long video or podcast into a week of posts | original |
| `/ig-comment` | Comments on other people's posts that read as a person | original |
| `/ig-reply` | Replies under your own posts, sorted by value | original |
| `/ig-dm` | Keyword delivery, first message, collab pitch, two follow-ups | original |
| `/ig-account` | Several accounts, each with its own data | new |
| `/ig-kweo` | Browsing through kweo, read only on Instagram | new |

Seven Claude Code agents ship in `agents/`: `ig-growth-coach` (weekly review),
`ig-kweo-reader` (reads Instagram through kweo with read-only tools, so it cannot like,
follow, comment or post), and the five-person edit crew below.

## Claude directs your video

Hand over raw footage. Claude acts as the director and fires up a crew:

```
raw.mov ─► direct.py analyze ─► word-numbered transcript · pauses · frame sheets
              │
   Director (Claude) ─► brief: concept, mood, hook, structure, length, loop
              │
   ig-cut-editor ─► shots by word range, hook first, filler cut, punch-ins, framing
              │  then in parallel
   ├ ig-caption-designer ─► font, size, colours, word highlight, placement per shot, hook text
   ├ ig-look-designer    ─► colour grade for the mood, vignette, progress bar, cover frame
   └ ig-sound-designer   ─► voice at -14 LUFS, whooshes on cuts, trending sounds to add in-app
              │
   direct.py merge + storyboard ─► real frames rendered with the real captions, zoom and grade
              │                     + a virality checklist scored out of 100
   ig-retention-critic ─► watches it like a scroller, sends fixes back, one more round
              │
   You approve the storyboard (or say what to change) ─► direct.py render ─► reel.mp4 + cover
```

The checklist covers what keeps people watching: something to read or hear by 0.4s,
hook text on frame 1 (the feed thumbnail), the strongest line first, a visual change
at least every 4.5s, no dead air, captions big and short and clear of the face and the
Instagram buttons, a payoff and a loop, one ask, and no unlicensed music burned in.
In IG Studio, drop the footage into a planned post's **Edit it** step: the director uses
that post's hook and script as the brief and renders straight away (you can still
change it and re-render). From the command line, nothing renders until you approve the
storyboard. Nothing is ever posted.

## Safety, plainly

- Nothing is posted, liked, followed, commented or sent. Every skill ends in text or
  files you post yourself. Automating those actions breaks Instagram's Terms and gets
  accounts restricted.
- Browsing Instagram is read only, at human pace, in your own logged-in session.
- One exception you trigger yourself: **Fix all with kweo** on the Account page. You
  tick each profile change (name and bio), can edit the text, confirm, and
  kweo's `ig-profile-editor` makes exactly those changes, checking it is on the right
  account first and stopping at any security prompt. A dry run checks everything
  without saving. Pins, highlights, covers and links can only be changed in the app (the
  website has no pin option), so you get a copy-ready list for those.
- Everything runs on your machine. IG Studio listens on 127.0.0.1 only, behind a
  per-launch token.
- No one can promise a reel goes viral. These tools improve the odds and measure what
  works for your account.

---

*The sections below are from the original pack's README by Jake Schincariol, updated where
the fixes changed behaviour.*

## The five tools that actually run

No dependencies, no network, nothing uploaded. They run on your machine, on
your text.

### Hooks

```bash
python3 hookscore.py hooks.txt              # rank your options
python3 beats.py script.txt --target 30     # time it before you shoot it
```

```
HOOK RANKING
==============================================================================
->  85.6 STRONG  Nobody tells you that your first 30 reels are supposed to f...
        weakest: SPECIFICITY (75)
    81.4 STRONG  I lost $18,000 because of one missing contract.
        weakest: ADDRESS (70)
    54.4 OK      Stop scrolling if you want to grow on Instagram in 2026 🔥
        weakest: STAKES (70)
        dealbreaker: Opens with "stop scrolling". Asking for attention proves
                     you have not earned it.
     9.6 WEAK    Hey guys, today I wanted to talk about content strategy
        weakest: FRONTLOAD (0)
        dealbreaker: Greeting. Nobody came to the feed to be greeted.
```

`beats.py` estimates how long each line takes to say, stacks them into
timecodes, and flags the four things that kill a Reel in the edit: a hook that
runs past three seconds, a beat long enough for the viewer to leave, a run of
lines with nothing concrete in them, and no loop back to the first line.

```
BEAT SHEET  ·  73 words  ·  ~26.6s at 165 wpm  ·  target 30.0s
========================================================================
  0:00.0   2.9s  HOOK    I lost $18,000 because of one missing contract.
  0:02.9  14.6s  MID     Here is the exact clause I now put in every single...
                         ^ 14.6s on one beat
  0:17.4   2.9s          Section 4. Payment on delivery, not on approval.
  0:20.4   2.9s          Approval is a feeling. Delivery is a date.
  0:23.3   3.3s  CTA     That one word change is worth $18,000 to me.
------------------------------------------------------------------------
  - Beat 2 runs past 4s. Either split the line or change what is on screen
    inside it. A static frame is where people leave.
  - Loops: the last beat repeats "$18,000" from the hook. Second watches are
    free reach.
  - 3.5s under target. Either add 9 words or shoot it short. Short is usually
    right.
```

### The caption

```bash
python3 caption.py caption.txt --keywords "client contracts,freelance pricing"
```

Instagram gives a caption about 125 characters in the feed and hides the rest
behind a tap. Almost every caption that fails, fails there. So the first thing
this prints is that window, as a box, the way a scrolling stranger reads it:

```
  WHAT THE FEED SHOWS
  +------------------------------------------------------+
  | I lost $18,000 because of one missing clause in a    |
  | contract, and the worst part is that I had read the  |
  | thing twice before I si                              |
  +-------------------------------------------- ... more +

  PASS  LENGTH            389 / 2200 characters
  WARN  FIRST LINE        133 characters, so it gets cut at 125 mid-thought
  PASS  HOOK IS CONCRETE  2 numbers or names in the visible window
  PASS  HASHTAGS          3 tags: #freelance #contracts #agencyowner
  PASS  ONE ASK           one call to action: comment a keyword
  WARN  SEARCH TERMS      1/2 present. Missing: client contracts
```

It enforces the current hashtag cap, which is **five per post**, not thirty.
Instagram cut it on 18 December 2025.

### The humanizer

```bash
python3 humanize.py draft.txt --report      # clean it, show every change
python3 detect.py draft.txt                  # score it, five checks
python3 detect.py before.txt after.txt       # prove the delta
```

**What comes out automatically:**

- **Invisible characters.** Zero-width spaces and joiners, word joiners, soft
  hyphens, byte-order marks, Unicode tag characters, invisible separators,
  non-breaking and narrow spaces. Your keyboard does not make these. They
  survive copy-paste and they are invisible in every editor you own.
- **Typography.** Em dash to comma, en dash to hyphen, curly quotes to
  straight, ellipsis to three dots, and the orphaned punctuation that leaves.
- **The lexicon.** 154 stock words and phrases with plain-English replacements.
  The last block of it is Instagram-specific: "stop scrolling", "in today's
  video", "follow for more", "tag someone who needs this", "the algorithm
  loves", "run don't walk". It lives in
  [`slop.json`](skills/ig-human/slop.json) and it is meant to be edited.

**What gets flagged instead of fixed:** "It's not just X, it's Y", rule-of-three
triads, the video preamble, emoji bullet lists, three shouted words in a row,
hashtag walls, reflex follow bait, uniform sentence length. Changing the shape
of a sentence needs judgement, so those come back for a rewrite rather than
getting mangled by a regex.

Run against a caption written to be as bad as possible:

```
  BURSTINESS    ###################.....  78.4
  SPECIFICITY   #############...........  53.6    3.4 concrete markers per 100 words
  SLOP DENSITY  ........................   0.0    20 stock terms, 23.0 per 100 words
  FINGERPRINT   ################........  68.7    1 em dash
  VOICE         #################.......  70.0    9 structural tells
  ------------------------------------------------------------
  HUMAN SCORE   ########................  32.5   FLAGGED
```

After `humanize.py`, with the flagged structures still unrewritten:

```
  HUMAN SCORE   ###################.....  79.7   PASS    (+47.2)
```

### The swipe file

```bash
DATA=$(python3 ~/.claude/skills/ig-account/account.py path)
python3 swipe.py captured.tsv --out "$DATA/swipe.md"
```

Raw views are not evidence. A 2,000,000-follower account doing 400,000 views
had a quiet Tuesday. A 4,000-follower account doing 400,000 views found
something. `swipe.py` ranks on the multiple over each account's own median,
names the hook formula, and prints what separates the top third from the
bottom third.

```
SWIPE FILE  ·  4 reels  ·  4 accounts  ·  baseline: account median
==============================================================================
    60.0x  hook  57  #9  The Steal              @c                 180,000
           "steal this four line follow up it took me two years"
    37.5x  hook  86  #3  Nobody Tells You       @a                 412,000
           "nobody tells you that your first 30 reels are supposed to flop"
     1.3x  hook  13  -   unclassified           @b               1,200,000
           "in this video I am going to show you my morning routine"
```

## What I actually measured, which is the part worth reading

I did not want to publish a hook scorer on the claim that it feels right, so I
tested it. The corpus is **74 real short-form hooks**: the first three seconds
of the auto-caption track from the top eight and bottom eight performing shorts
on each of five channels, view counts from 931 to 550,000.

They are YouTube Shorts rather than Reels, because Instagram does not hand you
view counts you can collect without logging into somebody's account, and
scraping it would violate the Terms this repo tells you not to violate. The
hook grammar is the same and the sourcing is public. That is a real limitation
and it is stated here rather than buried.

**Three results, two of them uncomfortable:**

**1. It catches bad hooks well.** Against ten hooks written deliberately badly,
AUC 0.83, and nine of the ten scored below the median of the real corpus. If
your hook opens on a greeting, a preamble or nothing concrete, this tells you.

**2. It does not pick winners.** Separating a good creator's hits from that
same creator's misses: **AUC 0.56, where 0.50 is a coin flip.** Of the five
checks, only SPECIFICITY separated the bands meaningfully, by 60 points of
median. STAKES and ADDRESS had identical medians in both bands, which means on
this corpus they measured nothing.

So the honest use is: kill the obviously weak hooks before you shoot them, then
trust your own retention graph. Nothing that reads text can tell you which of
two decent hooks will travel, because that is decided by your face, your edit,
your audio and who Instagram shows it to.

**3. The formula classifier was broken and the test is what caught it.** The
`match` regexes in `hooks.json` were written off my own templates, and they
named **8%** of real hooks. People do not speak in templates. Rewriting them
against actual transcribed speech took it to **49%**, and four formulas went
into the set because they kept appearing and were not there: Contrarian Flip,
The Statistic, The Reveal, Someone Else's Result, plus The Superlative. On the
other 51% it abstains, which is correct: a lot of short-form is podcast clips
that have no hook formula at all.

One fixed bug worth naming: `SPECIFICITY` only counted digits, so "zero
dollars" and "three marketing books" scored as having nothing concrete in them.
Spoken hooks say their numbers out loud.

If you re-run this on a bigger or cleaner corpus and get a different answer, I
would rather know. The measurement script is not in the repo because it depends
on `yt-dlp`, but the method is four lines and is written out in
[`/ig-viral`](skills/ig-viral/SKILL.md).

## The fine print, which is the honest part

**These skills do not post to Instagram.** There is a real Content Publishing
API for professional accounts. With the Instagram API with Instagram Login it
needs no Facebook Page, and an app used only for accounts you own or manage
runs on Standard Access with no App Review. It still needs a professional
account, a Meta developer app and a token, which is not a thing a skill can
hand you. Everything else people use to automate posting, commenting, following or
DMing is browser automation or a third-party tool, and both violate
[Instagram's Terms of Use](https://help.instagram.com/581066165581870) and get
accounts action-blocked. So every skill here ends the same way: a copy-ready
block, and you post it. That is not a limitation bolted on afterwards, it is
the design, and it is why the approval gate is real rather than a setting.

The one exception is keyword auto-replies in DMs, which Instagram supports
through its own tools and approved partners, and which only fire after somebody
comments first. `/ig-dm` says where that line is.

**`/ig-viral` reads, it does not scrape.** Ten accounts, a dozen reels each, at
human speed, with you driving your own browser. It never asks for your password
and never logs in as you. Automated collection at volume is the thing that gets
accounts restricted, and a crawler is not what this is.

**The five detection checks are local heuristics, not detector APIs.** They are
modelled on the signals public detectors key on and they run entirely on your
machine. They are not GPTZero, Originality, Copyleaks, Winston or Turnitin,
they do not call those services, and they cannot promise those verdicts. Fixing
what they measure tends to move those numbers, because they are measuring the
same underlying things. That is the whole claim. Nobody can honestly sell you
"undetectable", and anybody who does is selling you something.

**The invisible-character pass is real and it is narrow.** It removes the
zero-width and format characters that end up in generated text and survive a
copy-paste. That is a genuine, checkable fingerprint. It is not a claim about
defeating a cryptographic watermarking scheme, and this repo does not make one.

**Nothing here fabricates.** No invented metrics, clients or outcomes go under
your name. If a draft needs a number you have not given, it comes back with
`{{your number}}` in it and a flag, every time.

**Platform numbers go stale.** The hashtag cap moved from 30 to 5 in December
2025 while this repo was being written, and the linter had the old number in it
until the fact got checked. If something here contradicts what Instagram is
doing when you read it, Instagram is right.

The numbers now live in one place: [`platform.json`](platform.json) at the
repo root. Hashtag cap, caption limit, feed cut, carousel size, safe zones and
Reel length, each with the date it was last checked and a source where there
is one. `caption.py` reads its limits from it. When Instagram moves a number,
change it there.

## Credit

The original 13 skills, the hook formulas, the hook scorer, the humanizer, the beat
timer, the caption linter, the swipe-file ranking and the measurement work are by
**Jake Schincariol**, [opusjake.ai](https://opusjake.ai):
[instagram-agent-skill](https://github.com/Jakeschincariol/instagram-agent-skill).
His sibling repo for LinkedIn:
[linkedin-agent-skill](https://github.com/Jakeschincariol/linkedin-agent-skill).

The fixes, the 13 new skills, the agents and IG Studio are by
[nashit8421](https://github.com/nashit8421), built with Claude Code.

## License

MIT, same as the original. See [LICENSE](LICENSE).
