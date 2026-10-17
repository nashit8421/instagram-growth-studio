/* Week: the home screen. Claude prepares the week on its own (autopilot); this shows it.
   First visit: type a handle, press Start. Every visit after: the week, today's to-dos,
   and each post as a kit you open. */
(function () {
  "use strict";
  var h = IG.h;
  var DAYS = ["MON", "TUE", "WED", "THU", "FRI", "SAT", "SUN"];
  var DAY_NAME = { MON: "Monday", TUE: "Tuesday", WED: "Wednesday", THU: "Thursday", FRI: "Friday", SAT: "Saturday", SUN: "Sunday" };
  IG.STAGES = [["script", "Script"], ["filmed", "Filmed"], ["edited", "Edited"], ["posted", "Posted"]];

  /* ---------- small helpers shared with the post page */
  IG.day = function (iso) { return new Date(iso + "T12:00:00"); };
  IG.longDate = function (iso) {
    return IG.day(iso).toLocaleDateString(undefined, { weekday: "short", day: "numeric", month: "short" });
  };
  IG.ampm = function (hhmm) {
    var m = String(hhmm || "").match(/^(\d{1,2}):(\d{2})$/);
    if (!m) return "";
    var hr = +m[1], ap = hr >= 12 ? "pm" : "am";
    hr = hr % 12 || 12;
    return hr + (m[2] === "00" ? "" : ":" + m[2]) + ap;
  };
  IG.stageIndex = function (stage) {
    for (var i = 0; i < IG.STAGES.length; i++) if (IG.STAGES[i][0] === stage) return i;
    return 0;
  };
  IG.fmtLabel = function (p) { return { reel: "Reel", carousel: "Carousel", story: "Story", photo: "Photo" }[p.format] || p.format; };
  IG.postLink = function (weekOf, id) { return IG.hashFor("post", { w: weekOf, id: id }); };

  /* Follow a Claude run: phases light up as the tools they use start. */
  IG.followRun = function (job, phases, onUpdate, onEnd) {
    var st = { steps: [], phase: -1, now: "", ended: null };
    var s = IG.stream(job, function (ev) {
      if (ev.type === "tool" && ev.summary && !/^(Loading tools|Searching files)$/.test(ev.summary)) {
        st.now = ev.summary;
        st.steps.push(ev.summary);
        (phases || []).forEach(function (ph, i) { if (i > st.phase && ph.match.test(ev.summary)) st.phase = i; });
      }
      if (ev.type === "end") { st.ended = ev; if (onEnd) onEnd(ev, st); }
      else if (onUpdate) onUpdate(st);
    });
    return s;
  };

  var PREP_PHASES = [
    { label: "Reading the account", match: /scan\.py|kweo|account\.md|state\.py/i },
    { label: "Finding the one thing holding growth back", match: /grow\.py/i },
    { label: "Finding reels going viral in your niche", match: /swipe\.py|\/ig-viral|captured\.tsv/i },
    { label: "Checking what everyone's talking about this week", match: /moments\.py|trends\.py|Searching the web|ig-trends|Reading .*\.(com|in|org)/i },
    { label: "Picking the posts and the days", match: /ig-plan|plan\.md|hooks\.json/i },
    { label: "Writing hooks and scripts in their shape", match: /hookscore\.py|beats\.py|ig-reel/i },
    { label: "Captions, sounds, and the director's notes", match: /caption\.py|humanize\.py|audio\.py|ig-caption|ig-audio|week\.json/i },
    { label: "Final check", match: /week\.py/i }
  ];

  var DAILY_PHASES = [
    { label: "Reading what everyone's talking about", match: /moments\.py/i },
    { label: "Checking reels about it", match: /kweo|Searching the web|ig-kweo-reader/i },
    { label: "Writing the reel", match: /hookscore\.py|beats\.py|caption\.py|humanize\.py|week\.json/i },
    { label: "Final check", match: /week\.py/i }
  ];

  function prepCard(job, title, sub, phases, doneMsg) {
    phases = phases || PREP_PHASES;
    var list = h("ol", { class: "phases" }, phases.map(function (p) { return h("li", null, h("span", { class: "b" }), h("span", { text: p.label })); }));
    var now = h("div", { class: "now small muted", text: "Starting…" });
    var t0 = Date.now();
    var timer = h("span", { class: "num" });
    var tick = setInterval(function () {
      var s = Math.round((Date.now() - t0) / 1000);
      timer.textContent = Math.floor(s / 60) + ":" + ("0" + (s % 60)).slice(-2);
      if (!document.body.contains(timer)) clearInterval(tick);
    }, 1000);
    var stop = IG.btn("Stop", { cls: "ghost sm", onClick: function () { return IG.post("/api/jobs/" + job + "/cancel"); } });
    var card = h("section", { class: "prep" },
      h("div", { class: "prep-h" }, h("span", { class: "spin" }), h("div", { class: "grow" }, h("h2", { text: title }), h("p", { class: "muted", text: sub })),
        h("div", { class: "row" }, h("span", { class: "small faint" }, timer), stop)),
      list, now,
      h("p", { class: "small faint", text: "You can close this tab. It keeps going, and the week is here when you come back. Nothing is posted." }));
    var run = IG.followRun(job, phases, function (st) {
      list.querySelectorAll("li").forEach(function (li, i) { li.className = i < st.phase ? "done" : i === st.phase ? "cur" : ""; });
      now.textContent = st.now ? "Now: " + st.now : "";
    }, function (ev) {
      clearInterval(tick);
      if (ev.status === "done") IG.toast(doneMsg || "Your week is ready", "ok");
      if (IG.current === "week") IG.render("week");
    });
    card._run = run;
    return card;
  }

  /* ---------- first visit */
  function onboarding(view, data) {
    var known = (IG.accounts && IG.accounts.accounts) || [];
    var handle = IG.input("handle", { placeholder: "yourhandle", autocomplete: "off", spellcheck: "false", autocapitalize: "off",
      value: IG.params && IG.params.new ? "" : (data.handle || "") });
    var kweoBox = h("div", { class: "kweo-line" }, h("span", { class: "spin" }), h("span", { class: "small muted", text: "Checking kweo…" }));
    var form = h("form", { class: "onboard stack" },
      h("div", null, h("p", { class: "eyebrow", text: "IG Studio" }),
        h("h1", { text: "Whose Instagram are we growing?" }),
        h("p", { class: "lede", text: "Type the handle. Claude reads the account, works out what's working, and comes back with this week's posts, each one scripted, with how to film it and the caption to paste. You film and post. Nothing else." })),
      h("div", { class: "handle-in" }, h("span", { class: "at", text: "@" }), handle, IG.btn("Start", { cls: "primary", type: "submit", icon: "arrow" })),
      kweoBox,
      h("ul", { class: "promise small muted" },
        h("li", { text: "Your own account or a client's. Each gets its own folder." }),
        h("li", { text: "Reads only. Never posts, likes, follows or messages." }),
        h("li", { text: "About 10 minutes the first time. You can close the tab." })));
    form.addEventListener("submit", function (e) {
      e.preventDefault();
      var v = handle.value.trim().replace(/^@/, "").toLowerCase();
      if (!/^[a-z0-9._]{1,30}$/.test(v)) { handle.focus(); IG.toast("Type an Instagram handle: letters, digits, . and _", "bad"); return; }
      var btn = form.querySelector("button[type=submit]");
      IG.busy(btn, function () {
        var exists = known.some(function (a) { return a.handle === v; });
        var p = (IG.accounts && IG.accounts.active === v) ? Promise.resolve()
          : exists ? IG.post("/api/accounts/use", { handle: v }) : IG.post("/api/accounts/new", { handle: v });
        return p.then(function () { return IG.loadAccounts(); }).then(function () {
          if (IG.onAccountChange) IG.onAccountChange();
          return IG.post("/api/week/prepare", { handle: v });
        }).then(function () { IG.params = {}; IG.go("week"); });
      });
    });
    view.appendChild(form);
    IG.get("/api/kweo").then(function (k) {
      IG.clear(kweoBox);
      if (k.ready) {
        kweoBox.appendChild(h("span", { class: "ok-dot" }));
        kweoBox.appendChild(h("span", { class: "small", text: "kweo is connected. Claude reads the account in your own browser." }));
        return;
      }
      kweoBox.classList.add("warn");
      kweoBox.appendChild(h("div", { class: "stack-sm grow" },
        h("b", { class: "small", text: "Connect kweo first so Claude can read the account" }),
        h("span", { class: "small muted", text: IG.kweoText(k) }),
        k.app && IG.kweoConnectBox ? IG.kweoConnectBox(function () { IG.render("week"); })
          : h("div", null, h("a", { class: "btn sm", href: "https://kweo.ai", target: "_blank", rel: "noopener noreferrer", text: "Get kweo (free)" }))));
    }).catch(function () { kweoBox.remove(); });
  }

  /* ---------- the week */
  function todoDone(week, t, i) {
    if (t.post) {
      var p = (week.posts || []).filter(function (x) { return x.id === t.post; })[0];
      var stage = p && p.progress ? p.progress.stage : "script";
      if (t.kind === "film") return IG.stageIndex(stage) >= 1;
      if (t.kind === "post") return stage === "posted";
    }
    try { return !!JSON.parse(localStorage.getItem(todoKey(week)) || "{}")[i]; } catch (e) { return false; }
  }
  function todoKey(week) { return "igtodo:" + IG.accountKey() + ":" + week.week_of; }
  function setTodo(week, i, v) {
    try { var d = JSON.parse(localStorage.getItem(todoKey(week)) || "{}"); d[i] = v; localStorage.setItem(todoKey(week), JSON.stringify(d)); } catch (e) { /* ignore */ }
  }

  function todayCard(week, today) {
    var items = [];
    (week.todo || []).forEach(function (t, i) {
      if (!t.date || t.date > today) return;
      var done = todoDone(week, t, i);
      if (t.date < today && done) return;
      items.push({ t: t, i: i, done: done, late: t.date < today });
    });
    (week.posts || []).forEach(function (p) {
      if (p.date === today && (!p.progress || p.progress.stage !== "posted")) {
        items.push({ post: p });
      }
    });
    var upcoming = (week.todo || []).map(function (t, i) { return { t: t, i: i }; })
      .filter(function (x) { return x.t.date > today; }).sort(function (a, b) { return a.t.date < b.t.date ? -1 : 1; })[0];
    var list = h("ul", { class: "todo" }, items.map(function (it) {
      if (it.post) {
        return h("li", { class: "todo-post" }, h("span", { class: "tick live" }),
          h("a", { href: IG.postLink(week.week_of, it.post.id) }, h("b", { text: "Post " + it.post.title }), h("span", { class: "muted", text: " at " + IG.ampm(it.post.time) })),
          h("span", { class: "badge accent", text: "today" }));
      }
      var box = h("input", { type: "checkbox", checked: it.done, "aria-label": it.t.task });
      var auto = !!(it.t.post && (it.t.kind === "film" || it.t.kind === "post"));
      if (auto) box.disabled = true;
      box.addEventListener("change", function () { setTodo(week, it.i, box.checked); li.classList.toggle("done", box.checked); });
      var label = it.t.post ? h("a", { href: IG.postLink(week.week_of, it.t.post), text: it.t.task }) : h("span", { text: it.t.task });
      var li = h("li", { class: it.done ? "done" : "" }, box, h("span", { class: "grow" }, label), it.late ? h("span", { class: "badge warn", text: "from " + IG.longDate(it.t.date) }) : null);
      return li;
    }));
    return h("section", { class: "card today" },
      h("div", { class: "card-h" }, h("div", null, h("p", { class: "eyebrow", text: "Today · " + IG.longDate(today) }),
        h("h2", { text: items.length ? "What to do now" : "Nothing due today" }))),
      items.length ? list : h("p", { class: "muted", text: upcoming ? "Next: " + upcoming.t.task + " on " + IG.longDate(upcoming.t.date) + "." : "The week is done. Claude prepares the next one on its own." }),
      h("p", { class: "small faint", text: "Every day: 3 to 5 story frames, and 20 minutes of comments on others' posts before you post." }));
  }

  function stageDots(p) {
    var idx = IG.stageIndex(p.progress ? p.progress.stage : "script");
    var running = p.progress && p.progress.edit && p.progress.edit.running;
    return h("div", { class: "dots", "aria-label": "Progress: " + IG.STAGES[idx][1] }, IG.STAGES.map(function (s, i) {
      return h("span", { class: "d" + (i <= idx ? " on" : "") + (running && i === 2 ? " busy" : ""), title: s[1] });
    }));
  }

  function postCard(week, p, today) {
    var hook = p.hook || {};
    var stage = p.progress ? p.progress.stage : "script";
    var next = { script: p.format === "reel" ? "Film it" : "Make it", filmed: "Edit it", edited: "Post it", posted: "Posted" }[stage];
    var running = p.progress && p.progress.edit && p.progress.edit.running;
    return h("a", { class: "pcard" + (p.date === today ? " is-today" : "") + (stage === "posted" ? " is-done" : ""), href: IG.postLink(week.week_of, p.id) },
      h("div", { class: "pc-meta" },
        h("span", { class: "fmt " + p.format, text: IG.fmtLabel(p) }),
        h("span", { text: IG.ampm(p.time) }),
        h("span", { class: "type", text: p.type }),
        p.trial ? h("span", { class: "badge info", text: "trial" }) : null),
      h("div", { class: "pc-title", text: p.title }),
      p.moment && p.moment.name ? h("div", { class: "pc-model pc-moment" }, IG.icon("trends"),
        h("span", { text: "Rides: " + p.moment.name + (p.moment.hours_on_x ? " · " + p.moment.hours_on_x + "h trending on X" : "") })) : null,
      p.model && p.model.ref ? h("div", { class: "pc-model" }, IG.icon("trends"),
        h("span", { text: "Copies " + (p.model.account || p.model.ref) + (p.model.multiple ? " · " + IG.n(p.model.multiple, 1) + "× their usual " + (p.model.metric || "views") : "") })) : null,
      hook.spoken || hook.on_screen ? h("div", { class: "pc-hook", text: IG.quote(hook.spoken || hook.on_screen) }) : null,
      h("div", { class: "pc-foot" }, stageDots(p),
        h("span", { class: "pc-next" + (stage === "posted" ? " ok" : ""), text: running ? "Director at work…" : next }, stage === "posted" ? null : IG.icon("arrow"))));
  }

  /* Today's trend reel: Claude reads the day's moments and adds one reel when one fits. */
  function dailyCard(data, m) {
    var d = data.daily || {};
    if (!d.available) return null;
    var when = d.date === data.today ? "today" : IG.day(d.date).toLocaleDateString(undefined, { weekday: "long" });
    var head = h("p", { class: "eyebrow", text: "Trend reel for " + when });
    if (d.running) return prepCard(d.job, "Today's trend reel", "Claude is reading what everyone's talking about and writing one reel that rides it.",
      DAILY_PHASES, "Today's trend reel is ready");
    if (d.status === "done" && d.post_id) {
      var p = data.week && data.week.week_of === d.week_of ? (data.week.posts || []).filter(function (x) { return x.id === d.post_id; })[0] : null;
      return h("a", { class: "card daily", href: IG.postLink(d.week_of, d.post_id) }, head,
        h("h3", { text: d.moment ? "Riding: " + d.moment : "Today's trend reel" }),
        p ? h("p", { class: "muted", text: p.title + " · " + IG.ampm(p.time) }) : null,
        h("span", { class: "pc-next" }, "Open the kit", IG.icon("arrow")));
    }
    function again(label, cls) {
      return IG.btn(label, { cls: cls || "sm", icon: "refresh", onClick: function () {
        var note = IG.textarea("note", { rows: 2, placeholder: "Optional. e.g. the Tesla flying car" });
        IG.dialog("Make a trend reel for " + when + "?", h("div", { class: "stack-sm" },
          h("p", { class: "small", text: "Claude reads what everyone's talking about and writes one reel that rides it." }),
          IG.field("A moment you have in mind", note)), [
          { label: "Cancel" },
          { label: "Make it", primary: true, onClick: function (close) {
            return IG.post("/api/daily", { note: note.value }).then(function () { close(); IG.render("week"); });
          } }]);
      } });
    }
    if (d.status === "skipped") return h("div", { class: "card flat daily" }, head,
      h("p", { class: "small muted", text: "Nothing worth riding: " + (d.reason || "no moment fits the niche.") }), again("Make one anyway", "ghost sm"));
    if (d.status === "error" || d.status === "cancelled") return h("div", { class: "card flat daily" }, head,
      h("p", { class: "small", text: d.status === "cancelled" ? "Stopped." : (d.error || "Claude stopped.") }), again("Try again"));
    if (d.needs && !d.auto_blocked && data.claude && !data.autopilot.running) {
      IG.post("/api/daily", { auto: true }).then(function () { if (IG.alive(m)) IG.render("week"); }).catch(function () { /* shown next visit */ });
      return h("div", { class: "card flat daily" }, head, h("p", { class: "small muted", text: "Checking what everyone's talking about…" }));
    }
    return null;
  }

  function weekList(week, today) {
    var monday = IG.day(week.week_of);
    var byDay = {};
    var now = [];
    (week.posts || []).forEach(function (p) {
      if (/^now/.test(p.id)) now.push(p);
      else (byDay[p.day] = byDay[p.day] || []).push(p);
    });
    // A moment that can't wait for Monday: it goes up before the week starts.
    var nowRow = now.length ? h("div", { class: "dayrow is-now" },
      h("div", { class: "dlabel" }, h("span", { class: "dn", text: "NOW" }), h("span", { class: "dd", text: String(IG.day(now[0].date).getDate()) })),
      h("div", { class: "dbody" },
        h("p", { class: "small muted", text: "A moment everyone's talking about right now. Post it before the week starts: it's worth most in its first three days." }),
        now.sort(function (a, b) { return (a.date + a.time) < (b.date + b.time) ? -1 : 1; }).map(function (p) { return postCard(week, p, today); }))) : null;
    return h("section", { class: "days" }, nowRow, DAYS.map(function (d, i) {
      var date = new Date(monday.getTime() + i * 864e5);
      var iso = date.getFullYear() + "-" + ("0" + (date.getMonth() + 1)).slice(-2) + "-" + ("0" + date.getDate()).slice(-2);
      var posts = (byDay[d] || []).sort(function (a, b) { return a.time < b.time ? -1 : 1; });
      var stories = (week.stories || []).filter(function (s) { return String(s.day).toUpperCase() === d; })[0];
      return h("div", { class: "dayrow" + (iso === today ? " is-today" : "") + (iso < today ? " past" : "") },
        h("div", { class: "dlabel" }, h("span", { class: "dn", text: d }), h("span", { class: "dd", text: String(date.getDate()) })),
        h("div", { class: "dbody" },
          posts.length ? posts.map(function (p) { return postCard(week, p, today); })
            : h("div", { class: "rest" }, h("span", { text: "No post. Stories and the 20-minute comment round." })),
          stories && (stories.frames || []).length ? h("div", { class: "story-line small muted" }, h("b", { text: "Stories: " }), stories.frames.join(" · "), stories.sticker ? " · " + stories.sticker : "") : null));
    }));
  }

  function engageCard(week) {
    var e = week.engage;
    if (!e) return null;
    var when = String(e.when || "before each post");
    var lead = /\bmin/i.test(when) ? IG.cap(when) : (e.minutes || 20) + " minutes " + when;
    return IG.card("The comment round", lead + ", by hand. Real comments, not emoji.",
      h("div", { class: "stack-sm" },
        h("ul", { class: "plain" }, (e.kinds || []).map(function (k) {
          return h("li", null, h("b", { text: (k.count || "") + " " + k.kind }), " · " + (k.who || ""));
        })),
        (e.accounts || []).length ? h("div", { class: "chips" }, e.accounts.map(function (a) { return h("span", { class: "chip static", text: a }); })) : null,
        h("div", null, IG.btn("Write today's comments with Claude", { cls: "sm", icon: "chat", onClick: function () {
          IG.ask("/ig-comment Build today's engagement list from my plan and write the comments for me to post by hand.");
        } }))));
  }

  function remindersBtn() {
    return IG.btn("Add reminders", { icon: "calendar", onClick: function () {
      IG.dialog("Reminders for this week", h("div", { class: "stack-sm" },
        h("p", { text: "A reminder to film the day before each post, one to post on time, and the daily comment round." }),
        h("p", { class: "small muted", text: "Reminders only. Nothing is posted." })), [
        { label: "Download .ics", onClick: function (close) {
          return IG.post("/api/calendar/ics", {}).then(function (r) {
            var a = h("a", { href: r.url, download: "" }); document.body.appendChild(a); a.click(); a.remove();
            IG.toast(r.events + " reminders saved. Open the file to add them."); close();
          });
        } },
        { label: "Add to Google Calendar", primary: true, onClick: function (close) {
          close();
          IG.ask("/ig-calendar Add this week's plan to my Google Calendar as reminders. Show me the list, then add them when I say yes.", { send: true });
        } }]);
    } });
  }

  function redoWeekBtn(label) {
    return IG.btn(label || "Redo the week", { cls: "ghost", icon: "refresh", onClick: function () {
      var note = IG.textarea("note", { rows: 3, placeholder: "Optional. e.g. I have an audition on Thursday; more carousels; no political posts" });
      IG.dialog("Plan the week again?", h("div", { class: "stack-sm" },
        h("p", { text: "Claude rebuilds the week from scratch. Posts you already filmed keep their footage." }),
        IG.field("Anything Claude should know", note)), [
        { label: "Cancel" },
        { label: "Replan", primary: true, onClick: function (close) {
          return IG.post("/api/week/prepare", { note: note.value }).then(function () { close(); IG.render("week"); });
        } }]);
    } });
  }

  function weekView(view, data, m) {
    var w = data.week;
    var today = data.today;
    var hero = h("section", { class: "week-hero" },
      h("div", { class: "grow" },
        h("p", { class: "eyebrow", text: "Week of " + IG.day(w.week_of).toLocaleDateString(undefined, { day: "numeric", month: "long" }) + (data.handle ? " · @" + data.handle : "") }),
        h("h1", { text: w.headline || "This week" }),
        w.bottleneck && w.bottleneck.line ? h("p", { class: "lede" }, h("b", { text: IG.cap(w.bottleneck.key || "Focus") + ": " }), w.bottleneck.line) : null,
        (w.posts || []).some(function (p) { return p.model && p.model.ref; })
          ? h("p", { class: "small muted" }, "Every post copies a reel that's going viral in your niche, not your old posts. ",
            h("a", { href: IG.hashFor("trends", { tab: "viral" }), text: "See the reels" })) : null,
        h("div", { class: "row hero-actions" }, remindersBtn(), redoWeekBtn(w.week_of === data.target ? "Redo the week" : "Plan next week now"))));
    view.appendChild(hero);

    if (data.weeks.length > 1) {
      var opts = data.weeks.slice(-3).map(function (wk) {
        var label = wk === data.this_monday ? "This week" : wk > data.this_monday ? "Next week" : IG.day(wk).toLocaleDateString(undefined, { day: "numeric", month: "short" });
        return [wk, label];
      });
      view.appendChild(IG.seg(opts, w.week_of, function (wk) { IG.go("week", { w: wk }); }, "Week"));
    }

    var ap = data.autopilot;
    if (ap.running) view.appendChild(ap.week_of === w.week_of
      ? prepCard(ap.job, "Replanning this week", "The new plan replaces this one when it's ready.")
      : prepCard(ap.job, "Preparing the week of " + IG.day(ap.week_of || data.target).toLocaleDateString(undefined, { day: "numeric", month: "long" }),
        "This week stays as it is. The new one shows up here when it's ready."));
    else if (data.needs_prepare && !ap.auto_blocked && data.claude) {
      IG.post("/api/week/prepare", { auto: true }).then(function () { if (IG.alive(m)) IG.render("week"); }).catch(function () { /* shown next visit */ });
    }

    // A new day (or 6pm, when the trend reel becomes tomorrow's) brings a new trend reel.
    var loaded = new Date();
    var iv = setInterval(function () {
      if (!IG.alive(m)) { clearInterval(iv); return; }
      var t = new Date();
      if (t.toDateString() !== loaded.toDateString() || (loaded.getHours() < 18 && t.getHours() >= 18)) IG.render("week");
    }, 10 * 60 * 1000);

    view.appendChild(h("div", { class: "week-grid" },
      h("div", { class: "stack" }, dailyCard(data, m), weekList(w, today)),
      h("div", { class: "stack side-col" }, todayCard(w, today), engageCard(w),
        (w.assumptions || []).length ? h("details", { class: "card flat more" }, h("summary", { text: "What Claude assumed" }),
          h("ul", { class: "plain small", style: { marginTop: "10px" } }, w.assumptions.map(function (a) { return h("li", { text: a }); })),
          h("p", { class: "small muted", style: { marginTop: "8px" }, text: "Wrong? Tell Claude, or replan with a note." })) : null)));
  }

  function failedView(view, data) {
    var ap = data.autopilot;
    var kweo = /kweo|log in|logged in/i.test(ap.error || "");
    view.appendChild(h("section", { class: "card prep failed" },
      h("h2", { text: "The week isn't ready" }),
      h("p", { class: "pre", text: ap.error || "Claude stopped before the week was ready." }),
      kweo && IG.kweoConnectBox ? IG.kweoConnectBox(function () { IG.render("week"); }) : null,
      h("div", { class: "row" },
        IG.btn("Prepare my week", { cls: "primary", icon: "refresh", onClick: function () {
          return IG.post("/api/week/prepare", {}).then(function () { IG.render("week"); });
        } }),
        IG.btn("See what Claude did", { cls: "ghost", icon: "chat", onClick: function () { IG.openChat(); } }))));
  }

  IG.screen("week", {
    title: "This week", icon: "week", wide: true,
    render: function (view, params, m) {
      view.appendChild(IG.loading("Opening your week…"));
      var q = params.w ? "?" + IG.q({ week_of: params.w }) : "";
      return IG.get("/api/week" + q).then(function (data) {
        if (!IG.alive(m)) return;
        IG.clear(view);
        IG.weekData = data;
        if (!data.claude) { view.appendChild(IG.installCard()); return; }
        var ap = data.autopilot;
        if (params.new || (!data.week && !data.scanned && !data.handle && !ap.running)) { onboarding(view, data); return; }
        if (data.week) { weekView(view, data, m); return; }
        if (ap.running) {
          view.appendChild(prepCard(ap.job, data.scanned ? "Preparing your week" : "Getting to know @" + (data.handle || "your account"),
            data.scanned ? "Scripts, filming notes and captions for every post. About 10 minutes."
              : "Reading the account first, then the week: scripts, filming notes, captions. About 10 to 15 minutes."));
          return;
        }
        if (ap.auto_blocked || ap.status === "error" || ap.status === "cancelled") {
          if (ap.status === "cancelled") ap.error = "You stopped the last run.";
          failedView(view, data);
          return;
        }
        return IG.post("/api/week/prepare", { auto: true }).then(function () { if (IG.alive(m)) IG.render("week"); });
      });
    }
  });
})();
