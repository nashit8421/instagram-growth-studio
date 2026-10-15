/* Today: the home screen. Stage, next steps, and the first-run wizard. */
(function () {
  "use strict";
  var h = IG.h;

  IG.COUNTRIES = [["US", "United States"], ["IN", "India"], ["GB", "United Kingdom"], ["CA", "Canada"], ["AU", "Australia"],
    ["NZ", "New Zealand"], ["IE", "Ireland"], ["DE", "Germany"], ["FR", "France"], ["ES", "Spain"], ["IT", "Italy"],
    ["NL", "Netherlands"], ["SE", "Sweden"], ["PL", "Poland"], ["PT", "Portugal"], ["BR", "Brazil"], ["MX", "Mexico"],
    ["AR", "Argentina"], ["CO", "Colombia"], ["AE", "United Arab Emirates"], ["SA", "Saudi Arabia"], ["EG", "Egypt"],
    ["TR", "Türkiye"], ["PK", "Pakistan"], ["BD", "Bangladesh"], ["LK", "Sri Lanka"], ["NP", "Nepal"], ["ID", "Indonesia"],
    ["PH", "Philippines"], ["MY", "Malaysia"], ["SG", "Singapore"], ["TH", "Thailand"], ["VN", "Vietnam"], ["JP", "Japan"],
    ["KR", "South Korea"], ["NG", "Nigeria"], ["KE", "Kenya"], ["ZA", "South Africa"], ["GH", "Ghana"]];
  var LANGS = [["en", "English"], ["hi", "Hindi"], ["es", "Spanish"], ["pt", "Portuguese"], ["fr", "French"], ["de", "German"],
    ["ar", "Arabic"], ["ur", "Urdu"], ["id", "Indonesian"], ["it", "Italian"], ["tr", "Turkish"], ["ja", "Japanese"], ["ko", "Korean"],
    ["bn", "Bengali"], ["ta", "Tamil"], ["te", "Telugu"], ["mr", "Marathi"]];

  /* ---------- shared forms */
  IG.profileForm = function (initial, onSaved, opts) {
    initial = initial || {};
    opts = opts || {};
    var known = IG.COUNTRIES.some(function (c) { return c[0] === String(initial.region || "").toUpperCase(); });
    var region = IG.select("region_pick", [["", "Choose a country…"]].concat(IG.COUNTRIES.map(function (c) { return [c[0], c[1] + " (" + c[0] + ")"]; })).concat([["__other", "Somewhere else…"]]),
      known ? String(initial.region).toUpperCase() : (initial.region ? "__other" : ""));
    var other = IG.input("region_other", { placeholder: "Country code or region, e.g. LATAM", value: known ? "" : (initial.region || "") });
    var otherField = IG.field("Region", other, "A 2-letter country code works best.");
    otherField.hidden = region.value !== "__other";
    region.addEventListener("change", function () { otherField.hidden = region.value !== "__other"; if (!otherField.hidden) other.focus(); });
    var niche = IG.input("niche", { placeholder: "e.g. contracts and pricing for freelance designers", value: initial.niche || "", required: true });
    var type = IG.select("account_type", [["", "Choose…"], ["creator", "Creator"], ["business", "Business"]], initial.account_type || "");
    var lang = IG.select("language", [["", "Choose…"]].concat(LANGS.map(function (l) { return [l[0], l[1]]; })), initial.language || "en");
    var goal = IG.input("goal", { placeholder: "e.g. 10k followers by March", value: initial.goal || "" });
    var why = opts.why || {};
    var hint = function (k, d) { return why[k] ? "Suggested: " + why[k] : d; };
    var form = h("form", { class: "stack-sm", novalidate: true },
      h("div", { class: "form-grid" },
        IG.field("Where is your audience?", region, hint("region", "Your audience's country, not necessarily yours.")),
        otherField,
        IG.field("Account type", type, hint("account_type", "Instagram → Settings → Account type.")),
        IG.field("Your niche, in your words", niche, hint("niche", "What you post about and for whom."), "span-all"),
        IG.field("Language", lang, hint("language")),
        IG.field("Goal (optional)", goal)),
      h("div", { class: "row" }, IG.btn(opts.submitLabel || "Save profile", { cls: "primary", type: "submit" }), opts.extra || null));
    form.addEventListener("submit", function (e) {
      e.preventDefault();
      var r = region.value === "__other" ? other.value.trim() : region.value;
      if (!r || !niche.value.trim() || !type.value) { IG.toast("Region, niche and account type are needed.", "bad"); return; }
      var btn = form.querySelector("button[type=submit]");
      IG.busy(btn, function () {
        return IG.post("/api/profile", { region: r, niche: niche.value.trim(), account_type: type.value, language: lang.value, goal: goal.value.trim() })
          .then(function (res) { IG.toast("Profile saved"); if (onSaved) onSaved(res.profile); });
      });
    });
    return form;
  };

  IG.followersForm = function (onSaved, opts) {
    opts = opts || {};
    var n = IG.input("followers", { type: "number", min: "0", inputmode: "numeric", placeholder: "e.g. 1460", value: opts.value || "", required: true });
    var form = h("form", { class: "row", style: { alignItems: "flex-end" } },
      h("div", { style: { flex: "1 1 200px", maxWidth: "260px" } }, IG.field(opts.label || "Followers right now", n, opts.hint)),
      IG.btn(opts.submitLabel || "Save", { cls: "primary", type: "submit" }));
    form.addEventListener("submit", function (e) {
      e.preventDefault();
      if (n.value === "") { n.focus(); return; }
      IG.busy(form.querySelector("button"), function () {
        return IG.post("/api/grow/checkin", { followers: n.value }).then(function (res) { IG.toast("Logged " + IG.n(n.value) + " followers"); if (onSaved) onSaved(res); });
      });
    });
    return form;
  };

  IG.voiceForm = function (prefill) {
    var areas = [0, 1, 2].map(function (i) {
      return IG.textarea("cap" + i, { rows: 3, placeholder: "Caption or reel transcript " + (i + 1), value: (prefill && prefill[i]) || "" });
    });
    var form = h("form", { class: "stack-sm" },
      areas.map(function (a, i) { return IG.field("Your post " + (i + 1), a); }),
      h("div", { class: "row" }, IG.btn("Write my voice with Claude", { cls: "primary", type: "submit", icon: "assistant" }),
        h("span", { class: "small muted", text: "Claude writes voice.md in your data folder and shows you a summary." })));
    form.addEventListener("submit", function (e) {
      e.preventDefault();
      var caps = areas.map(function (a) { return a.value.trim(); }).filter(Boolean);
      if (caps.length < 2) { IG.toast("Paste at least two of your own captions.", "bad"); return; }
      if (!IG.claudeReady()) { IG.toast("Install Claude Code first (see Settings).", "bad"); return; }
      var prompt = "/ig-reel Do only the voice step: write voice.md in my data folder from these captions of mine. Then show me a short summary of my voice.\n\n" +
        caps.map(function (c, i) { return "Caption " + (i + 1) + ":\n" + c; }).join("\n\n");
      IG.ask(prompt, { send: true });
    });
    return form;
  };

  IG.screenshotAsk = function (prompt, label) {
    var file = h("input", { type: "file", accept: "image/*", multiple: true, class: "sr", id: "shot-" + Math.random().toString(36).slice(2) });
    var status = h("span", { class: "small muted" });
    var lab = h("label", { class: "btn primary", for: file.id }, IG.icon("upload"), h("span", { text: label || "Upload screenshot" }));
    file.addEventListener("change", function () {
      var files = Array.prototype.slice.call(file.files || []);
      if (!files.length) return;
      if (!IG.claudeReady()) { IG.toast("Install Claude Code first (see Settings).", "bad"); return; }
      status.textContent = "Uploading…";
      Promise.all(files.map(function (f) { return IG.upload(f, "image"); })).then(function (ups) {
        IG.ask(prompt, { send: true, attachments: ups.map(function (u) { return { path: u.path, name: u.name, url: u.url }; }) });
      }).catch(function (e) { status.textContent = ""; IG.fail(e); });
    });
    return h("div", { class: "row" }, file, lab, status);
  };

  /* ---------- step actions */
  function aiStep(key) { return function () { IG.ask("/ig do the step: " + key); }; }
  var STEP_LABEL = {
    scan: "Scan my account", rescan: "Rescan", profile: "Set profile", voice: "Add my voice", baseline: "Log followers",
    profile_score: "Score my profile", perf: "Enter numbers", weekly_review: "Start review", trends: "Find trends",
    plan: "Plan my week", calendar: "Add reminders", create_today: "Make today's post", engage: "Write comments"
  };
  var STEP_TITLE = {
    scan: "Scan your account", rescan: "Refresh your account scan", profile: "Tell IG Studio about your account",
    voice: "Teach Claude your voice", baseline: "Log your starting followers", profile_score: "Fix your profile",
    perf: "Check your recent posts", weekly_review: "Weekly growth review", trends: "Find this week's trends",
    plan: "Plan the week", calendar: "Put the plan in your calendar", create_today: "Make today's post", engage: "20-minute engagement round"
  };

  function stepAction(step, slot, reload) {
    var k = step.key;
    if (k === "scan" || k === "rescan") return { go: function () { IG.go("account"); } };
    if (k === "perf") return { go: function () { IG.go("posts", { focusDue: true }); } };
    if (k === "calendar") return { go: function () { IG.go("calendar"); } };
    if (k === "profile") return { form: function () { return IG.profileForm(IG.state && IG.state.profile, reload); } };
    if (k === "baseline") return { form: function () { return IG.followersForm(reload); } };
    if (k === "voice") return { form: function () { return IG.voiceForm(); } };
    if (k === "weekly_review") return {
      form: function () {
        return IG.followersForm(function (res) {
          IG.ask("/ig do the step: weekly_review. I already logged today's follower check-in (" + IG.n(res && res.row && res.row.followers) + "). Run the report and build this week's plan.", { send: false });
        }, { label: "Followers today", submitLabel: "Log and review" });
      }
    };
    if (k === "profile_score") return {
      form: function () {
        return h("div", { class: "stack-sm" }, h("p", { class: "small muted", text: "Screenshot the top of your profile and the first two grid rows. Claude scores it out of 100 and rewrites what loses points." }),
          IG.screenshotAsk("/ig-profile Score my profile from these screenshots and rewrite the parts that lose points.", "Upload screenshots"));
      }
    };
    return { go: aiStep(k), ai: true };
  }

  function stepCard(step, i, reload) {
    var act = stepAction(step, null, reload);
    var formBox = h("div", { class: "form", hidden: true });
    var btn = IG.btn(STEP_LABEL[step.key] || "Do this", { cls: i === 0 ? "primary" : "", icon: act.ai ? "assistant" : (act.form ? null : "arrow") });
    btn.addEventListener("click", function () {
      if (act.form) {
        if (formBox.hidden) { IG.clear(formBox).appendChild(act.form()); formBox.hidden = false; var f = formBox.querySelector("input, textarea, select"); if (f) f.focus(); }
        else formBox.hidden = true;
      } else act.go();
    });
    return h("div", { class: "step" + (i === 0 ? " first" : "") },
      h("div", { class: "n", text: String(i + 1) }),
      h("div", null,
        h("div", { class: "t" }, STEP_TITLE[step.key] || step.skill, " ", h("span", { class: "badge", text: step.skill.split(" ")[0] })),
        h("div", { class: "why", text: step.why }),
        step.ask && act.ai ? h("div", { class: "ask", text: "Claude will ask: " + step.ask }) : null),
      btn, formBox);
  }

  /* ---------- wizard */
  function wizKey() { return "igwiz:" + IG.accountKey(); }
  function wizSkipped() { try { return JSON.parse(localStorage.getItem(wizKey()) || "[]"); } catch (e) { return []; } }
  function wizSkip(k) { var s = wizSkipped(); if (s.indexOf(k) < 0) s.push(k); try { localStorage.setItem(wizKey(), JSON.stringify(s)); } catch (e) { /* ignore */ } }

  function wizardSteps(st) {
    var keys = st.next.map(function (s) { return s.key; });
    var steps = [];
    if (IG.status && IG.status.scan_available) steps.push({ key: "scan", title: "Your account", done: !!st.scan || keys.indexOf("scan") < 0 });
    steps.push({ key: "profile", title: "Profile", done: keys.indexOf("profile") < 0 });
    steps.push({ key: "baseline", title: "Followers", done: keys.indexOf("baseline") < 0 });
    steps.push({ key: "voice", title: "Voice", done: keys.indexOf("voice") < 0 });
    steps.push({ key: "screenshot", title: "Profile check", optional: true, done: false });
    var skipped = wizSkipped();
    steps.forEach(function (s) { s.skipped = skipped.indexOf(s.key) >= 0; });
    return steps;
  }

  function renderWizard(view, st, reload) {
    var steps = wizardSteps(st);
    var required = steps.filter(function (s) { return !s.optional && !s.done && !s.skipped; });
    if (required.length) IG._wizActive = true;
    var cur = required[0] || (IG._wizActive ? steps.filter(function (s) { return s.optional && !s.skipped; })[0] : null);
    if (!cur) return false;
    var wrap = h("div", { class: "wizard stack" });
    wrap.appendChild(h("div", null, h("h2", { style: { fontSize: "24px" }, text: "Let's set up " + IG.handle() }),
      h("p", { class: "muted", style: { marginTop: "6px" }, text: "A few questions, once. Everything stays on this computer. Nothing is ever posted for you." })));
    wrap.appendChild(h("ol", { class: "wsteps" }, steps.map(function (s, i) {
      var cls = s === cur ? "cur" : (s.done ? "done" : "");
      return h("li", { class: cls, "aria-current": s === cur ? "step" : null }, h("span", { class: "b" }, s.done ? IG.icon("check") : String(i + 1)), s.title + (s.skipped ? " (skipped)" : ""));
    })));
    var body = h("div", { class: "card" });
    var skip = function (label) {
      return IG.btn(label || "Skip for now", { cls: "ghost", onClick: function () { wizSkip(cur.key); reload(); } });
    };
    if (cur.key === "scan") {
      body.appendChild(h("div", { class: "stack-sm" },
        h("h2", { text: "Start from your real account" }),
        h("p", { class: "muted", text: "IG Studio reads your recent posts (with kweo, your data download, or screenshots) and learns your niche, size, cadence and what performs. Every other step gets better with it." }),
        h("div", { class: "row" }, IG.btn("Scan my account", { cls: "primary", icon: "arrow", onClick: function () { IG.go("account"); } }), skip())));
    } else if (cur.key === "profile") {
      var extra = null;
      var formBox = h("div");
      var mount = function (init, why) { IG.clear(formBox).appendChild(IG.profileForm(init, reload, { why: why, submitLabel: "Save and continue", extra: extra })); };
      mount(st.profile);
      body.appendChild(h("div", { class: "stack-sm" }, h("h2", { text: "Where you post, and about what" }),
        h("p", { class: "muted", text: "Every skill uses this: trends come from your region, plans from your niche." }),
        st.scan && IG.status.scan_available ? h("div", null, IG.btn("Fill from my scan", { cls: "sm", icon: "refresh", onClick: function () {
          return IG.post("/api/scan/prefill").then(function (r) { mount(Object.assign({}, st.profile, r.fields), r.why); IG.toast("Suggestions filled in. Check them."); });
        } })) : null, formBox));
    } else if (cur.key === "baseline") {
      var scanF = st.scan && st.scan.followers;
      body.appendChild(h("div", { class: "stack-sm" }, h("h2", { text: "Your starting point" }),
        h("p", { class: "muted", text: "Growth is measured from today. Open Instagram and read the number under Followers." + (scanF ? " The scan read " + IG.n(scanF) + "." : "") }),
        IG.followersForm(reload, { value: scanF || "", submitLabel: "Save and continue" })));
    } else if (cur.key === "voice") {
      var box = h("div");
      box.appendChild(IG.voiceForm());
      if (st.scan && IG.status.scan_available) {
        IG.post("/api/scan/prefill").then(function (r) {
          var caps = (r.typical_captions || []).map(function (c) { return c.caption; });
          if (caps.length) IG.clear(box).appendChild(IG.voiceForm(caps));
        }).catch(function () { /* fine, manual */ });
      }
      body.appendChild(h("div", { class: "stack-sm" }, h("h2", { text: "Sound like you" }),
        h("p", { class: "muted", text: "Paste three of your own captions or reel transcripts. Claude reads them and writes your voice profile, so every script sounds like you." }),
        IG.claudeReady() ? box : IG.installCard(), h("div", null, skip())));
    } else {
      body.appendChild(h("div", { class: "stack-sm" }, h("h2", { text: "Optional: check your profile" }),
        h("p", { class: "muted", text: "A screenshot of the top of your profile and the first two grid rows. Claude scores it and rewrites the bio and name field." }),
        h("div", { class: "row" }, IG.claudeReady() ? IG.screenshotAsk("/ig-profile Score my profile from these screenshots and rewrite the parts that lose points.") : null,
          skip("Skip, show my dashboard"))));
    }
    wrap.appendChild(body);
    wrap.appendChild(h("div", null, h("button", { class: "link-btn small", type: "button", text: "Skip setup and show the dashboard", onclick: function () { steps.forEach(function (s) { wizSkip(s.key); }); reload(); } })));
    view.appendChild(wrap);
    return true;
  }

  /* ---------- dashboard */
  function greeting() {
    var hr = new Date().getHours();
    return hr < 12 ? "Good morning" : hr < 18 ? "Good afternoon" : "Good evening";
  }

  function renderDash(view, st, ctx) {
    var prof = st.profile || {};
    var sc = st.scan;
    var meta = h("div", { class: "meta" },
      h("span", { class: "badge " + (st.stage === "setup" ? "warn" : "ok"), text: st.stage === "setup" ? "Setting up" : "Running" }),
      sc && sc.size_tier ? h("span", { class: "badge accent", text: IG.cap(sc.size_tier) + " account" }) : null,
      prof.niche ? h("span", { class: "badge", text: prof.niche }) : (sc && sc.niche_guess ? h("span", { class: "badge", text: sc.niche_guess + " (guess)" }) : null),
      prof.region ? h("span", { class: "badge", text: prof.region }) : null,
      prof.account_type ? h("span", { class: "badge", text: IG.cap(prof.account_type) }) : null);
    view.appendChild(h("div", { class: "hero" },
      h("div", null, h("div", { class: "muted small", text: new Date().toLocaleDateString(undefined, { weekday: "long", day: "numeric", month: "long" }) }),
        h("h2", { text: greeting() + ", " + (st.account && st.account.indexOf("(") !== 0 ? "@" + st.account : "creator") }), meta),
      IG.btn("Ask Claude", { icon: "assistant", onClick: function () { IG.go("assistant"); } })));

    if (ctx && ctx.lines && ctx.lines.length) {
      view.appendChild(h("details", { class: "card flat more" }, h("summary", { text: "Account context from your scan" }),
        h("div", { class: "planbox", style: { marginTop: "10px" }, text: ctx.lines.join("\n") })));
    }

    var f = st.followers || {}, led = st.ledger || {};
    var voiceTxt = { filled: "Ready", template: "Template only", missing: "Not set" }[st.voice] || st.voice;
    view.appendChild(h("div", { class: "stats" },
      IG.stat("Followers", IG.n(f.count), f.last_checkin ? "checked " + IG.date(f.last_checkin) : "no check-in yet"),
      IG.stat("Posts logged", IG.n(led.posts), (led.posts_last_7d || 0) + " in the last 7 days"),
      IG.stat("Voice", voiceTxt, st.voice === "filled" ? "voice.md" : "scripts need it", st.voice === "filled" ? "up" : "down"),
      IG.stat("Browsing", st.kweo && st.kweo.ready ? "kweo ready" : (st.kweo && st.kweo.ready === null ? "checking…" : "Web search"), st.kweo && st.kweo.ready ? "reads only" : "connect kweo in Settings")));

    if (st.today) {
      var t = st.today;
      view.appendChild(h("div", { class: "slot" },
        h("div", { class: "grow" }, h("div", { class: "day", text: "TODAY · " + t.day }), h("div", { class: "txt", text: t.rest ? "Rest day. No post." : t.text })),
        t.rest ? null : IG.btn("Make it", { cls: "primary", icon: "assistant", onClick: function () { IG.ask("/ig do the step: create_today"); } })));
    }

    var steps = st.next || [];
    view.appendChild(h("div", { class: "section-h" }, h("h2", { text: "Next steps" }), h("span", { class: "sub", text: steps.length + " to go · the first one matters most" })));
    var list = h("div", { class: "steps" });
    var reload = function () { IG.render("today"); };
    steps.forEach(function (s, i) { list.appendChild(stepCard(s, i, reload)); });
    if (!steps.length) list.appendChild(h("div", { class: "card empty" }, h("h3", { text: "All caught up" }), h("p", { text: "Come back tomorrow, or ask Claude for something." })));
    view.appendChild(list);
    if (!IG.claudeReady()) view.appendChild(IG.installCard());
    view.appendChild(h("p", { class: "small faint", text: "Nothing is posted, liked, followed or sent by IG Studio. You post." }));
  }

  IG.screen("today", {
    title: "Today", icon: "today",
    render: function (view, params, m) {
      view.appendChild(IG.loading("Reading your account…"));
      var reload = function () { IG.render("today"); };
      var draw = function (st, ctx) {
        if (!IG.alive(m)) return;
        IG.state = st;
        IG.setBadge("posts", (st.perf_due || []).length);
        var box = IG.clear(view);
        box.classList.add("stack");
        if (!renderWizard(box, st, reload)) renderDash(box, st, ctx);
      };
      var ctxP = IG.get("/api/scan").then(function (s) { return s.context && typeof s.context === "object" ? s.context : null; }).catch(function () { return null; });
      return IG.get("/api/state?quick=1").then(function (st) {
        st.kweo = { ready: null };
        return ctxP.then(function (ctx) {
          draw(st, ctx);
          return IG.get("/api/state").then(function (full) {
            // Re-draw with perf + kweo checks, unless the user already started typing in a form.
            var typing = view.querySelector(".step .form:not([hidden])") || view.querySelector(".wizard");
            if (IG.alive(m) && !typing) draw(full, ctx);
            else if (IG.alive(m)) { IG.state = full; IG.setBadge("posts", (full.perf_due || []).length); }
          }).catch(function () { /* quick state is enough */ });
        });
      });
    }
  });
})();
