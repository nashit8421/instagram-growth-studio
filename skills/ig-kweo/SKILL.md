---
name: ig-kweo
description: >-
  The browsing layer for the Instagram pack. How every other ig- skill reads
  the web: kweo first, then whatever browser this session has, then public
  fetches, then asking the user to paste. Also sets kweo up. Use when the user
  says "set up kweo", "connect kweo", "browse for me", "kweo isn't working",
  or when /ig-viral, /ig-trends or any other skill needs to look at a page.
---

# ig-kweo

kweo is the user's own AI browser. It can run a local MCP server so Claude
drives it. The user is already logged in there, so Claude can read what they
can read without ever touching a password.

This skill does two things. It says how the rest of the pack browses. And it
gets kweo connected when it is not.

## Instagram rules. Read these first. They are not negotiable.

These apply to kweo, Claude in Chrome, the built-in browser, computer use, and
anything else that can click.

- **Read only.** Never post, like, follow, unfollow, comment, reply, DM, save,
  share, report, or accept a request. Not once, not "just to test".
- **This includes `browser_run_task`.** kweo's agent will act on a goal, so
  every goal on Instagram is phrased as reading. Always end it with:
  *"Read and report only. Do not click like, follow, comment, save, share or
  send. Do not type into any box."*
- **Human speed.** A handful of pages per session. Pause between pages. Scroll,
  read, move on. Ten accounts and a dozen reels each is the ceiling, not the
  target.
- **The user is present.** Browse while they are at the keyboard, so they see
  what is opened and can stop it.
- **Never log in for the user. Never ask for a password, a code or a cookie.**
  If a page wants a login, stop and tell the user. They log in themselves, in
  kweo, by hand.
- **No background loops, no schedules, no crawlers** on Instagram. Nothing
  that runs while the user is away. Automated collection breaks Instagram's
  Terms and gets accounts action-blocked.

Public, non-Instagram sources (Google Trends, TikTok Creative Center, YouTube,
news sites) are fine at normal browsing pace. Still read only. Still no
logging in on the user's behalf.

## Which browser to use, in order

1. **kweo MCP tools**, if they are in this session. They are named
   `mcp__kweo__browser_navigate`, `mcp__kweo__browser_read`,
   `mcp__kweo__browser_tabs`, `mcp__kweo__browser_new_tab`,
   `mcp__kweo__browser_select_tab`, `mcp__kweo__browser_run_task`. If they only
   appear as deferred tool names, load them with ToolSearch first
   (`select:mcp__kweo__browser_navigate,mcp__kweo__browser_read,...`).
2. **Claude in Chrome** (`mcp__claude-in-chrome__*`) or the **built-in
   browser** (`mcp__Claude_Browser__*`), if present. Load their own skills
   first. Same rules.
3. **WebSearch / WebFetch**, for public pages that need no login. Good for
   Google Trends RSS, news, YouTube Charts. Useless for Instagram, which needs
   a login for almost everything.
4. **Ask the user to paste.** Screenshots, view counts, the first line of a
   reel. Always works. Never pretend it is worse than browsing.

If kweo is installed but not connected, offer the setup below once, then fall
through to the next option. Do not block the task on it.

## How to browse with kweo

Prefer the small tools over `browser_run_task`. They do exactly one thing and
nothing else.

```
browser_new_tab        open a fresh tab, so the user's own tabs are left alone
browser_navigate       go to one URL
browser_read           read the page as indexed handles and text, not pixels
browser_tabs           list tabs
browser_select_tab     switch tab
```

The normal loop for one page: `browser_new_tab`, `browser_navigate`,
`browser_read`, take notes, move on. `browser_read` returns structure, so
pull view counts, captions and handles straight out of it. No screenshots.

Use `browser_run_task` only when a page needs scrolling or a filter set, and
phrase the goal as reading:

```
Goal: On this TikTok Creative Center page, set country to India and period
to 7 days, then read the top 20 hashtags with their rank and post count.
Report them as a list. Read and report only. Do not click like, follow,
comment, save, share or send. Do not type into any box except the
country/period filters.
```

On Instagram, keep `browser_run_task` goals tiny and specific: "scroll this
profile's reels grid once and report the view count under each of the first
12 reels". Never "go through my feed".

## Setup, when the kweo tools are missing

Run the checker. It reads nothing secret and prints the exact next step.

```bash
python3 kweo_check.py          # human-readable
python3 kweo_check.py --json   # for other skills
```

It checks four things: the app is installed, it is running, its MCP server on
`http://127.0.0.1:7333/mcp` answers, and Claude Code has a server named
`kweo`. A **401** from the server is the healthy answer. It means the server
is on and wants its token. "Connection refused" means the toggle is off.

What to tell the user, by result:

| result | say |
| --- | --- |
| not installed | Install kweo from https://kweo.ai, open it, then say "connect kweo" again. |
| not running | Open kweo. |
| server off | In kweo press Cmd+J, open the model picker, choose **Connect a model…**, turn on **Let Claude control kweo**. |
| server on, not registered | The same panel shows a command. Copy it. |
| registered | Restart Claude Code so the tools load. |

The command kweo shows looks like this, with the user's real token:

```bash
claude mcp add kweo --transport http http://127.0.0.1:7333/mcp --header "Authorization: Bearer <token>"
```

The user can run it themselves by typing `! ` and pasting it into Claude
Code. Or they paste it into the chat and Claude runs it with Bash. Either way:

- Do not go looking for the token. Not in kweo's files, not in its settings,
  not in the keychain. The user copies it from the panel.
- Do not echo the token back, write it into any file, or put it in a report.
- After it is added, Claude Code needs a restart before `mcp__kweo__*` tools
  appear. Say so.

Then run `kweo_check.py` again. It should say READY.

## What other skills should do

At the point where a skill needs a page:

1. If `mcp__kweo__*` tools exist, use them, under the rules above.
2. If not, run `python3 ~/.claude/skills/ig-kweo/kweo_check.py --json`. If
   `ready` is false and `app` is true, offer setup in one line. If the user
   says not now, carry on with the next browser in the list.
3. Never tell the user a page was read when it was not. If a source could not
   be reached, name it and say what is missing from the result because of it.

Nothing is posted, liked, followed, saved or messaged by this skill. It reads.
