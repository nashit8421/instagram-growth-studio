# IG Studio

A local app for the ig- Instagram skill pack. Double-click it and it opens in your
browser. Type a handle once; from then on Claude prepares each week by itself and the
app shows it.

- **This week** (home): the week's posts by day, today's to-dos, the comment round.
  Each post opens as a kit: **Say this** (hook, timed script, a teleprompter),
  **Film it** (the director's setup and shot list), **Edit it** (drop the footage;
  Claude's director cuts, captions, grades and renders the Reel), **Post it** (the
  caption to copy, the sound, the cover, and "I posted it", which logs it).
- **Results**: the account scan, every post and its numbers, follower growth, and
  **Viral & trends**: the reels going viral in your niche (the ones your posts copy),
  trends and sounds.
- **Ask Claude**: a side panel, for changes ("make Thursday funnier") or anything else.
- **Settings** (the gear): accounts, profile details, the hand tools (hook scorer,
  script timer, caption checker, humanizer, carousel maker, video editor), system checks.

How the week gets made: when there is no plan for the coming week (Mon to Wed: this
week; Thu to Sun: next week) and Claude Code is installed, the app starts an
**autopilot** run on its own: it scans the account if needed, finds the growth
bottleneck, finds the reels going viral in your niche (ranked by how far each beat
its own account), checks trends, and gives every post the hook, structure, pace and
tone of one of those viral reels, not your old posts. Each post links the reel it
copies. It writes every kit into `week.json`
(see the ig skill's Autopilot section; `skills/ig/week.py` checks it). A run that
fails is not retried automatically for 6 hours; the page says why and offers a button.
Each run costs Claude usage, roughly one long session per week per account.

Every day, the first time the Week page opens (after 6pm it is for tomorrow),
Claude also reads what everyone is talking about (`skills/ig-trends/moments.py`:
X trends over 24 hours and Google News top stories) and, when one moment has an
honest bridge to the niche, adds **today's trend reel** to the week with its full
kit. When nothing fits it says why and adds nothing. About 5 minutes of Claude a
day per account.

## Start it

The launchers are in the repo's main folder, next to this `app/` folder.

**Mac**
1. Double-click **IG Studio.app** (runs quietly in the background), or **IG Studio.command** (shows a Terminal window).
2. Your browser opens IG Studio. First time macOS asks, right-click → Open.
   If the folder is in Desktop, Documents or Downloads, macOS privacy blocks the app from
   reading it, so IG Studio opens through Terminal instead (allow access if asked). To
   avoid the Terminal window, move the folder to your home folder.
3. Stop it with Settings → Quit (or close the Terminal window for the .command).

**Windows**
1. Double-click **IG Studio.bat**.
2. Your browser opens IG Studio. No Python? It tells you: `winget install Python.Python.3.12`.
3. Stop it with Settings → Quit.

**Linux**
1. Double-click **IG Studio.desktop** (allow launching if asked), or run `./ig-studio.sh`.
2. Your browser opens IG Studio.
3. Stop it with Settings → Quit, or Ctrl+C in the terminal.

Power users: `python3 app/server.py --no-browser --port 8765` prints the private URL.
Launching again while it runs just reopens the running one.

## What you need

- Python 3.9 or newer (nothing to pip install).
- The ig skills in `~/.claude/skills` (or set `IG_SKILLS_DIR`).
- [Claude Code](https://claude.com/claude-code), logged in with your Claude
  subscription. It prepares the week; without it, Results, Settings and the hand tools
  still work.
- Optional: ffmpeg (video editor), Google Chrome (carousel images), Whisper (word-timed
  captions), kweo (lets Claude read Instagram in your own logged-in browser). Settings
  shows what's found and how to add what's missing.

## Privacy

- Runs only on your computer at `127.0.0.1`. The page needs the private link the
  launcher opens (a random token, new each start); other sites and other pages can't
  talk to it.
- **Nothing is ever posted, liked, followed, commented or sent.** Every tool ends in
  text or files that you post yourself.
- Your data stays in the skills' data folder (`~/IGStudio`, one folder per
  account). Settings → Open folder shows it.
- Only Claude goes online: reading the account in kweo and researching trends while it
  prepares the week, and your Google Calendar only after you say yes in the chat. An
  Instagram API token (Results → Account → Rescan → API token) is passed
  to the scanner for that one run and never saved.

## For developers

- `server.py`: stdlib HTTP server, job runner with SSE progress, runs the skill
  scripts with `IG_DATA_DIR` set to the active account. Claude runs use
  `claude -p --output-format stream-json` with a fixed tool allowlist and `--resume`
  for follow-ups.
- `web/`: plain HTML/CSS/JS, no build step, works offline.
- Tests (temp folders and a fake `claude` only): `python3 -m unittest discover -s tests`.
- Env: `IG_HOME`, `IG_SKILLS_DIR`, `IG_CLAUDE_BIN`, `IG_STUDIO_HOME` (lock file, default `~/.ig-studio`).
