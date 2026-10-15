---
name: ig-test
description: >-
  A/B test two hooks for the same reel using Instagram Trial Reels, then say
  honestly whether one of them actually won. Use when the user wants to "test
  two hooks", run an "A/B test" or a "split test", asks "which hook is better"
  and has two decent options, mentions a "trial reel", or comes back with the
  numbers from two trials.
---

# ig-test

The hook scorer in /ig-reel catches bad hooks. It cannot pick between two good
ones. Tested on real creators, it called hits from misses at AUC 0.56, and a
coin flip is 0.50. Nothing that reads text can make that call. The audience
can.

**Trial Reels** show a reel only to people who do not follow you. After 24
hours you see how strangers reacted, and you choose whether to share it to
your followers. They need a professional account (creator or business). You
turn it on with the "Trial" toggle on the share screen.

Two trials of the same video, with only the first line changed, is a split
test with strangers as the panel. This skill sets it up, keeps the books and
does the arithmetic.

**Nothing is posted by this skill.** The user posts both trials by hand.

One tool lives in this folder and it runs:

```bash
python3 abtest.py new --a "hook A" --b "hook B" --formula-a ID --formula-b ID --theme T --length 28
python3 abtest.py record T001 A --views 2140 --shares 31 --skip-rate 34.2 --avg-watch 11.4
python3 abtest.py record T001 B --views 1900 --shares 18 --skip-rate 41.8
python3 abtest.py report T001          # add --json for the raw numbers
python3 abtest.py list                 # every test and where it stands
```

Records go in the shared ledger, `posts.csv` in the active account's data
folder (`python3 ~/.claude/skills/ig-account/account.py path`, see
/ig-account; defaults to `~/IGStudio`), through
`../ig-ledger/ledger.py`. Each variant is one row,
marked `trial=yes`, with a `test_id` and a `variant`.

## The steps

**1. Write two hooks with /ig-reel.** Two different formulas from
`hooks.json`, not two rewrites of one line. Same script after the hook, word
for word. If both hooks share a formula, the test can only tell you about
wording, which is worth less.

**2. Start the test.**

```bash
python3 abtest.py new --a "..." --b "..." --formula-a <id> --formula-b <id>
```

It scores both with hookscore.py if ig-reel is installed. If either scores
WEAK, fix it first. A trial is a real post to real strangers, so do not spend
one on a hook that fails the basics. If both are OK or STRONG, ignore the gap
between the scores. That gap is exactly what the scorer cannot read.

It prints a checklist. Show it to the user as is:

- Same video after the hook. Only the first line changes.
- Post both as Trial Reels within the same hour, at their normal time of day.
- Same caption, same audio, same cover.
- Do not share either to followers yet. Turn off auto-share if offered.
- Come back after 24 hours.

**3. The user posts both.** By hand, in the app. You do not post anything.

**4. After 24 hours, record the numbers.** Ask the user to open each trial's
insights and paste views, shares, likes, comments, saves, follows, skip rate
and average watch time. Skip rate is the percent who swiped away in the first
3 seconds. Then:

```bash
python3 abtest.py record T001 A --views N --shares N --skip-rate F ...
python3 abtest.py record T001 B --views N --shares N --skip-rate F ...
```

`12,400`, `1.2k` and `38.5%` all work.

**5. Read the report.**

```bash
python3 abtest.py report T001
```

How it decides:

- **Primary: skip rate**, when both trials have it. Lower wins. It is tested
  as "held past 3s", views times (1 minus skip rate).
- **Secondary: shares per view.** Only decides if skip rate was too close.
- **Last: views.** A rough count test. Instagram sizes the trial audience, so
  a views-only win is weak evidence.

Every metric gets a two-proportion z-test. Under |z| 1.96, or under 300 views
on either trial, the verdict is **TOO CLOSE**. On a few hundred views a 3
point skip-rate gap is usually noise, and the report says so.

The verdict is one of `WINNER A`, `WINNER B`, `TOO CLOSE`.

- **Winner:** tell the user to share the winner to followers from the trial
  reel's menu. The loser stays as a trial. The ledger rows get `won T001` and
  `lost T001` in `notes`, so the losing hook is logged as a learning.
- **Too close:** say so plainly. Do not pick one and dress it up. If both are
  still climbing, wait another day and record again. Otherwise the user
  shares the one they like better, and nothing is learned about the hooks.

The final call is the user's. The report is evidence, not an instruction.

## Be honest about what one test is

One test is one data point. A win on skip rate says this hook held strangers
better on this video, this week. It does not say the formula always wins.

After several tests, run /ig-audit (`../ig-ledger/audit.py`). It reads the
same ledger and shows which formulas win for this account. That is where a
pattern shows up, if there is one.

## Things that ruin the test

- Different videos after the hook. Then you tested the video.
- Posting hours apart, or one on a weekday and one on a weekend.
- Sharing one to followers early. Followers are not strangers.
- Calling it at 6 hours because one is ahead. Wait the full 24.
- Running five variants at once on a small account. Two is enough.

## Files

- `abtest.py`: the tool. Stdlib only, no network.
- `tests/test_abtest.py`: run `python3 -m unittest discover -s tests` from
  this folder. Uses the real ig-ledger if present, else the stand-in in
  `tests/_fake_ledger/`.
