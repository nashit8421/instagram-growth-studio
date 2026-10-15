/* Posts: the ledger, numbers checks, audit, Meta import and A/B tests. */
(function () {
  "use strict";
  var h = IG.h;
  var FORMATS = [["reel", "Reel"], ["carousel", "Carousel"], ["story", "Story"], ["photo", "Photo"]];
  var METRIC_FIELDS = [["views", "Views"], ["reach", "Reach"], ["likes", "Likes"], ["comments", "Comments"], ["shares", "Shares / sends"],
    ["saves", "Saves"], ["follows", "Follows"], ["skip_rate", "Skip rate %"], ["nonfollower_pct", "Non-followers %"], ["avg_watch", "Avg watch (s)"]];

  function numInput(name, label, val) { return IG.field(label, IG.input(name, { type: "number", min: "0", step: "any", inputmode: "decimal", value: val == null ? "" : val })); }

  /* ---------- dialogs */
  function addPostDialog(done) {
    var form = h("form", { class: "stack-sm" },
      h("div", { class: "form-grid" },
        IG.field("Format", IG.select("format", FORMATS, "reel")),
        IG.field("Date", IG.input("date", { type: "date", value: new Date().toISOString().slice(0, 10) })),
        IG.field("First line / hook", IG.input("first_line", { placeholder: "The spoken hook or the cover line, word for word" }), null, "span-all"),
        IG.field("Theme", IG.input("theme", { placeholder: "e.g. pricing" }), "Use the same words every time."),
        IG.field("Hook formula #", IG.input("hook_formula", { type: "number", min: "1", max: "26" }), "From ig-reel's 26 formulas"),
        IG.field("Length (s)", IG.input("length", { type: "number", min: "1" })),
        IG.field("Link", IG.input("permalink", { placeholder: "https://www.instagram.com/reel/…" }), null, "span-2"),
        IG.field("Notes", IG.input("notes"), null, "span-all")),
      h("label", { class: "check" }, h("input", { type: "checkbox", name: "trial" }), "Trial reel (shown to non-followers first)"));
    IG.dialog("Log a post", form, [{ label: "Cancel" }, { label: "Add post", primary: true, onClick: function (close) {
      return IG.post("/api/ledger/add", IG.formData(form)).then(function (r) { close(); IG.toast("Logged as " + r.id); done(); });
    } }]);
  }

  function numbersDialog(post, done) {
    var form = h("form", { class: "stack-sm" },
      h("p", { class: "small muted", text: "Open the post in Instagram → View insights. Leave anything you can't see empty (empty means unknown, not zero)." }),
      h("div", { class: "form-grid" }, METRIC_FIELDS.map(function (f) { return numInput(f[0], f[1]); }),
        IG.field("Hours since posting", IG.input("hours", { type: "number", min: "0", step: "any", placeholder: "auto" })),
        IG.field("Posted at", IG.input("posted_at", { placeholder: "YYYY-MM-DD HH:MM" }), "Once, so checks line up"),
        IG.field("Notes", IG.input("notes"), null, "span-all")));
    IG.dialog("Numbers for " + post.id + (post.first_line ? " · " + post.first_line.slice(0, 40) : ""), form, [{ label: "Cancel" }, { label: "Save check", primary: true, onClick: function (close) {
      var b = IG.formData(form); b.id = post.id;
      return IG.post("/api/perf/check", b).then(function () { close(); IG.toast("Saved"); done(); statusDialog(post.id); });
    } }]);
  }

  function editDialog(post, done) {
    var form = h("form", { class: "stack-sm" }, h("div", { class: "form-grid" },
      IG.field("Format", IG.select("format", FORMATS, post.format)),
      IG.field("Date", IG.input("date", { type: "date", value: post.date })),
      IG.field("First line", IG.input("first_line", { value: post.first_line }), null, "span-all"),
      IG.field("Theme", IG.input("theme", { value: post.theme })),
      IG.field("Hook formula #", IG.input("hook_formula", { value: post.hook_formula })),
      IG.field("Length (s)", IG.input("length", { value: post.length_s })),
      IG.field("Link", IG.input("permalink", { value: post.permalink }), null, "span-2"),
      METRIC_FIELDS.map(function (f) { return numInput(f[0], f[1], post[f[0] === "avg_watch" ? "avg_watch_s" : f[0]]); }),
      IG.field("Notes", IG.input("notes", { value: post.notes }), null, "span-all")));
    IG.dialog("Edit " + post.id, form, [{ label: "Cancel" }, { label: "Save", primary: true, onClick: function (close) {
      var b = IG.formData(form), changed = { id: post.id };
      Object.keys(b).forEach(function (k) {
        var orig = post[k === "length" ? "length_s" : k === "avg_watch" ? "avg_watch_s" : k];
        if (String(b[k]) !== String(orig == null ? "" : orig) && b[k] !== "") changed[k] = b[k];
      });
      if (Object.keys(changed).length === 1) { close(); return; }
      return IG.post("/api/ledger/update", changed).then(function () { close(); IG.toast("Updated " + post.id); done(); });
    } }]);
  }

  function statusDialog(id) {
    var box = h("div", { class: "stack-sm" }, IG.loading());
    IG.dialog("How " + id + " is doing", box);
    IG.get("/api/perf/status?id=" + encodeURIComponent(id)).then(function (s) {
      IG.clear(box);
      var c = s.compare || {};
      box.appendChild(h("div", { class: "stats" },
        IG.stat("Views", IG.compact((s.metrics || {}).views), s.age_hours != null ? Math.round(s.age_hours) + "h old" : null),
        IG.stat("vs your usual", c.multiple != null ? c.multiple.toFixed(2) + "×" : "–", c.basis || null, c.multiple >= 1 ? "up" : "down"),
        IG.stat("Sends / reach", IG.pct((s.rates || {}).sends_per_reach), null)));
      if (s.velocity && s.velocity.line) box.appendChild(h("p", { text: s.velocity.line }));
      (s.diagnosis || []).forEach(function (d) { box.appendChild(IG.note("warn", h("div", null, h("b", { text: d.title || d.rule }), h("div", { class: "small", text: d.detail || "" })))); });
      if (!(s.diagnosis || []).length && (s.metrics || {}).views != null) box.appendChild(IG.note("ok", "No problem stands out yet."));
      var list = function (t, arr) { return arr && arr.length ? h("div", null, h("h3", { text: t }), h("ul", { class: "small", style: { margin: "4px 0 0", paddingLeft: "18px" } }, arr.map(function (x) { return h("li", { text: x }); }))) : null; };
      box.appendChild(list("Do now", s.improve_now));
      box.appendChild(list("Next reel", s.improve_next));
      box.appendChild(list("Missing numbers", s.missing));
      if (c.note) box.appendChild(h("p", { class: "small muted", text: c.note }));
      if (s.noise) box.appendChild(h("p", { class: "small muted", text: s.noise }));
    }).catch(function (e) { IG.clear(box).appendChild(IG.errorBox(e)); });
  }

  /* ---------- sections */
  function ledgerSection(box, reload, focusDue) {
    box.appendChild(IG.loading());
    return Promise.all([IG.get("/api/ledger"), IG.get("/api/perf/due"), IG.get("/api/audit").catch(function () { return null; })]).then(function (res) {
      IG.clear(box);
      var posts = res[0].posts, due = res[1].due, audit = res[2];
      IG.setBadge("posts", due.length);
      var dueIds = {}; due.forEach(function (d) { dueIds[d.post_id] = d; });
      var outl = {}; ((audit && audit.posts) || []).forEach(function (p) { outl[p.id] = p.outlier; });
      if (due.length) {
        var dueCard = h("section", { class: "card", style: { borderColor: "var(--warn)" } },
          h("div", { class: "card-h" }, h("div", null, h("h2", { text: due.length + " check" + (due.length > 1 ? "s" : "") + " due" }), h("div", { class: "sub", text: "Numbers at 1h, 24h, 72h and 7 days show the curve, not just the total." })),
            IG.claudeReady() ? IG.btn("Fetch numbers with kweo", { icon: "eye", onClick: function () { IG.ask("/ig-perf check the due posts using the ig-kweo-reader insights job", { send: true }); } }) : null),
          h("div", { class: "stack-sm" }, due.map(function (d) {
            var post = posts.filter(function (p) { return p.id === d.post_id; })[0] || { id: d.post_id, first_line: d.first_line };
            return h("div", { class: "row between" }, h("div", { class: "grow" }, h("b", { text: d.post_id + " " }), h("span", { class: "badge warn", text: d.checkpoint + (d.late ? " · late" : "") }), " ", h("span", { class: "muted", text: d.first_line || "" })),
              IG.btn("Enter numbers", { cls: "sm", onClick: function () { numbersDialog(post, reload); } }));
          })),
          h("p", { class: "small muted", style: { marginTop: "10px" }, text: "Reads only. Nothing is liked, followed or posted." }));
        box.appendChild(dueCard);
        if (focusDue) setTimeout(function () { dueCard.scrollIntoView({ behavior: "smooth", block: "start" }); }, 50);
      }
      if (!posts.length) {
        box.appendChild(h("div", { class: "card empty" }, h("h3", { text: "No posts logged yet" }), h("p", { text: "Log a post when it goes up, import a Meta Business Suite export, or import the posts from your account scan." })));
        return;
      }
      var rows = posts.slice().reverse();
      box.appendChild(h("div", { class: "table-wrap" }, h("table", { class: "t" },
        h("thead", null, h("tr", null, ["ID", "Date", "Format", "First line"].map(function (t) { return h("th", { text: t }); }),
          ["Views", "Reach", "Shares", "Saves", "Follows", "× median"].map(function (t) { return h("th", { class: "n", text: t }); }), h("th", { class: "actions", text: "" }))),
        h("tbody", null, rows.map(function (p) {
          var o = outl[p.id];
          return h("tr", { class: dueIds[p.id] ? "hl" : "" },
            h("td", { class: "mono", text: p.id }), h("td", { class: "num nw", text: IG.date(p.date) }),
            h("td", { class: "nw" }, p.format, p.trial ? h("span", { class: "badge info", style: { marginLeft: "4px" }, text: "trial" }) : null, p.variant ? h("span", { class: "badge", style: { marginLeft: "4px" }, text: p.test_id + p.variant }) : null),
            h("td", { class: "first" }, h("div", { class: "ellipsis", title: p.first_line, text: p.first_line || "–" })),
            h("td", { class: "n", text: IG.compact(p.views) }), h("td", { class: "n", text: IG.compact(p.reach) }), h("td", { class: "n", text: IG.compact(p.shares) }),
            h("td", { class: "n", text: IG.compact(p.saves) }), h("td", { class: "n", text: IG.compact(p.follows) }),
            h("td", { class: "n" }, o != null ? h("span", { class: "badge " + (o >= 1.5 ? "ok" : o < 0.7 ? "bad" : ""), text: o.toFixed(2) + "×" }) : "–"),
            h("td", { class: "actions" },
              IG.btn("Numbers", { cls: "sm", onClick: function () { numbersDialog(p, reload); } }),
              IG.btn("", { cls: "sm ghost", icon: "growth", aria: "Status of " + p.id, title: "Status", onClick: function () { statusDialog(p.id); } }),
              IG.btn("", { cls: "sm ghost", icon: "create", aria: "Edit " + p.id, title: "Edit", onClick: function () { editDialog(p, reload); } })));
        })))));
    });
  }

  function groupTable(title, rows) {
    if (!rows || !rows.length) return null;
    return h("div", { class: "stack-sm" }, h("h3", { text: title }), h("div", { class: "table-wrap" }, h("table", { class: "t" },
      h("thead", null, h("tr", null, h("th", { text: "Group" }), h("th", { class: "n", text: "n" }), h("th", { class: "n", text: "× median" }), h("th", { class: "n", text: "Sends / reach" }))),
      h("tbody", null, rows.map(function (g) {
        return h("tr", null, h("td", null, g.group, g.thin ? h("span", { class: "badge", style: { marginLeft: "6px" }, text: "thin" }) : null), h("td", { class: "n", text: g.n }),
          h("td", { class: "n", text: g.mean_outlier != null ? g.mean_outlier.toFixed(2) + "×" : "–" }), h("td", { class: "n", text: IG.pct(g.mean_sends_per_reach) }));
      })))));
  }

  function auditSection(box) {
    box.appendChild(IG.loading());
    return IG.get("/api/audit").then(function (a) {
      IG.clear(box);
      var conf = { too_few: ["Too few posts to trust patterns yet", "warn"], early: ["Early signal", "info"], visible: ["Patterns are visible", "ok"] }[a.confidence] || [a.confidence, ""];
      box.appendChild(h("div", { class: "stats" },
        IG.stat("Posts measured", IG.n(a.n), a.n_without_views ? a.n_without_views + " without views" : null),
        IG.stat("Median views", IG.compact(a.median_views)),
        IG.stat("Confidence", conf[0].split(" ").slice(0, 2).join(" "), conf[0])));
      if (a.profile && a.profile.flag) box.appendChild(IG.note("warn", "Your reels reach non-followers but few follow. That's a profile problem, not a hook problem.", h("div", { style: { marginTop: "6px" } }, IG.btn("Fix my profile", { cls: "sm", onClick: function () { IG.ask("/ig-profile Score my profile and rewrite what loses points."); } }))));
      var list = function (t, arr) {
        return arr && arr.length ? IG.card(t, null, h("div", { class: "stack-sm" }, arr.map(function (p) {
          return h("div", { class: "row between", style: { flexWrap: "nowrap" } }, h("div", { class: "grow ellipsis" }, h("b", { class: "mono", text: p.id + " " }), p.first_line || ""), h("span", { class: "badge " + (p.outlier >= 1 ? "ok" : "bad"), text: (p.outlier || 0).toFixed(2) + "×" }));
        }))) : null;
      };
      box.appendChild(h("div", { class: "grid-2" }, list("Top 5", a.top), list("Bottom 5", a.bottom)));
      var g = a.groups || {};
      box.appendChild(h("div", { class: "card stack" }, groupTable("By hook formula", g.hook_formula), groupTable("By format", g.format), groupTable("By length", g.length), groupTable("By theme", g.theme)));
      box.appendChild(h("div", { class: "row" }, IG.btn("Ask Claude what to stop and do more of", { icon: "assistant", onClick: function () { IG.ask("/ig-audit Audit my posts from the ledger (run audit.py) and tell me what to stop and what to do more of."); } })));
    });
  }

  function importSection(box, reload) {
    var file = h("input", { type: "file", accept: ".csv,text/csv", id: "meta-csv" });
    var out = h("div", { class: "stack-sm" });
    box.appendChild(IG.card("Import a Meta Business Suite export", "Meta Business Suite → Insights → Content → Export. Pick a date range, download the CSV.",
      h("div", { class: "stack-sm" }, IG.field("CSV file", file),
        h("div", null, IG.btn("Preview import", { cls: "primary", icon: "upload", onClick: function () {
          var f = file.files && file.files[0];
          if (!f) { IG.toast("Pick the CSV first.", "bad"); return; }
          return IG.upload(f, "csv").then(function (up) {
            return IG.post("/api/ledger/import", { path: up.path, dry_run: true }).then(function (r) {
              IG.clear(out).appendChild(h("div", { class: "log", style: { maxHeight: "260px" }, text: r.output || "Nothing to import." }));
              out.appendChild(h("div", { class: "row" }, IG.btn("Import for real", { cls: "primary", onClick: function () {
                return IG.post("/api/ledger/import", { path: up.path, dry_run: false }).then(function (r2) { IG.clear(out).appendChild(IG.note("ok", h("div", { class: "pre", text: r2.output || "Imported." }))); reload(); });
              } }), h("span", { class: "small muted", text: "Imported rows have no hook formula or theme. Fill those in with Edit." })));
            });
          });
        } })), out)));
  }

  function testsSection(box) {
    box.appendChild(IG.loading());
    return IG.get("/api/abtest").then(function (r) {
      IG.clear(box);
      var newForm = h("form", { class: "stack-sm" }, h("div", { class: "form-grid" },
        IG.field("Hook A", IG.input("a", { required: true }), null, "span-all"), IG.field("Hook B", IG.input("b", { required: true }), null, "span-all"),
        IG.field("Formula A #", IG.input("formula_a")), IG.field("Formula B #", IG.input("formula_b")),
        IG.field("Theme", IG.input("theme")), IG.field("Length (s)", IG.input("length", { type: "number" }))));
      box.appendChild(h("div", { class: "row between" }, h("p", { class: "muted small", text: "Post the same reel twice as Trial Reels with different hooks, then compare the 24h numbers." }),
        IG.btn("New test", { cls: "primary", icon: "plus", onClick: function () {
          IG.dialog("New A/B test", newForm, [{ label: "Cancel" }, { label: "Start test", primary: true, onClick: function (close) {
            return IG.post("/api/abtest/new", IG.formData(newForm)).then(function (t) { close(); IG.toast("Started " + t.test_id + " (posts " + t.rows.A + " and " + t.rows.B + ")"); IG.render("posts"); });
          } }]);
        } })));
      if (!r.tests.length) { box.appendChild(h("div", { class: "card empty" }, h("h3", { text: "No tests yet" }), h("p", { text: "Two close hooks? Test them instead of guessing." }))); return; }
      r.tests.forEach(function (t) {
        var rep = h("div");
        box.appendChild(h("section", { class: "card stack-sm" },
          h("div", { class: "row between" }, h("h2", { text: t.test_id }), h("span", { class: "badge " + (t.winner ? "ok" : ""), text: t.winner ? "Winner: " + t.winner : t.status })),
          ["A", "B"].map(function (v) { return h("div", { class: "row", style: { flexWrap: "nowrap" } }, h("span", { class: "badge accent", text: v }), h("span", { class: "grow", text: (t.hooks || {})[v] || "" }),
            IG.btn("24h numbers", { cls: "sm", onClick: function () {
              var f = h("form", { class: "form-grid" }, [["views", "Views"], ["shares", "Shares"], ["likes", "Likes"], ["comments", "Comments"], ["saves", "Saves"], ["follows", "Follows"], ["skip_rate", "Skip rate %"], ["avg_watch", "Avg watch (s)"]].map(function (x) { return numInput(x[0], x[1]); }));
              IG.dialog(t.test_id + " · variant " + v, f, [{ label: "Cancel" }, { label: "Save", primary: true, onClick: function (close) {
                var b = IG.formData(f); b.test_id = t.test_id; b.variant = v;
                return IG.post("/api/abtest/record", b).then(function () { close(); IG.toast("Saved"); IG.render("posts"); });
              } }]);
            } })); }),
          h("div", null, IG.btn("Report", { cls: "sm ghost", onClick: function () {
            return IG.get("/api/abtest/report?id=" + encodeURIComponent(t.test_id)).then(function (x) {
              IG.clear(rep);
              if (x.metrics && x.metrics.length) rep.appendChild(h("div", { class: "table-wrap" }, h("table", { class: "t" }, h("thead", null, h("tr", null, h("th", { text: "Metric" }), h("th", { class: "n", text: "A" }), h("th", { class: "n", text: "B" }))),
                h("tbody", null, x.metrics.map(function (mm) { return h("tr", null, h("td", { text: mm.name }), h("td", { class: "n", text: IG.n(mm.a, 3) }), h("td", { class: "n", text: IG.n(mm.b, 3) })); })))));
              rep.appendChild(h("p", { class: "small", style: { marginTop: "8px" }, text: (x.verdict || "No call yet") + (x.reasons && x.reasons.length ? ". " + x.reasons.join(". ") : "") }));
            });
          } })), rep));
      });
    });
  }

  IG.screen("posts", {
    title: "Posts", icon: "posts",
    render: function (view, params) {
      var tab = params.tab || sessionStorage.getItem("igposts") || "ledger";
      var body = h("div", { class: "stack" });
      var reload = function () { show("ledger"); };
      var show = function (k) {
        tab = k; try { sessionStorage.setItem("igposts", k); } catch (e) { /* ignore */ }
        IG.clear(body);
        var p = k === "ledger" ? ledgerSection(body, reload, params.focusDue) : k === "audit" ? auditSection(body) : k === "tests" ? testsSection(body) : importSection(body, reload);
        if (p && p.catch) p.catch(function (e) { IG.clear(body).appendChild(IG.errorBox(e, function () { show(k); })); });
      };
      if (params.focusDue) tab = "ledger";
      view.appendChild(h("div", { class: "stack" },
        h("div", { class: "row between" }, IG.seg([["ledger", "All posts"], ["audit", "Audit"], ["tests", "A/B tests"], ["import", "Import CSV"]], tab, show, "Section"),
          IG.btn("Log a post", { cls: "primary", icon: "plus", onClick: function () { addPostDialog(reload); } })),
        body));
      show(tab);
    }
  });
})();
