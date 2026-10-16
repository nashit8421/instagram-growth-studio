/* Trends & Sound: what's going viral in the niche, the trend board, logged trends, sounds and sound picks. */
(function () {
  "use strict";
  var h = IG.h;
  var PHASE = { rising: "ok", peaking: "warn", fading: "bad", early: "info" };

  function prof() { return (IG.state && IG.state.profile) || {}; }

  function addTrendForm(done) {
    var p = prof();
    var form = h("form", { class: "stack-sm" }, h("div", { class: "form-grid" },
      IG.field("Trend", IG.input("name", { placeholder: "e.g. POV office meme", required: true }), null, "span-2"),
      IG.field("Kind", IG.select("kind", [["topic", "Topic"], ["hashtag", "Hashtag"], ["song", "Song"], ["format", "Format"], ["meme", "Meme"]], "topic")),
      IG.field("Where you saw it", IG.select("source", [["instagram", "Instagram"], ["tiktok", "TikTok"], ["google", "Google Trends"], ["youtube", "YouTube"], ["news", "News"]], "instagram")),
      IG.field("Region", IG.input("region", { value: p.region || "", placeholder: "IN" })),
      IG.field("Trending…", IG.select("scope", [["region", "everywhere in the region"], ["niche", "inside my niche"]], "region")),
      IG.field("Growth", IG.input("growth", { placeholder: "+250%, 3x, Breakout" })),
      IG.field("Niche fit (0-3)", IG.select("niche_match", [["", "Let it guess"], ["0", "0 none"], ["1", "1 loose"], ["2", "2 good"], ["3", "3 perfect"]], "")),
      IG.field("Link", IG.input("url", { placeholder: "https://…" }), null, "span-2"),
      IG.field("Notes", IG.input("notes"), null, "span-all")));
    IG.dialog("Add a trend", form, [{ label: "Cancel" }, { label: "Add trend", primary: true, onClick: function (close) {
      return IG.post("/api/trends/add", IG.formData(form)).then(function (t) {
        close(); IG.toast("Added " + t.id + (t.safety_level && t.safety_level !== "ok" ? " (safety: " + t.safety_level + ")" : "")); done();
      });
    } }]);
  }

  function trendsTab(box) {
    var p = prof();
    var boardBox = h("div", { class: "stack-sm" }, IG.loading());
    var listBox = h("div");
    var reload = function () { IG.render("trends"); };
    box.appendChild(h("section", { class: "card" },
      h("div", { class: "card-h" },
        h("div", null, h("h2", { text: "Trend board" }), h("div", { class: "sub", text: "Trend brings the timing, your niche brings the substance" + (p.region ? " · " + p.region : "") + (p.niche ? " · " + p.niche : "") })),
        h("div", { class: "row" },
          IG.btn("Add trend", { icon: "plus", onClick: function () { addTrendForm(reload); } }),
          IG.btn("Rebuild board", { icon: "refresh", title: "Re-rank and write trends.md", onClick: function () { return IG.post("/api/trends/blend", {}).then(function () { IG.toast("Board rebuilt and saved"); reload(); }); } }),
          IG.claudeReady() ? IG.btn("Refresh with Claude", { cls: "primary", icon: "assistant", onClick: function () { IG.ask("/ig-trends Find what's trending right now in my region and in my niche, log the trends, and rebuild my trend board.", { send: true }); } }) : null)),
      boardBox));
    box.appendChild(listBox);
    IG.post("/api/trends/blend", { no_write: true }).then(function (b) {
      IG.clear(boardBox);
      if (!b.board || !b.board.length) {
        boardBox.appendChild(h("div", { class: "empty" }, h("h3", { text: "No trend ideas yet" }), h("p", { text: "Add trends you've spotted, or let Claude research them." })));
        return;
      }
      boardBox.appendChild(h("div", { class: "table-wrap" }, h("table", { class: "t" },
        h("thead", null, h("tr", null, h("th", { class: "n", text: "Score" }), h("th", { text: "Idea" }), h("th", { text: "Phase" }), h("th", { class: "n", text: "Days left" }), h("th", { text: "Hook formula" }), h("th", { text: "Ship by" }), h("th", { text: "" }))),
        h("tbody", null, b.board.map(function (r) {
          return h("tr", null, h("td", { class: "n" }, h("b", { text: r.score })),
            h("td", null, h("div", null, h("b", { text: r.trend }), " ", h("span", { class: "badge", text: r.kind })), r.angle ? h("div", { class: "small muted", text: "× " + r.angle }) : null,
              r.safety && r.safety !== "ok" ? h("span", { class: "badge bad", text: "safety: " + r.safety }) : null),
            h("td", null, h("span", { class: "badge " + (PHASE[r.phase] || ""), text: r.phase })),
            h("td", { class: "n", text: r.days_left }), h("td", { text: r.formula ? "#" + r.formula_id + " " + r.formula : "–" }), h("td", { class: "num", text: IG.date(r.ship_by) }),
            h("td", { class: "actions" }, IG.btn("Write reel", { cls: "sm", onClick: function () {
              IG.ask("/ig-reel Write a reel that rides the trend \"" + r.trend + "\"" + (r.angle ? " with my angle \"" + r.angle + "\"" : "") + (r.formula ? ", hook formula #" + r.formula_id + " " + r.formula : "") + ". Ship by " + r.ship_by + ".");
            } })));
        })))));
      if (b.excluded && b.excluded.length) boardBox.appendChild(h("p", { class: "small muted", text: b.excluded.length + " trend(s) left out for brand safety." }));
    }).catch(function (e) { IG.clear(boardBox).appendChild(e.status === 400 ? IG.note("info", e.message) : IG.errorBox(e)); });

    IG.get("/api/trends").then(function (r) {
      var live = r.trends.filter(function (t) { return !t.expired; });
      listBox.appendChild(IG.card("Logged trends", live.length + " live, " + (r.trends.length - live.length) + " expired",
        r.trends.length ? h("div", { class: "table-wrap" }, h("table", { class: "t" },
          h("thead", null, h("tr", null, h("th", { text: "ID" }), h("th", { text: "Trend" }), h("th", { text: "Source" }), h("th", { class: "n", text: "Momentum" }), h("th", { text: "Phase" }), h("th", { class: "n", text: "Days left" }))),
          h("tbody", null, r.trends.map(function (t) {
            return h("tr", { style: t.expired ? { opacity: ".55" } : null }, h("td", { class: "mono", text: t.id }), h("td", null, t.name, " ", h("span", { class: "badge", text: t.scope })),
              h("td", { text: t.source + " · " + t.region }), h("td", { class: "n" }, h("div", { class: "row", style: { justifyContent: "flex-end", flexWrap: "nowrap" } }, h("div", { class: "bar", style: { width: "70px" } }, h("i", { style: { width: (t.momentum || 0) + "%" } })), h("span", { class: "num", text: t.momentum }))),
              h("td", null, h("span", { class: "badge " + (PHASE[t.phase] || ""), text: t.expired ? "expired" : t.phase })), h("td", { class: "n", text: t.days_left }));
          })))) : h("p", { class: "muted", text: "Nothing logged yet." }),
        r.trends.length - live.length > 0 ? IG.btn("Prune expired", { cls: "sm", onClick: function () { return IG.post("/api/trends/prune").then(function () { IG.toast("Pruned"); reload(); }); } }) : null));
    }).catch(function (e) { listBox.appendChild(IG.errorBox(e)); });
  }

  function addSoundForm(done) {
    var p = prof();
    var form = h("form", { class: "stack-sm" }, h("div", { class: "form-grid" },
      IG.field("Song or sound", IG.input("name", { required: true }), null, "span-2"), IG.field("Artist", IG.input("artist")),
      IG.field("Seen on", IG.select("source", [["instagram", "Instagram"], ["tiktok", "TikTok"], ["other", "Other"]], "instagram")),
      IG.field("Region", IG.input("region", { value: p.region || "" })),
      IG.field("Reels using it", IG.input("reels_count", { placeholder: "12.4K" }), "From the sound's page"),
      IG.field("Trend", IG.select("trend", [["", "Unknown"], ["rising", "Rising"], ["peaking", "Peaking"], ["fading", "Fading"]], "")),
      IG.field("Mood", IG.select("mood", [["", "Unknown"], ["upbeat", "Upbeat"], ["calm", "Calm"], ["dramatic", "Dramatic"], ["funny", "Funny"], ["emotional", "Emotional"], ["lofi", "Lo-fi"]], "")),
      IG.field("BPM", IG.input("bpm", { type: "number" })),
      IG.field("Business accounts can use it?", IG.select("business_ok", [["unknown", "Not sure"], ["yes", "Yes"], ["no", "No"]], "unknown")),
      IG.field("Link", IG.input("url"), null, "span-all")));
    IG.dialog("Add a sound", form, [{ label: "Cancel" }, { label: "Add sound", primary: true, onClick: function (close) {
      return IG.post("/api/audio/add", IG.formData(form)).then(function () { close(); IG.toast("Sound saved"); done(); });
    } }]);
  }

  function soundsTab(box) {
    var p = prof();
    var reload = function () { IG.render("trends"); };
    var picks = h("div", { class: "stack-sm" });
    var sf = h("form", { class: "stack-sm" }, h("div", { class: "form-grid" },
      IG.field("Reel length (s)", IG.input("reel_length", { type: "number", min: "3", value: "25" })),
      IG.field("Mood", IG.select("mood", [["", "Any"], ["upbeat", "Upbeat"], ["calm", "Calm"], ["dramatic", "Dramatic"], ["funny", "Funny"], ["emotional", "Emotional"], ["lofi", "Lo-fi"]], "")),
      IG.field("Voiceover?", IG.select("voiceover", [["no", "No, music only"], ["yes", "Yes, I talk over it"]], "yes")),
      IG.field("Account", IG.select("account", [["creator", "Creator"], ["business", "Business"]], p.account_type || "creator"))),
      h("div", null, IG.btn("Suggest sounds", { cls: "primary", type: "submit" })), picks);
    sf.addEventListener("submit", function (e) {
      e.preventDefault();
      IG.busy(sf.querySelector("button[type=submit]"), function () {
        return IG.post("/api/audio/suggest", IG.formData(sf)).then(function (r) {
          IG.clear(picks);
          if (!r.picks.length) picks.appendChild(h("p", { class: "muted", text: "No saved sound fits. Add a few you've seen on Instagram's audio pages." }));
          r.picks.forEach(function (x, i) {
            picks.appendChild(h("div", { class: "card flat" + (i === 0 ? "" : " tint"), style: i === 0 ? { borderColor: "var(--accent)" } : null },
              h("div", { class: "row between" }, h("b", { text: x.name }), h("span", { class: "badge " + (i === 0 ? "accent" : ""), text: Math.round(x.score) + " pts" })),
              h("div", { class: "small muted", style: { margin: "4px 0 8px" }, text: (x.why || []).join(" · ") }),
              (x.flags || []).map(function (f) { return h("div", { class: "small", style: { color: "var(--warn)" }, text: "⚠ " + f }); }),
              h("ul", { class: "small", style: { margin: 0, paddingLeft: "18px" } }, (x.how || []).map(function (w) { return h("li", { text: w }); }))));
          });
          if (r.licence) picks.appendChild(h("p", { class: "small muted", text: r.licence }));
          if (r.original_audio) picks.appendChild(h("p", { class: "small muted", text: typeof r.original_audio === "string" ? r.original_audio : (r.original_audio.why || r.original_audio.text || "") }));
        });
      });
    });
    var listBox = h("div", null, IG.loading());
    box.appendChild(h("div", { class: "grid-2", style: { alignItems: "start" } },
      IG.card("Pick a sound for a reel", "Ranks your saved sounds by momentum, freshness, mood and pace.", sf),
      h("section", { class: "card" }, h("div", { class: "card-h" }, h("div", null, h("h2", { text: "Saved sounds" })),
        h("div", { class: "row" }, IG.btn("Add sound", { icon: "plus", onClick: function () { addSoundForm(reload); } }),
          IG.claudeReady() ? IG.btn("Find with Claude", { icon: "assistant", onClick: function () { IG.ask("/ig-audio Find the trending sounds in my region this week and save them."); } }) : null)), listBox)));
    IG.get("/api/audio").then(function (r) {
      IG.clear(listBox);
      if (!r.sounds.length) { listBox.appendChild(h("p", { class: "muted", text: "No sounds saved yet." })); return; }
      listBox.appendChild(h("div", { class: "stack-sm" }, r.sounds.map(function (x) {
        return h("div", { class: "row between", style: { borderTop: "1px solid var(--border)", paddingTop: "8px" } },
          h("div", { class: "grow" }, h("b", { text: x.name }), x.artist ? h("span", { class: "muted", text: " · " + x.artist }) : null,
            h("div", { class: "small muted", text: [x.region, x.reels_count ? IG.compact(x.reels_count) + " reels" : null, x.mood, x.bpm ? x.bpm + " bpm" : null, "seen " + IG.date(x.last_seen)].filter(Boolean).join(" · ") })),
          h("div", { class: "row" }, x.trend ? h("span", { class: "badge " + (PHASE[x.trend] || ""), text: x.trend }) : null,
            x.business_ok === "no" ? h("span", { class: "badge bad", text: "not for business" }) : null));
      })));
    }).catch(function (e) { IG.clear(listBox).appendChild(IG.errorBox(e)); });
  }

  /* What is going viral in the niche (viral.json). Every planned post copies one of these. */
  function viralTab(box) {
    var sub = h("p", { class: "muted small" });
    var list = h("div", null, IG.loading());
    box.appendChild(h("section", { class: "card" },
      h("div", { class: "card-h" }, h("div", null, h("h2", { text: "Going viral in your niche" }), sub),
        IG.claudeReady() ? IG.btn("Find new ones with Claude", { icon: "assistant", onClick: function () {
          IG.ask("/ig-viral Find the reels going viral in my niche right now (Autopilot mode: pick the accounts yourself), rank them and write viral.json.", { send: true });
        } }) : null),
      list));
    IG.get("/api/viral").then(function (r) {
      IG.clear(list);
      if (!r.reels.length) {
        list.appendChild(h("div", { class: "empty" }, h("h3", { text: "No viral research yet" }),
          h("p", { text: "Claude finds these when it prepares your week. Every post copies one of them." })));
        return;
      }
      sub.textContent = r.reels.length + " reels" + (r.accounts ? " from " + r.accounts + " accounts" : "") +
        ", ranked by how far each beat its own account's usual views (likes where Instagram hides the views). Found " + IG.date(r.made) + ".";
      list.appendChild(h("ol", { class: "viral" }, r.reels.map(function (x) {
        return h("li", null,
          h("span", { class: "vx", title: "Times its account's usual " + (x.metric || "views"), text: x.multiple ? IG.n(x.multiple, 1) + "×" : "–" }),
          h("div", { class: "grow" },
            h("div", { class: "vh", text: IG.quote(x.hook) }),
            h("div", { class: "small muted", text: [x.account, x.views != null ? IG.compact(x.views) + " views" : x.likes != null ? IG.compact(x.likes) + " likes" : null, x.formula && x.formula !== "unclassified" ? x.formula : null, x.length_s ? x.length_s + "s" : null].filter(Boolean).join(" · ") }),
            x.structure ? h("div", { class: "small faint", text: x.structure }) : null),
          x.url ? h("a", { class: "btn sm ghost", href: x.url, target: "_blank", rel: "noopener noreferrer", text: "Watch" }) : null);
      })));
    }).catch(function (e) { IG.clear(list).appendChild(IG.errorBox(e)); });
  }

  IG.screen("trends", {
    title: "Viral & trends", short: "Viral", icon: "trends", group: "results",
    render: function (view, params) {
      var tab = (params && params.tab) || sessionStorage.getItem("igtrends") || "viral";
      var tabs = { viral: viralTab, trends: trendsTab, sounds: soundsTab };
      if (!tabs[tab]) tab = "viral";
      var body = h("div", { class: "stack" });
      var show = function (k) { try { sessionStorage.setItem("igtrends", k); } catch (e) { /* ignore */ } IG.clear(body); tabs[k](body); };
      view.appendChild(h("div", { class: "stack" }, IG.seg([["viral", "Going viral"], ["trends", "Trends"], ["sounds", "Sounds"]], tab, show, "Section"), body));
      if (!IG.state) IG.get("/api/state?quick=1").then(function (s) { IG.state = s; }).catch(function () { /* fine */ });
      show(tab);
    }
  });
})();
