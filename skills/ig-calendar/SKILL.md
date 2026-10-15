---
name: ig-calendar
description: >-
  Turn the weekly Instagram plan into calendar reminders - a slot for each
  post, a filming block the day before each reel, the daily 20-minute
  engagement round and the story nudge. Use when the user says "put my plan
  in my calendar", "remind me to post", "schedule reminders", "add to Google
  Calendar", "calendar for my posts", or right after /ig-plan has written
  plan.md. Reminders only. Nothing is ever posted.
---

# ig-calendar

/ig-plan decides the week. This puts it where the user will see it: their
calendar. Every event is a reminder. **Nothing posts to Instagram, ever.** The
user posts by hand when the reminder goes off.

One script lives in this folder and it runs. Run it from this skill's own
folder (Claude Code gives you the base directory when the skill loads).
Stdlib Python, no installs, no network. It never touches a calendar itself.
It reads the plan and prints events. You create them, with the user's say-so.

```bash
python3 schedule.py parse                     # read plan.md, show the events
python3 schedule.py parse --json              # the same, for you to read
python3 schedule.py events --json             # the list for the Calendar connector
python3 schedule.py checklist                 # the week as a plain checklist
python3 schedule.py ics --out ~/Desktop/ig-week.ics   # fallback file
```

Options on every command:

- `PLAN.md` path. Default is `plan.md` in the data dir: `$IG_DATA_DIR`, else
  the active account under `~/.claude/instagram/accounts/`, else
  `~/.claude/instagram`.
- `--week-of YYYY-MM-DD` the Monday. Without it, the week comes from the
  plan's `WEEK OF SEP 15` line (the year nearest today), else next Monday.
- `--tz Europe/London` the time zone the times are in. Default is the
  system zone. If the audience lives somewhere else, /ig-plan anchored the
  times to them, so pass their zone.
- `--skip stories` (or `prep`, `engage`, `post`) to leave a kind out.
- `--prep-at 5pm`, `--engage-at 8am`, `--stories-at 9am`, `--remind 15`.

## What it makes

From a plan like this:

```
WEEK OF SEP 15
MON  engage only  (20 min, list below)
TUE  7:30pm  REEL      PROOF    #5  Time Collapse   - 5hr proposal to 20 min
WED  stories only + engage
THU  7:00pm  CAROUSEL  TEACH    Job B caption       - the 4-slide clause breakdown
SAT  -
STORIES  every day, 3 to 5 frames, question box on Thursday.
```

| kind | when | how long | says |
| --- | --- | --- | --- |
| post | the slot time | 30 min | `IG: REEL · PROOF · Time Collapse`, the angle, the hook formula, which skills to run |
| prep | day before a reel, 6pm | 60 min | `IG prep: Film Tuesday's reel`, run /ig-reel then /ig-edit |
| engage | 30 min before the post, or 7pm | 20 min | the ENGAGE list, run /ig-comment |
| stories | every story day, 12:30pm | 15 min | frames, and the day's note ("question box") |

A `-` day is a rest day. No engagement block on it. Every event has a 30
minute popup and ends its description with "Nothing posts automatically" and
a tag like `[ig:ig-2026-W43-tue-reel]`.

**The key is stable.** It is the ISO week, the day and the format. It does
not change when the time or the angle changes. That is how a second run
finds the first run's events and updates them instead of doubling them.

## The flow

1. **Find the plan.** Run `python3 schedule.py parse`. If it says "No plan
   found", tell the user and offer /ig-plan. Do not invent a week.
2. **Read the warnings.** If it says the week is already over, ask which
   week they mean and rerun with `--week-of`. If it fell back to UTC, ask for
   their time zone.
3. **Show the week.** Run `python3 schedule.py checklist` and paste it. Say
   how many events of each kind, the time zone, and the dates.
4. **Ask before anything goes in a calendar.** Something like: "That is 20
   reminders in your Google Calendar, Mon 19 to Sun 25 Oct, Europe/London.
   Add them? I can drop stories or prep if that is too many." Wait for a
   yes. A calendar is the user's space and other people may see it. **Never
   create, update or delete an event without that yes.** A yes to last
   week's plan is not a yes to this week's.
5. **Create them** (below). Then report what was created, updated and
   skipped, one line each.

If the user says "too many", rerun with `--skip stories` or `--skip prep` and
ask again.

## Creating events with the Google Calendar connector

Run `python3 schedule.py events --json` (same options as before). Each item
has `summary`, `description`, `start` and `end` (RFC 3339 with offset),
`time_zone`, `reminders_minutes`, `key`, and `connector`: the arguments for
`create_event`, already shaped.

1. **Look first.** Call `list_events` for the week (`startTime` the Monday
   00:00, `endTime` the next Monday 00:00, local times, `timeZone` from the
   output; start a day early if there is a prep event on the Sunday before).
   Use `fullText: "ig:"` if it helps narrow it. For each event that comes
   back, look for `[ig:KEY]` in its description.
2. **Key found:** call `update_event` with that `eventId` and the new
   `summary`, `description`, `startTime`, `endTime`, `timeZone` and
   `overrideReminders`. Do not create a second one.
3. **Key not found:** call `create_event` with the `connector` object as
   is: `summary`, `description`, `startTime` and `endTime` as local times,
   `timeZone`, and `overrideReminders` (popup, 30 minutes). Primary calendar
   unless the user named another; `list_calendars` finds its id.
4. **Old keys from the same week that are no longer in the plan** (a slot
   was dropped): list them and ask before you `delete_event` anything.

Never add attendees. Never make an event public. These are the user's own
reminders.

## When the connector is missing or fails

If there are no Google Calendar tools, or a call fails and a retry does not
fix it, use the file:

```bash
python3 schedule.py ics --out ~/Desktop/ig-week.ics
```

Tell the user: "I could not reach your calendar, so I wrote
~/Desktop/ig-week.ics. Double-click it to add the reminders to Apple
Calendar. For Google Calendar, open Settings, then Import and export, and
import that file." The file still needs their yes first; the double-click
is theirs.

The file uses UTC times, a 30 minute alarm on each event, and the same keys
as UIDs. Importing a newer file for the same week replaces the old events in
Apple Calendar instead of adding copies. Google import may skip events it
has already seen, so for changes the connector is the better route.

## What this skill does not do

- It does not post, schedule or draft anything on Instagram.
- It does not write the posts. The reminders point at /ig-reel,
  /ig-carousel, /ig-caption, /ig-render, /ig-edit, /ig-story and
  /ig-comment.
- It does not change `plan.md`. If the plan is wrong, fix it with /ig-plan
  and run this again. The keys will match and the events update.

## Tests

```bash
python3 -m unittest discover -s tests
```

They cover the /ig-plan example line by line, time zones and the October
clock change, the .ics format (CRLF, folding at 75 octets, escaping, stable
UIDs), stable keys, and a missing plan. They use temp dirs only.
