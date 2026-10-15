# IG Studio

A friendly local app for the ig- Instagram skill pack. Double-click it, it opens in
your browser, and everything the skills do has a button: today's next steps, your
account scan, a chat with Claude that runs the skills, instant tools (hook scorer,
script timer, caption checker, humanizer, carousel maker, video editor), your post
ledger, growth chart, trends, sounds and the week's calendar.

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
- For the Assistant: [Claude Code](https://claude.com/claude-code), logged in with your
  Claude subscription. Without it, every non-AI screen still works.
- Optional: ffmpeg (video editor), Google Chrome (carousel images), Whisper (word-timed
  captions), kweo (lets Claude read Instagram in your own logged-in browser). Settings
  shows what's found and how to add what's missing.

## Privacy

- Runs only on your computer at `127.0.0.1`. The page needs the private link the
  launcher opens (a random token, new each start); other sites and other pages can't
  talk to it.
- **Nothing is ever posted, liked, followed, commented or sent.** Every tool ends in
  text or files that you post yourself.
- Your data stays in the skills' data folder (`~/.claude/instagram`, one folder per
  account). Settings → Open folder shows it.
- Only Claude goes online, and only when you ask: research, and your Google Calendar
  after you say yes in the chat. An Instagram API token (Account → Advanced) is passed
  to the scanner for that one run and never saved.

## For developers

- `server.py`: stdlib HTTP server, job runner with SSE progress, runs the skill
  scripts with `IG_DATA_DIR` set to the active account. Claude runs use
  `claude -p --output-format stream-json` with a fixed tool allowlist and `--resume`
  for follow-ups.
- `web/`: plain HTML/CSS/JS, no build step, works offline.
- Tests (temp folders and a fake `claude` only): `python3 -m unittest discover -s tests`.
- Env: `IG_HOME`, `IG_SKILLS_DIR`, `IG_CLAUDE_BIN`, `IG_STUDIO_HOME` (lock file, default `~/.ig-studio`).
