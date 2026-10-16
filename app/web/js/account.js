/* Account: read the account with ig-scan and show what it found. */
(function () {
  "use strict";
  var h = IG.h;
  var MIX_COLORS = { reel: "var(--accent)", carousel: "var(--info)", photo: "var(--warn)", image: "var(--warn)", story: "var(--ok)", video: "var(--faint)" };
  var READS_ONLY = "Reads only. Nothing is liked, followed or posted.";

  /* kweo status in IG Studio's words (kweo_check's own text is written for the terminal). */
  IG.kweoText = function (k) {
    if (k.ready) return "Connected. Claude can read pages in kweo, and edit your profile only when you approve it.";
    if (!k.app) return "kweo isn't installed. Get it from kweo.ai, open it, then check again.";
    if (k.process === false) return "kweo is installed but not running. Open kweo, then check again.";
    if (k.server === "off") return "In kweo press ⌘J, open the model picker, choose “Connect a model…” and turn on “Let Claude control kweo”. Then check again.";
    if (k.server === "auth" || k.server === "open") return "kweo is running. Copy the command it shows (⌘J → Connect a model) and paste it below.";
    return k.next || "kweo isn't connected yet.";
  };

  /* Paste-the-kweo-command box (also used in Settings). */
  /* One-click kweo connect. kweo connects itself to Claude Code (its own confirm
     dialog, its own `claude mcp add`); IG Studio just asks and then watches until
     the connection shows up. Copy-paste stays as a last resort. */
  IG.kweoConnectBox = function (onDone) {
    var out = h("div", { class: "stack-sm" });
    var btn = IG.btn("Connect kweo", { cls: "primary" });
    var polling = null;
    function stop() { if (polling) { clearInterval(polling); polling = null; } }
    function watch(seconds) {
      stop();
      var until = Date.now() + seconds * 1000;
      polling = setInterval(function () {
        if (!document.body.contains(btn)) { stop(); return; }
        IG.get("/api/kweo").then(function (k) {
          if (k.ready) {
            stop();
            btn.disabled = true;
            IG.clear(out).appendChild(IG.note("ok", "kweo is connected. IG Studio can now read Instagram through it."));
            IG.toast("kweo connected", "ok");
            if (onDone) onDone(k);
          } else if (Date.now() > until) {
            stop(); btn.disabled = false; btn.textContent = "Try again";
          }
        }).catch(function () { /* keep waiting */ });
      }, 2000);
    }
    function showToggleHelp(lead) {
      IG.clear(out).appendChild(IG.note("info", lead));
      out.appendChild(h("ol", { class: "kweo-steps" },
        h("li", null, "In kweo, press ", h("strong", { text: "⌘J" }), " and open ", h("strong", { text: "Connect a model" }), "."),
        h("li", null, "Turn ", h("strong", { text: "Let Claude control kweo" }), " on. If it is already on, turn it off and on again."),
        h("li", { text: "kweo connects itself. This page notices within a few seconds." })));
      out.appendChild(pasteFallback());
    }
    btn.addEventListener("click", function () {
      btn.disabled = true; btn.textContent = "Waiting for kweo…";
      IG.post("/api/kweo/one-click").then(function (r) {
        if (r.launched) {
          IG.clear(out).appendChild(IG.note("info", "Switch to kweo and click Connect in the dialog it shows. This page updates by itself."));
          setTimeout(function () {
            if (polling && !btn.disabled) return;
            if (polling) showToggleHelp("No dialog in kweo? Your kweo may be older. Do this instead:");
          }, 12000);
        } else {
          showToggleHelp("Do this in kweo (takes 10 seconds):");
        }
        watch(180);
      }, function (e) { btn.disabled = false; btn.textContent = "Connect kweo"; IG.clear(out).appendChild(IG.note("bad", e.message)); });
    });
    return h("div", { class: "stack-sm" },
      h("div", { class: "row" }, btn, h("span", { class: "small muted", text: "kweo asks you to confirm, then connects itself. Your kweo key never passes through IG Studio." })),
      out);
  };

  function pasteFallback() {
    var ta = IG.textarea("kweo_cmd", { rows: 3, spellcheck: "false", autocomplete: "off", placeholder: 'claude mcp add kweo --transport http http://127.0.0.1:7333/mcp --header "Authorization: Bearer …"' });
    ta.classList.add("mono");
    var msg = h("div");
    var form = h("form", { class: "stack-sm" },
      IG.field("Paste the command kweo shows", ta, "In ⌘J → Connect a model, copy the command under the toggle."),
      h("div", { class: "row" }, IG.btn("Connect with this command", { type: "submit" })),
      msg);
    form.addEventListener("submit", function (e) {
      e.preventDefault();
      IG.busy(form.querySelector("button"), function () {
        return IG.post("/api/kweo/connect", { command: ta.value }).then(function () {
          ta.value = "";
          IG.clear(msg).appendChild(IG.note("ok", "Done. kweo is connected to Claude Code."));
        }, function (err) { IG.clear(msg).appendChild(IG.note("bad", err.message)); });
      });
    });
    return h("details", { class: "kweo-paste" }, h("summary", { text: "Still stuck? Paste the command instead" }), form);
  }

  function sourcePanel(kind, handleInput, refresh) {
    var box = h("div", { class: "stack-sm" });
    var handle = function () { var v = handleInput.value.trim().replace(/^@/, ""); return v ? "@" + v : ""; };
    if (kind === "kweo") {
      var status = h("div");
      box.appendChild(h("p", { class: "muted", text: "kweo is your own browser, already logged in to Instagram. Claude opens your profile in a new kweo tab and reads your latest posts. No passwords, no keys." }));
      box.appendChild(IG.note("info", READS_ONLY));
      box.appendChild(h("div", { class: "row" }, IG.btn("Read with kweo", {
        cls: "primary", icon: "eye", onClick: function () {
          if (!handle()) { handleInput.focus(); IG.toast("Type your handle first.", "bad"); return; }
          if (!IG.claudeReady()) { IG.toast("Install Claude Code first (Settings).", "bad"); return; }
          return IG.get("/api/kweo").then(function (k) {
            if (k.ready) { IG.ask("/ig-scan " + handle() + " using kweo", { send: true }); return; }
            IG.clear(status).appendChild(h("div", { class: "card tint stack-sm" },
              h("h3", { text: "kweo isn't connected yet" }),
              h("p", { class: "small", text: IG.kweoText(k) }),
              k.app && (k.server === "auth" || k.server === "open") ? IG.kweoConnectBox() : null,
              h("p", { class: "small muted", text: "Or pick another source above: your data download or screenshots work without kweo." })));
          });
        }
      })));
      box.appendChild(status);
    } else if (kind === "dyi") {
      var file = h("input", { type: "file", accept: ".zip,application/zip", id: "dyi-file" });
      var fol = IG.input("followers", { type: "number", min: "0", placeholder: "e.g. 1460" });
      var prog = h("div");
      box.appendChild(h("ol", { class: "small muted", style: { margin: 0, paddingLeft: "20px" } },
        h("li", { text: "Instagram → Accounts Center → Your information and permissions → Download your information." }),
        h("li", { text: "Pick this account, format JSON (not HTML), date range all time, low media quality." }),
        h("li", { text: "Meta emails a link (can take hours). Download the zip and pick it here." })));
      box.appendChild(h("div", { class: "form-grid" }, IG.field("Export zip", file), IG.field("Followers now (optional)", fol, "The export doesn't include it.")));
      box.appendChild(h("div", { class: "row" }, IG.btn("Read the export", {
        cls: "primary", icon: "upload", onClick: function () {
          var f = file.files && file.files[0];
          if (!f) { IG.toast("Pick the zip first.", "bad"); return; }
          var bar = h("div", { class: "progress" }, h("i"));
          IG.clear(prog).appendChild(h("div", { class: "stack-sm" }, h("span", { class: "small muted", text: "Uploading " + f.name + "…" }), bar));
          return IG.upload(f, "zip", function (p) { bar.firstChild.style.width = Math.round(p * 100) + "%"; }).then(function (up) {
            return IG.runJob(IG.post("/api/scan/dyi", { path: up.path, handle: handle(), followers: fol.value }), prog, { label: "Reading your export…" });
          }).then(function () { IG.toast("Scan done"); refresh(); });
        }
      })), prog);
      box.appendChild(IG.note("", READS_ONLY + " The zip stays in your data folder."));
    } else if (kind === "shots") {
      box.appendChild(h("p", { class: "muted", text: "Screenshot the top of your profile, your grid, and the insights of your latest posts. Claude reads them, copies captions word for word and leaves unknown numbers empty." }));
      box.appendChild(IG.claudeReady() ? IG.screenshotAsk("/ig-scan " + (handle() || "my account") + ": read these screenshots of my profile and posts, write the captured JSON (source screenshot), ingest it, then analyze and show me the summary.", "Upload screenshots") : IG.installCard());
      handleInput.addEventListener("change", function () { refresh(true); });
    } else if (kind === "api") {
      var tok = IG.input("token", { type: "password", autocomplete: "off", spellcheck: "false", placeholder: "IGAA…" });
      var max = IG.input("max", { type: "number", min: "1", max: "2000", value: "200" });
      var ins = h("input", { type: "checkbox", name: "insights" });
      var prog2 = h("div");
      box.appendChild(h("p", { class: "muted", text: "For professional accounts with a developer app and an Instagram API with Instagram Login token. Read-only GET requests to graph.instagram.com." }));
      box.appendChild(h("div", { class: "form-grid" }, IG.field("Access token", tok, "Used for this one scan only. Never saved or logged.", "span-2"), IG.field("Max posts", max)));
      box.appendChild(h("label", { class: "check" }, ins, "Also read per-post insights (needs the insights permission)"));
      box.appendChild(h("div", { class: "row" }, IG.btn("Scan with the API", {
        cls: "primary", icon: "lock", onClick: function () {
          if (!tok.value.trim()) { tok.focus(); return; }
          var p = IG.post("/api/scan/api", { token: tok.value.trim(), max: max.value, insights: ins.checked });
          tok.value = "";
          return IG.runJob(p, prog2, { label: "Reading your account…" }).then(function () { IG.toast("Scan done"); refresh(); });
        }
      })), prog2);
    }
    return box;
  }

  function mixBar(mix) {
    var keys = Object.keys(mix || {}).filter(function (k) { return mix[k] > 0; });
    if (!keys.length) return null;
    var tot = keys.reduce(function (a, k) { return a + mix[k]; }, 0);
    return h("div", null,
      h("div", { class: "mix", role: "img", "aria-label": keys.map(function (k) { return k + " " + Math.round(mix[k]) + "%"; }).join(", ") },
        keys.map(function (k) { return h("i", { style: { width: (mix[k] / tot * 100) + "%", background: MIX_COLORS[k] || "var(--faint)" } }); })),
      h("div", { class: "legend" }, keys.map(function (k) { return h("span", null, h("b", { style: { background: MIX_COLORS[k] || "var(--faint)" } }), IG.cap(k) + " " + Math.round(mix[k]) + "%"); })));
  }

  function postsTable(rows, title) {
    if (!rows || !rows.length) return null;
    return h("div", { class: "stack-sm" }, h("h3", { text: title }),
      h("div", { class: "table-wrap" }, h("table", { class: "t" },
        h("thead", null, h("tr", null, h("th", { text: "Date" }), h("th", { text: "Type" }), h("th", { text: "First line" }), h("th", { class: "n", text: "Views" }), h("th", { class: "n", text: "Likes" }), h("th", { class: "n", text: "×" }))),
        h("tbody", null, rows.map(function (p) {
          return h("tr", null, h("td", { class: "num", text: IG.date(p.date) }), h("td", { text: p.type || "" }),
            h("td", { class: "first" }, h("div", { class: "ellipsis", title: p.first_line || "", text: p.first_line || "" })),
            h("td", { class: "n", text: IG.compact(p.views) }), h("td", { class: "n", text: IG.compact(p.likes) }),
            h("td", { class: "n" }, h("span", { class: "badge " + (p.outlier >= 1.2 ? "ok" : p.outlier < 0.8 ? "bad" : ""), text: (p.outlier != null ? p.outlier.toFixed(2) : "–") + "×" })));
        })))));
  }

  function bestOf(list) { return (list || []).filter(function (g) { return !g.thin && g.group !== "unclassified"; })[0] || null; }

  function analysisView(data, refresh) {
    var a = data.account || {};
    var size = a.size || {}, cad = a.cadence || {}, perf = a.performance || {}, wp = a.what_performs || {}, niche = a.niche_guess || {};
    var wrap = h("div", { class: "stack" });
    wrap.appendChild(h("div", { class: "card" },
      h("div", { class: "card-h" },
        h("div", null, h("h2", { text: "@" + (a.handle || "account") + (a.name ? " · " + a.name : "") }),
          h("div", { class: "sub", text: "Scanned " + IG.date((a.scanned_at || "").slice(0, 10)) + " from " + (a.sources || [a.source]).join(", ") + " · " + IG.n(a.n_feed) + " posts read" })),
        IG.btn("Re-run analysis", { cls: "sm", icon: "refresh", onClick: function () { return IG.post("/api/scan/analyze").then(function () { IG.toast("Analysis updated"); refresh(); }); } })),
      a.bio ? h("p", { class: "pre", text: a.bio }) : null,
      h("p", { class: "small muted", style: { marginTop: "10px" }, text: "Claude uses this to plan every week: your niche, voice and what already works. Rescan any time; it does so itself every month." })));

    wrap.appendChild(h("div", { class: "stats" },
      IG.stat("Followers", IG.n(size.followers), size.following != null ? "following " + IG.n(size.following) : null),
      IG.stat("Size tier", IG.cap(size.tier || "–"), size.posts_count ? IG.n(size.posts_count) + " posts on profile" : null),
      IG.stat("Posts / week", cad.per_week_30d != null ? String(cad.per_week_30d) : "–", cad.per_week_90d != null ? cad.per_week_90d + " over 90 days" : null),
      IG.stat("Consistency", cad.consistency != null ? cad.consistency + "%" : "–", cad.longest_gap_days != null ? "longest gap " + cad.longest_gap_days + "d" : null),
      IG.stat("Engagement", perf.er_median != null ? perf.er_median + "%" : "–", "median per post"),
      data.niche ? IG.stat("Niche", data.niche, "Claude's read") : IG.stat("Niche guess", niche.label || "–", niche.confidence ? niche.confidence + " confidence" : null)));

    var fm = a.format_mix || {};
    var best = [["Best format", bestOf(wp.format)], ["Best hook formula", bestOf(wp.formula)], ["Best theme", bestOf(wp.theme)]];
    wrap.appendChild(h("div", { class: "grid-2" },
      IG.card("Format mix", fm.basis ? "Recent shift: " + Object.keys(fm.shift_pts || {}).map(function (k) { var v = fm.shift_pts[k]; return k + " " + (v > 0 ? "+" : "") + Math.round(v) + " pts"; }).join(", ") : null,
        h("div", { class: "stack-sm" }, mixBar(fm.all) || h("p", { class: "muted", text: "No posts read yet." }),
          fm.recent ? h("div", null, h("div", { class: "small muted", style: { margin: "8px 0 4px" }, text: "Last 30 days" }), mixBar(fm.recent)) : null)),
      IG.card("What performs", "Mean multiple over the account median", h("div", { class: "stack-sm" },
        best.map(function (b) {
          return h("div", { class: "row between" }, h("span", { class: "muted", text: b[0] }),
            b[1] ? h("span", null, h("b", { text: b[1].group }), " ", h("span", { class: "badge ok", text: b[1].mean_outlier + "× · n=" + b[1].n })) : h("span", { class: "faint", text: "not enough posts" }));
        }),
        a.worst_habit ? IG.note("warn", typeof a.worst_habit === "string" ? a.worst_habit : (a.worst_habit.text || a.worst_habit.label || JSON.stringify(a.worst_habit))) : null))));

    var tops = h("div", { class: "card stack" }, postsTable(perf.top, "Top posts"), postsTable(perf.bottom, "Bottom posts"));
    if (tops.childNodes.length) wrap.appendChild(tops);
    if (a.honesty && a.honesty.length) wrap.appendChild(IG.note("info", h("div", null, h("b", { text: "How sure this is" }), h("ul", { style: { margin: "4px 0 0", paddingLeft: "18px" } }, a.honesty.map(function (x) { return h("li", { text: x }); })))));
    if (data.md) wrap.appendChild(h("details", { class: "card more" }, h("summary", { text: "Full report (account.md)" }), h("div", { style: { marginTop: "12px" } }, IG.md(data.md))));
    return wrap;
  }

  /* ---------- profile fixes: tick, edit, "Fix all with kweo" */
  var FIELD_LABEL = { name: "Name", bio: "Bio", pin: "Pin", unpin: "Unpin", pins: "Pins", highlights: "Highlights", covers: "Grid covers", website: "Link", category: "Category", contact: "Contact", photo: "Photo" };
  var LIMIT = { name: 30, bio: 150 };
  var RESULT_TEXT = { done: "✓ Changed", would_change: "Would change", failed: "✗ Failed", skipped: "Skipped" };

  function profileFixes(d, refresh) {
    var web = d.changes.filter(function (c) { return !c.app_only; });
    var app = d.changes.filter(function (c) { return c.app_only; });
    var results = {};
    ((d.result && d.result.results) || []).forEach(function (r) { results[r.id] = r; });
    var rows = web.map(function (c) {
      var box = h("input", { type: "checkbox", checked: true });
      var edit = null, count = null;
      if (LIMIT[c.field]) {
        edit = c.field === "bio" ? IG.textarea("v", { rows: 3, maxlength: String(LIMIT.bio) }) : IG.input("v", { maxlength: String(LIMIT.name) });
        edit.value = c.value || "";
        count = h("span", { class: "tiny faint num" });
        var upd = function () { count.textContent = edit.value.length + " / " + LIMIT[c.field]; };
        edit.addEventListener("input", upd); upd();
      }
      var r = results[c.id];
      return { c: c, box: box, edit: edit, el: h("div", { class: "fix-row" },
        h("label", { class: "check" }, box, h("b", { text: FIELD_LABEL[c.field] || c.field })),
        h("div", { class: "stack-sm grow" },
          edit ? h("div", null, edit, h("div", { class: "row between" }, c.current ? h("span", { class: "tiny faint", text: "Now: " + c.current }) : h("span"), count))
               : h("div", null, h("a", { href: c.post_url, target: "_blank", rel: "noopener", text: c.label || c.post_url })),
          c.why ? h("div", { class: "small muted", text: c.why }) : null,
          r ? h("div", { class: "small " + (r.status === "done" ? "ok-text" : r.status === "failed" ? "bad-text" : "muted"), text: (RESULT_TEXT[r.status] || r.status) + (r.note ? ": " + r.note : "") }) : null)) };
    });
    var out = h("div");
    var k = d.kweo || {};
    function chosen() {
      return rows.filter(function (r) { return r.box.checked; }).map(function (r) { return r.edit ? { id: r.c.id, value: r.edit.value } : { id: r.c.id }; });
    }
    function run(dry) {
      var items = chosen();
      if (!items.length) { IG.toast("Tick at least one change.", "bad"); return; }
      var list = h("ul", { class: "small" }, items.map(function (it) {
        var r = rows.filter(function (x) { return x.c.id === it.id; })[0];
        return h("li", { style: { whiteSpace: "pre-line" } }, h("b", { text: (FIELD_LABEL[r.c.field] || r.c.field) + ": " }), it.value != null ? it.value : (r.c.label || r.c.post_url));
      }));
      var go = function () {
        return IG.post("/api/profile/apply", { items: items, dry_run: !!dry }).then(function (res) {
          return watchFix(res.job, out, dry).then(refresh);
        });
      };
      if (dry) return go();
      IG.dialog("Change these on @" + (d.handle || "your account") + "?", h("div", { class: "stack-sm" },
        h("p", { class: "small", text: "kweo will open Instagram in your browser and make only these changes, exactly as written. It checks it is logged in as @" + (d.handle || "") + " first, and stops at any password or security prompt." }),
        list, h("p", { class: "small muted", text: "It never posts, likes, follows, comments or messages. Instagram limits name changes to twice in 14 days." })),
        [{ label: "Cancel" }, { label: "Fix with kweo", primary: true, onClick: function (close) { close(); return go(); } }]);
    }
    var kweoOk = !!(k.ready);
    var ready = kweoOk && IG.claudeReady();
    var fixBtn = IG.btn("Fix all with kweo", { cls: "primary", icon: "check", onClick: function () { return run(false); } });
    var dryBtn = IG.btn("Dry run", { cls: "ghost", title: "kweo checks each change on Instagram but saves nothing", onClick: function () { return run(true); } });
    fixBtn.disabled = dryBtn.disabled = !ready;
    return IG.card("Profile fixes", (d.score_now != null ? "Score " + d.score_now + "/100 now, about " + d.score_after + " after these. " : "") + "Tick what to change. You can edit the text first.",
      h("div", { class: "stack" },
        web.length ? h("div", { class: "stack-sm" }, rows.map(function (r) { return r.el; })) : null,
        web.length ? h("div", { class: "row" },
          fixBtn, dryBtn,
          !kweoOk ? h("span", { class: "small muted", text: "Open kweo and connect it first (Settings)." }) : null) : null,
        out,
        app.length ? h("div", { class: "stack-sm" }, h("h3", { text: "Do these in the Instagram app" }),
          h("p", { class: "small muted", text: "Instagram only lets you change these on your phone." }),
          app.map(function (c) {
            return h("div", { class: "fix-row" }, h("b", { text: FIELD_LABEL[c.field] || c.field }),
              h("div", { class: "stack-sm grow" }, h("div", { class: "pre small", text: c.value || "" }), c.why ? h("div", { class: "small muted", text: c.why }) : null),
              c.value ? IG.btn("Copy", { cls: "sm ghost", onClick: function () { return navigator.clipboard.writeText(c.value).then(function () { IG.toast("Copied"); }); } }) : null);
          })) : null));
  }

  function watchFix(job, out, dry) {
    IG.clear(out);
    var steps = h("ol", { class: "steps small" });
    out.appendChild(h("div", { class: "stack-sm" }, h("div", { class: "row" }, h("span", { class: "spin" }), h("span", { class: "small muted", text: dry ? "Dry run: kweo is checking each change without saving…" : "kweo is changing your profile. Watch it in kweo…" })), steps));
    var seen = {};
    return new Promise(function (resolve) {
      IG.stream(job, function (ev) {
        if (ev.type === "tool" && ev.summary && !seen[ev.summary] && !/^(Reading|Searching|Loading)/.test(ev.summary)) { seen[ev.summary] = 1; steps.appendChild(h("li", { text: ev.summary })); }
        if (ev.type === "end") {
          IG.toast(ev.status === "done" ? (dry ? "Dry run finished" : "Profile updated, check the results") : "kweo stopped", ev.status === "done" ? null : "bad");
          resolve();
        }
      });
    });
  }

  IG.screen("account", {
    title: "Account", icon: "account", group: "results",
    render: function (view, params, m) {
      view.classList.add("stack");
      view.appendChild(IG.loading());
      var refresh = function () { IG.render("account"); };
      return Promise.all([IG.get("/api/scan"), IG.get("/api/state?quick=1").catch(function () { return null; })]).then(function (res) {
        var data = res[0];
        data.niche = res[1] && res[1].profile ? res[1].profile.niche : null;
        if (!IG.alive(m)) return;
        IG.clear(view);
        var fixBox = h("div");
        view.appendChild(fixBox);
        Promise.all([IG.get("/api/profile/changes"), IG.get("/api/kweo").catch(function () { return {}; })]).then(function (r) {
          var d = r[0]; d.kweo = r[1];
          if (d.changes && d.changes.length && IG.alive(m)) fixBox.appendChild(profileFixes(d, refresh));
        }).catch(function () { /* the card is optional */ });
        if (!data.available) view.appendChild(IG.note("warn", "The account scanner (ig-scan) isn't installed in your skills folder yet. Everything else works; come back here once it's installed."));
        var handleInput = IG.input("handle", { placeholder: "yourhandle", autocomplete: "off", spellcheck: "false",
          value: (data.account && data.account.handle) || (IG.accounts && IG.accounts.active) || "" });
        var panel = h("div");
        var src = "kweo";
        var show = function (k) { src = k; IG.clear(panel).appendChild(sourcePanel(k, handleInput, refresh)); };
        var card = h("section", { class: "card stack-sm" },
          h("div", { class: "card-h", style: { marginBottom: "4px" } }, h("div", null, h("h2", { text: data.has_analysis ? "Read your account again" : "Read your account" }),
            h("div", { class: "sub", text: "Only accounts you own or manage for a client." }))),
          h("div", { class: "form-grid", style: { maxWidth: "460px" } }, IG.field("Instagram handle", handleInput, "Files go to the active account's folder (top right).")),
          h("div", { class: "field" }, h("span", { text: "How should IG Studio read it?" }),
            IG.seg([["kweo", "kweo browser · recommended"], ["dyi", "Data download"], ["shots", "Screenshots"], ["api", "Advanced: API token"]], src, show, "Source")),
          panel);
        show("kweo");
        if (data.has_analysis) {
          view.appendChild(analysisView(data, refresh));
          view.appendChild(h("details", { class: "more" }, h("summary", { text: "Rescan" }), h("div", { style: { marginTop: "12px" } }, card)));
        } else if (data.available) {
          view.appendChild(card);
          view.appendChild(h("div", { class: "card tint" }, h("h3", { text: "What you get" }),
            h("p", { class: "muted small", style: { marginTop: "6px" }, text: "Size tier, posting cadence, format mix, engagement, your top and bottom posts, themes, hashtags, languages, the hook formulas you already use, and a niche guess. Every other skill uses it as context." })));
        }
      });
    }
  });
})();
