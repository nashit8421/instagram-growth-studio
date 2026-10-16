/* Post: one planned post as a kit. Say this -> Film it -> Edit it -> Post it.
   Everything here was decided by Claude; the user films, drops the footage, copies, posts. */
(function () {
  "use strict";
  var h = IG.h;

  var DIRECT_PHASES = [
    { label: "Watching your footage", match: /Watching the footage/i },
    { label: "Cut editor picks the shots and the hook", match: /Cut editor/i },
    { label: "Captions, look and sound", match: /Caption designer|Look designer|Sound designer|fonts/i },
    { label: "Storyboard and virality checklist", match: /Merging|storyboard|checklist/i },
    { label: "Critic watches it like a scroller", match: /Critic/i },
    { label: "Rendering your Reel", match: /Rendering the Reel/i }
  ];

  function copyBtn(label, text) {
    return IG.btn(label || "Copy", { cls: "sm", icon: "copy", onClick: function () { IG.copy(text); } });
  }

  function section(n, title, sub, body, extra) {
    return h("section", { class: "kit", id: "s" + n },
      h("div", { class: "kit-h" }, h("span", { class: "kit-n", text: String(n) }),
        h("div", { class: "grow" }, h("h2", { text: title }), sub ? h("p", { class: "muted small", text: sub }) : null), extra || null),
      body);
  }

  /* ---------- the viral reel this post copies */
  function modelCard(p) {
    var m = p.model;
    if (!m || !m.ref) return null;
    var facts = [m.views != null ? IG.compact(m.views) + " views" : null,
      m.multiple ? IG.n(m.multiple, 1) + "× their usual" : null,
      m.length_s ? m.length_s + "s" : null].filter(Boolean).join(" · ");
    return h("section", { class: "model" },
      h("div", { class: "model-h" },
        h("div", { class: "grow" },
          h("p", { class: "eyebrow", text: "Copies a reel that went viral" }),
          h("div", { class: "model-who" }, h("b", { text: m.account || m.ref }), facts ? h("span", { class: "muted", text: facts }) : null)),
        m.url ? h("a", { class: "btn sm", href: m.url, target: "_blank", rel: "noopener noreferrer" }, IG.icon("play"), h("span", { text: "Watch it first" })) : null),
      m.hook ? h("p", { class: "model-hook" }, h("span", { class: "lbl", text: "Their hook" }), h("span", { text: IG.quote(m.hook) })) : null,
      m.structure ? h("p", { class: "small muted", text: "How it goes: " + m.structure }) : null,
      (m.copy || []).length ? h("div", null, h("h3", { class: "small", text: "What you copy" }),
        h("ul", { class: "plain small" }, m.copy.map(function (c) { return h("li", { text: c }); }))) : null,
      m.change ? h("p", { class: "small" }, h("b", { text: "What's yours: " }), m.change) : null);
  }

  /* ---------- teleprompter */
  function teleprompter(lines) {
    var speed = 1.2, playing = true, y = 0, last = null, raf = null;
    var txt = h("div", { class: "tp-text" }, lines.map(function (l) { return h("p", { text: l }); }));
    var spd = h("span", { class: "num", text: "1.2×" });
    var toggle = h("button", { class: "btn sm", type: "button", text: "Pause" });
    var wrap = h("div", { class: "tp", role: "dialog", "aria-label": "Teleprompter" },
      h("div", { class: "tp-bar" },
        toggle,
        h("button", { class: "btn sm", type: "button", text: "Slower", onclick: function () { speed = Math.max(0.4, speed - 0.2); spd.textContent = speed.toFixed(1) + "×"; } }),
        spd,
        h("button", { class: "btn sm", type: "button", text: "Faster", onclick: function () { speed = Math.min(4, speed + 0.2); spd.textContent = speed.toFixed(1) + "×"; } }),
        h("button", { class: "btn sm", type: "button", text: "Restart", onclick: function () { y = 0; } }),
        h("span", { class: "grow" }),
        h("button", { class: "btn sm", type: "button", text: "Close (Esc)", onclick: close })),
      h("div", { class: "tp-view" }, txt), h("div", { class: "tp-line" }));
    function frame(t) {
      if (last !== null && playing) y += (t - last) * 0.03 * speed;
      last = t;
      txt.style.transform = "translateY(" + (-y) + "px)";
      raf = requestAnimationFrame(frame);
    }
    function key(e) {
      if (e.key === "Escape") close();
      if (e.key === " ") { e.preventDefault(); toggle.click(); }
    }
    function close() { cancelAnimationFrame(raf); document.removeEventListener("keydown", key); wrap.remove(); }
    toggle.addEventListener("click", function () { playing = !playing; toggle.textContent = playing ? "Pause" : "Play"; });
    document.addEventListener("keydown", key);
    document.body.appendChild(wrap);
    setTimeout(function () { raf = requestAnimationFrame(frame); }, 900);
  }

  /* ---------- 1. say this */
  function sayThis(p) {
    var hook = p.hook || {};
    var beats = p.script || [];
    var lines = beats.map(function (b) { return b.say; }).filter(Boolean);
    var hookBox = h("div", { class: "hook" },
      h("p", { class: "eyebrow", text: "The first two seconds" }),
      hook.spoken ? h("p", { class: "hook-say", text: IG.quote(hook.spoken) }) : null,
      hook.on_screen ? h("p", { class: "hook-text" }, h("span", { class: "lbl", text: "On screen" }), h("b", { text: hook.on_screen })) : null,
      h("div", { class: "row small muted" },
        hook.formula ? h("span", { text: "Formula #" + hook.formula + (hook.formula_name ? " · " + hook.formula_name : "") }) : null,
        hook.score != null ? h("span", { class: "badge " + (hook.score >= 75 ? "ok" : hook.score >= 55 ? "warn" : "bad"), text: "Hook score " + Math.round(hook.score) }) : null));
    var beatList = beats.length ? h("ol", { class: "beats" }, beats.map(function (b, i) {
      return h("li", null,
        h("span", { class: "bt", text: b.t || String(i + 1) }),
        h("div", { class: "grow" },
          b.say ? h("div", { class: "say", text: b.say }) : null,
          b.on_screen ? h("div", { class: "ost" }, h("span", { class: "lbl", text: "Text" }), b.on_screen) : null),
        b.shot ? h("span", { class: "shotref", text: "shot " + b.shot }) : null);
    })) : null;
    var slides = p.format === "carousel" ? slidesBlock(p) : null;
    return section(1, p.format === "carousel" ? "The slides" : "Say this",
      p.format === "carousel" ? "Copy is written. Make the images in one click." : (p.length_s ? "About " + p.length_s + " seconds. Start talking on the first frame." : null),
      h("div", { class: "stack" }, hookBox, beatList, slides,
        lines.length ? h("div", { class: "row" },
          IG.btn("Teleprompter", { cls: "primary", icon: "play", onClick: function () { teleprompter(lines); } }),
          copyBtn("Copy script", beats.map(function (b) { return (b.t ? "[" + b.t + "] " : "") + (b.say || "") + (b.on_screen ? "  (text: " + b.on_screen + ")" : ""); }).join("\n"))) : null));
  }

  function slidesBlock(p) {
    var out = h("div", { class: "stack-sm" });
    var list = h("ol", { class: "slide-list" }, (p.slides || []).map(function (s, i) {
      return h("li", null, h("span", { class: "si", text: String(i + 1) }),
        h("div", null, s.title ? h("b", { text: s.title }) : null, s.body ? h("div", { class: "small", text: s.body }) : null,
          s.list ? h("ul", { class: "small" }, s.list.map(function (x) { return h("li", { text: x }); })) : null));
    }));
    var make = IG.btn("Make the images", { cls: "primary", icon: "film", onClick: function () {
      var spec = { kind: "carousel", handle: IG.accounts && IG.accounts.active ? "@" + IG.accounts.active : "", alt: (p.cover && p.cover.text) || p.title,
        slides: (p.slides || []).map(function (s, i) { return Object.assign({ role: i === 0 ? "cover" : s.role }, s); }) };
      return IG.runJob(IG.post("/api/render", { spec: spec }), out, { label: "Rendering the slides…" }).then(function (r) {
        IG.clear(out);
        out.appendChild(h("div", { class: "row between" }, h("b", { text: r.files.length + " images, in upload order" }),
          h("a", { class: "btn primary sm", href: r.zip }, IG.icon("download"), h("span", { text: "Download all" }))));
        out.appendChild(h("div", { class: "gallery" }, r.files.map(function (f) {
          return h("figure", null, h("a", { href: f.url, target: "_blank", rel: "noopener" }, h("img", { src: f.url, alt: f.name, loading: "lazy" })),
            h("figcaption", null, h("span", { text: f.name }), h("a", { href: f.download, text: "Save" })));
        })));
        if (r.alt_text) out.appendChild(h("div", { class: "row" }, copyBtn("Copy alt text", r.alt_text)));
      });
    } });
    return h("div", { class: "stack-sm" }, list, h("div", null, make), out);
  }

  /* ---------- 2. film it */
  function filmIt(p) {
    var d = p.direction || {};
    var setup = d.setup || {};
    var tiles = [["Location", setup.location], ["Light", setup.light], ["Framing", setup.framing], ["Wardrobe", setup.wardrobe], ["Props", setup.props]]
      .filter(function (x) { return x[1]; });
    return section(2, "Film it", "The director's notes. Phone vertical, 4K or 1080p, at eye level.",
      h("div", { class: "stack" },
        d.concept ? h("p", { class: "concept" }, h("b", { text: "The idea: " }), d.concept, d.mood ? h("span", { class: "badge", style: { marginLeft: "8px" }, text: d.mood }) : null) : null,
        tiles.length ? h("div", { class: "tiles" }, tiles.map(function (t) { return h("div", { class: "tile" }, h("span", { class: "k", text: t[0] }), h("span", { text: t[1] })); })) : null,
        (d.shots || []).length ? h("ol", { class: "shots" }, d.shots.map(function (s, i) {
          return h("li", null,
            h("div", { class: "sn" }, h("b", { text: String(s.n || i + 1) }), s.seconds ? h("span", { class: "tiny muted", text: s.seconds + "s" }) : null),
            h("div", { class: "grow" },
              s.frame ? h("div", { class: "frame", text: s.frame }) : null,
              h("div", { class: "action", text: s.action }),
              s.line ? h("div", { class: "line", text: IG.quote(s.line) }) : null));
        })) : null,
        h("div", { class: "grid-2" },
          (d.delivery || []).length ? h("div", { class: "notes" }, h("h3", { text: "How to say it" }), h("ul", null, d.delivery.map(function (x) { return h("li", { text: x }); }))) : null,
          (d.avoid || []).length || d.takes ? h("div", { class: "notes" }, h("h3", { text: "Takes and traps" }),
            h("ul", null, d.takes ? h("li", { text: d.takes }) : null, (d.avoid || []).map(function (x) { return h("li", { text: x }); }))) : null)));
  }

  /* ---------- 3. edit it */
  function editIt(p, weekOf, reload) {
    var prog = p.progress || {};
    var edit = prog.edit;
    var box = h("div", { class: "stack" });

    function startDirector(path) {
      return IG.post("/api/video/direct", { path: path, post_id: p.id, week_of: weekOf }).then(function (res) {
        directing(res.job);
      });
    }
    function directing(job) {
      IG.clear(box);
      var list = h("ol", { class: "phases" }, DIRECT_PHASES.map(function (ph) { return h("li", null, h("span", { class: "b" }), h("span", { text: ph.label })); }));
      var now = h("div", { class: "now small muted", text: "Starting the director…" });
      box.appendChild(h("div", { class: "prep inset" },
        h("div", { class: "prep-h" }, h("span", { class: "spin" }), h("div", { class: "grow" }, h("h3", { text: "The director is editing your Reel" }),
          h("p", { class: "small muted", text: "5 to 10 minutes. It follows the plan above, then renders. You can leave this page." })),
          IG.btn("Stop", { cls: "ghost sm", onClick: function () { return IG.post("/api/jobs/" + job + "/cancel"); } })),
        list, now));
      IG.followRun(job, DIRECT_PHASES, function (st) {
        list.querySelectorAll("li").forEach(function (li, i) { li.className = i < st.phase ? "done" : i === st.phase ? "cur" : ""; });
        now.textContent = st.now ? "Now: " + st.now : "";
      }, function (ev) {
        if (ev.status === "done") IG.toast("Your Reel is ready", "ok");
        if (IG.current === "post" && IG.params0 && IG.params0.id === p.id && IG.params0.w === weekOf) reload();
      });
    }

    function dropzone() {
      var file = h("input", { type: "file", accept: "video/*,.mov,.mp4,.m4v", class: "sr", id: "foot-" + p.id });
      var status = h("div");
      var zone = h("label", { class: "drop", for: file.id },
        IG.icon("upload"), h("b", { text: "Drop your footage here" }),
        h("span", { class: "small muted", text: "One file: the whole take, or your best take. The director cuts, captions, grades and renders it. No settings." }));
      function take(f) {
        if (!f) return;
        if (!/^video\//.test(f.type) && !/\.(mov|mp4|m4v|webm|mkv)$/i.test(f.name)) { IG.toast("That isn't a video file.", "bad"); return; }
        var bar = h("div", { class: "progress" }, h("i"));
        IG.clear(status).appendChild(h("div", { class: "stack-sm" }, h("span", { class: "small muted", text: "Uploading " + f.name + " (" + IG.n(f.size / 1048576, 1) + " MB)…" }), bar));
        IG.upload(f, "video", function (x) { bar.firstChild.style.width = Math.round(x * 100) + "%"; })
          .then(function (up) { return startDirector(up.path); })
          .catch(function (e) { IG.clear(status).appendChild(IG.note("bad", e.message)); });
      }
      file.addEventListener("change", function () { take(file.files && file.files[0]); });
      zone.addEventListener("dragover", function (e) { e.preventDefault(); zone.classList.add("over"); });
      zone.addEventListener("dragleave", function () { zone.classList.remove("over"); });
      zone.addEventListener("drop", function (e) { e.preventDefault(); zone.classList.remove("over"); take(e.dataTransfer.files[0]); });
      var noFf = IG.status && !IG.status.ffmpeg;
      return h("div", { class: "stack-sm" }, noFf ? IG.note("warn", "Editing needs ffmpeg. Mac: brew install ffmpeg. Windows: winget install ffmpeg. Then restart IG Studio.") : null,
        file, zone, status);
    }

    function finished() {
      var change = IG.textarea("change", { rows: 2, maxlength: "3000", placeholder: "e.g. bigger captions, open on the second line, calmer colours, under 20 seconds" });
      var work = h("div");
      var storyLink = h("span");
      IG.get("/api/video/direct?" + IG.q({ dir: edit.dir })).then(function (d) {
        if (d.html) storyLink.appendChild(h("a", { class: "btn ghost sm", href: d.html, target: "_blank", rel: "noopener", text: "See the storyboard" }));
        if (d.score != null) storyLink.appendChild(h("span", { class: "badge " + (d.score >= 85 ? "ok" : "warn"), text: "Checklist " + d.score + "/100" }));
      }).catch(function () { /* optional */ });
      return h("div", { class: "video-wrap" },
        h("video", { src: edit.video.url, controls: true, playsinline: true, preload: "metadata" }),
        h("div", { class: "stack-sm grow" },
          h("div", { class: "row" },
            h("a", { class: "btn primary", href: edit.video.download }, IG.icon("download"), h("span", { text: "Download the Reel" })),
            edit.cover ? h("a", { class: "btn", href: edit.cover.download }, IG.icon("download"), h("span", { text: "Cover" })) : null),
          h("div", { class: "row" }, storyLink),
          edit.cover ? h("img", { class: "cover-thumb", src: edit.cover.url, alt: "Cover frame" }) : null,
          IG.field("Want something different?", change),
          h("div", { class: "row" }, IG.btn("Change it", { onClick: function () {
            var text = change.value.trim();
            if (!text) { change.focus(); return; }
            return IG.post("/api/video/direct/revise", { dir: edit.dir, change: text }).then(function (res) {
              return IG.runJob(Promise.resolve(res), work, { label: "The director is making the change…" });
            }).then(function () {
              return IG.runJob(IG.post("/api/video/direct/render", { dir: edit.dir }), work, { label: "Rendering the new cut…" });
            }).then(function () { IG.toast("New cut ready", "ok"); reload(); });
          } }), IG.btn("Start over with new footage", { cls: "ghost", onClick: function () { IG.clear(box).appendChild(dropzone()); } })),
          work));
    }

    if (edit && edit.running) directing(edit.job);
    else if (edit && edit.video) box.appendChild(finished());
    else {
      if (edit && edit.error) {
        box.appendChild(IG.note("bad", h("div", { class: "stack-sm" }, h("span", { text: edit.error }),
          prog.footage ? h("div", null, IG.btn("Try again with the same footage", { cls: "sm", onClick: function () { return startDirector(prog.footage); } })) : null)));
      }
      box.appendChild(dropzone());
    }
    var mark = prog.stage !== "edited" && prog.stage !== "posted" && !(edit && edit.video)
      ? h("p", { class: "small faint" }, "Edited it somewhere else? ", h("button", { class: "link-btn", type: "button", text: "Mark it edited", onclick: function () {
        IG.post("/api/week/post", { week_of: weekOf, id: p.id, stage: "edited" }).then(reload).catch(IG.fail);
      } }), " · or use the ", h("a", { href: "#tools", text: "quick editor" }), ".") : null;
    return section(3, "Edit it", "Claude's director cuts the pauses, opens on the hook, captions inside the safe zone and renders 1080×1920.", h("div", { class: "stack" }, box, mark));
  }

  /* ---------- 4. post it */
  function postIt(p, weekOf, reload) {
    var cap = p.caption || {};
    var full = (cap.text || "") + ((cap.hashtags || []).length ? "\n\n" + cap.hashtags.join(" ") : "");
    var sound = p.sound || {};
    var cover = p.cover || {};
    var posted = p.progress && p.progress.stage === "posted";
    return section(4, "Post it", "Post at " + IG.ampm(p.time) + " on " + IG.longDate(p.date) + ". Do the 20-minute comment round first.",
      h("div", { class: "stack" },
        h("div", { class: "caption-box" },
          h("div", { class: "row between" }, h("h3", { text: "Caption" }), copyBtn("Copy caption", full)),
          h("div", { class: "cap-text", text: cap.text || "" }),
          (cap.hashtags || []).length ? h("div", { class: "tags", text: cap.hashtags.join(" ") }) : null),
        h("div", { class: "grid-2" },
          sound.name ? h("div", { class: "notes" }, h("h3", { text: "Sound" }),
            h("p", null, h("b", { text: sound.name }), sound.artist ? " · " + sound.artist : ""),
            sound.why ? h("p", { class: "small muted", text: sound.why }) : null,
            sound.how ? h("p", { class: "small", text: sound.how }) : null) : null,
          cover.text || cover.frame ? h("div", { class: "notes" }, h("h3", { text: "Cover" }),
            cover.text ? h("p", null, h("b", { text: cover.text })) : null,
            cover.frame ? h("p", { class: "small muted", text: "Frame: " + cover.frame }) : null) : null),
        posted
          ? IG.note("ok", h("div", null, h("b", { text: "Posted." }), " Logged in your results" + (p.progress.ledger_id ? " as " + p.progress.ledger_id : "") + ". Its numbers at 1 hour, 24 hours and 7 days show what to do next. ",
            h("a", { href: "#posts", text: "Add its numbers" })))
          : h("div", { class: "row" }, IG.btn("I posted it", { cls: "primary", icon: "check", onClick: function () {
            return IG.post("/api/week/post", { week_of: weekOf, id: p.id, stage: "posted" }).then(function () { IG.toast("Logged. Nice.", "ok"); reload(); });
          } }), h("span", { class: "small muted", text: "Logs it so Claude can learn what works for you." }))));
  }

  function stepper(p) {
    var idx = IG.stageIndex(p.progress ? p.progress.stage : "script");
    var reel = p.format === "reel";
    // [label, section, the stage index at which this step counts as done]
    var steps = reel ? [["Script", 1, 0], ["Film", 2, 1], ["Edit", 3, 2], ["Post", 4, 3]] : [["Copy", 1, 0], ["Post", 4, 3]];
    var curSet = false;
    return h("ol", { class: "stepper" }, steps.map(function (s, i) {
      var done = idx >= s[2];
      var cur = !done && !curSet;
      if (cur) curSet = true;
      return h("li", { class: done ? "done" : cur ? "cur" : "" },
        h("a", { href: "#", onclick: function (e) { e.preventDefault(); var el = document.getElementById("s" + s[1]); if (el) el.scrollIntoView({ behavior: "smooth", block: "start" }); } },
          h("span", { class: "b" }, done && !cur ? IG.icon("check") : String(i + 1)), s[0]));
    }));
  }

  function redoBtn(p, weekOf, reload, box) {
    return IG.btn("Rewrite this post", { cls: "ghost sm", icon: "refresh", onClick: function () {
      var note = IG.textarea("note", { rows: 3, placeholder: "Optional. e.g. funnier; I don't have an audition story yet; make it a carousel" });
      IG.dialog("Rewrite " + DAYS_LONG(p.day) + "'s post?", h("div", { class: "stack-sm" },
        h("p", { class: "small", text: "Claude writes a new kit for this slot: hook, script, filming notes, caption and sound. The other posts stay as they are." }),
        IG.field("What should change", note)), [
        { label: "Cancel" },
        { label: "Rewrite", primary: true, onClick: function (close) {
          return IG.post("/api/week/redo", { week_of: weekOf, id: p.id, note: note.value }).then(function (res) {
            close();
            IG.runJob(Promise.resolve(res), box, { label: "Claude is rewriting this post…" }).then(function () { IG.toast("Rewritten", "ok"); reload(); })
              .catch(function (e) { if (!e.handled) IG.fail(e); });
          });
        } }]);
    } });
  }
  function DAYS_LONG(d) { return { MON: "Monday", TUE: "Tuesday", WED: "Wednesday", THU: "Thursday", FRI: "Friday", SAT: "Saturday", SUN: "Sunday" }[d] || d; }

  IG.screen("post", {
    title: "Post", hidden: true,
    render: function (view, params, m) {
      var weekOf = params.w, id = params.id;
      IG.params0 = { w: weekOf, id: id };
      var reload = function () { IG.params = { w: weekOf, id: id }; IG.render("post"); };
      view.appendChild(IG.loading());
      return IG.get("/api/week?" + IG.q({ week_of: weekOf })).then(function (data) {
        if (!IG.alive(m)) return;
        IG.clear(view);
        var w = data.week;
        var p = w && (w.posts || []).filter(function (x) { return x.id === id; })[0];
        if (!p || w.week_of !== weekOf) {
          view.appendChild(h("div", { class: "card empty" }, h("h3", { text: "That post isn't in the plan any more" }),
            h("p", null, h("a", { href: "#week", text: "Back to the week" }))));
          return;
        }
        document.title = p.title + " · IG Studio";
        var redoBox = h("div");
        view.appendChild(h("a", { class: "back", href: IG.hashFor("week", weekOf === data.this_monday || weekOf === data.target ? null : { w: weekOf }) }, IG.icon("back"), h("span", { text: "The week" })));
        view.appendChild(h("header", { class: "post-head" },
          h("p", { class: "eyebrow", text: [IG.longDate(p.date), IG.ampm(p.time), IG.fmtLabel(p), p.type, p.trial ? "trial reel" : null].filter(Boolean).join(" · ") }),
          h("h1", { text: p.title }),
          p.why ? h("p", { class: "lede", text: p.why }) : null,
          h("div", { class: "row between" }, stepper(p), redoBtn(p, weekOf, reload, redoBox)),
          redoBox,
          p.trial ? IG.note("info", "Post this one as a Trial Reel (Instagram: Share → Trial). Non-followers see it first; it stays off your grid unless it does well.") : null));
        var model = modelCard(p);
        if (model) view.appendChild(model);
        view.appendChild(sayThis(p));
        if (p.format === "reel") {
          view.appendChild(filmIt(p));
          view.appendChild(editIt(p, weekOf, reload));
        }
        view.appendChild(postIt(p, weekOf, reload));
      });
    }
  });
})();
