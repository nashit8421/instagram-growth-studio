---
name: ig-account
description: >-
  Run more than one Instagram account from the same pack - your own plus
  clients - with each account's voice, brand, ledger, swipe file and plan kept
  in its own folder. Use when the user says "switch account", "add another
  account", "manage clients", "which account", "new client", "use @handle",
  names a different handle than the one active, or starts work for a client.
---

# ig-account

Every ig-* skill reads and writes files: `voice.md`, `brand.json`,
`posts.csv`, `swipe.md`, `plan.md`, `log.md`, `engaged.md`, `trends.csv`,
`sounds.csv`, `snapshots.csv`, `followers.csv` and the rest. They all live in
one data folder. With one account that folder is `~/.claude/instagram`. With
several, each account gets its own folder and one of them is active. Every
skill works on the active account and nothing else.

One script, stdlib Python, run from this skill's folder:

```bash
python3 account.py list                      # * marks the active account
python3 account.py new HANDLE                # new empty account (voice.md template copied in)
python3 account.py new HANDLE --from-current --yes   # move the existing files into it
python3 account.py use HANDLE                # switch
python3 account.py use --none                # back to the single-account folder
python3 account.py current                   # active handle + its folder
python3 account.py path                      # the folder only
python3 account.py remove HANDLE --yes       # moved to a backup, never deleted
```

`--json` works on `list`, `new` and `current`. Handles follow Instagram's
rules (letters, digits, `.` and `_`, 30 max); a leading `@` and capitals are
fine and get normalised.

Any skill that needs the data folder in a shell:

```bash
DATA=$(python3 ~/.claude/skills/ig-account/account.py path)
```

## Which folder wins

1. `$IG_DATA_DIR`, if set. It overrides everything, accounts included.
2. `$IG_HOME/active-account` names a handle and `$IG_HOME/accounts/<handle>/`
   exists: that folder.
3. Otherwise `$IG_HOME` itself, the original single-account layout.

`$IG_HOME` defaults to `~/.claude/instagram`. Someone with one account never
has to know this skill exists.

## How to run a multi-account session

**Say the account first.** At the start of any session where more than one
account exists, run `account.py current` and say it in the first line: "Working
on @acme.co." If the user then asks for something that is clearly for another
account ("write a reel for my own page"), stop and switch before drafting, then
say the new handle.

**Never mix data across accounts.** One account's voice, swipe file, ledger
numbers, brand colours or engagement list never go into another's work. Do not
read another account's folder to "borrow" a hook or a benchmark unless the user
asks for that comparison by name, and then say which account each number is
from.

**Moving to multiple accounts.** If `~/.claude/instagram` already has files and
the user adds a second account, ask whether the existing files belong to them
(usually yes). Then:

```bash
python3 account.py new theirhandle --from-current        # shows what will move
python3 account.py new theirhandle --from-current --yes  # moves it, backup first
python3 account.py new clienthandle
python3 account.py use clienthandle
```

`--from-current` copies everything to `~/.claude/instagram/backup-<time>/`
before moving, so nothing can be lost.

**A new account needs its own voice.** `new` copies the `voice.md` template in
when it can find it (`--template path/to/voice.md` to point at it). If not,
copy `templates/voice.md` from the pack into the folder from `account.py path`.
Then fill it in for that account, or ask for three of its reels and write it
from those. Do not start a client off on the user's own voice. A client's
`brand.json` goes in the same folder for /ig-render.

**Removing.** `remove --yes` moves the folder to a backup and, if it was
active, drops back to single-account mode. Tell the user where the backup is.
To really delete it, they do that themselves.
