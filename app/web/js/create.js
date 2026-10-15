/* Create: instant tools that run the skill scripts directly, no AI. */
(function () {
  "use strict";
  var h = IG.h;
  var TOOLS = [["hooks", "Hook scorer"], ["beats", "Script timer"], ["caption", "Caption checker"], ["human", "Humanizer"], ["carousel", "Carousel maker"], ["video", "Video editor"]];

  function verdictBadge(v) {
    var cls = { STRONG: "ok", OK: "info", WEAK: "warn", FIX: "bad", PASS: "ok", FAIL: "bad", WARN: "warn", HUMAN: "ok", FLAGGED: "bad", BORDERLINE: "warn", MIXED: "warn" }[String(v).toUpperCase()] || "";
    return h("span", { class: "badge " + cls, text: v });
  }
  function scoreBar(score) {
    var cls = score >= 75 ? "ok" : score >= 55 ? "warn" : "bad";
    return h("div", { class: "bar " + cls }, h("i", { style: { width: Math.max(2, Math.min(100, score)) + "%" } }));
  }
  function twoCol(left, right) { return h("div", { class: "grid-2", style: { alignItems: "start" } }, left, right); }

  /* ---------- hook scorer */
  function hooks() {
    var ta = IG.textarea("hooks", { rows: 6, placeholder: "One hook per line\nNobody tells you your first 30 reels are practice\nI lost $18,000 because of one missing line" });
    var out = h("div", { class: "stack-sm" }, h("p", { class: "muted small", text: "Scores each hook on length, specificity, stakes, front-loading and who it speaks to. Highest first." }));
    var run = function () {
      return IG.post("/api/tools/hookscore", { hooks: ta.value }).then(function (r) {
        IG.clear(out);
        r.hooks.forEach(function (x, i) {
          out.appendChild(h("div", { class: "score-row" },
            h("div", null, h("div", { class: "score", text: Math.round(x.score) }), i === 0 && r.hooks.length > 1 ? h("span", { class: "badge accent", text: "Best" }) : null),
            h("div", null,
              h("div", { class: "row between" }, h("b", { class: "grow", text: x.hook }), verdictBadge(x.verdict)),
              h("div", { style: { margin: "8px 0" } }, scoreBar(x.score)),
              h("div", { class: "small muted", text: "Weakest: " + IG.cap(String(x.weakest || "").toLowerCase()) + (x.flags && x.flags.length ? " · " + x.flags.join(", ") : "") }),
              h("details", { class: "more", style: { marginTop: "6px" } }, h("summary", { text: "Details" }),
                h("div", { class: "checks" }, Object.keys(x.checks || {}).map(function (k) { var c = x.checks[k]; return h("div", { class: "c" }, h("b", { text: k + " · " + Math.round(c.score) }), c.detail); }))))));
        });
      });
    };
    return twoCol(IG.card("Your hooks", null, h("div", { class: "stack-sm" }, ta, h("div", null, IG.btn("Score hooks", { cls: "primary", onClick: run })))), IG.card("Ranking", null, out));
  }

  /* ---------- beats */
  function beats() {
    var ta = IG.textarea("script", { rows: 9, placeholder: "One line per beat.\nI lost $18,000.\nBecause of one line in my contract.\nHere is the line I add now…" });
    var target = IG.input("target", { type: "number", min: "3", max: "180", value: "30" });
    var wpm = IG.input("wpm", { type: "number", min: "80", max: "260", value: "165" });
    var out = h("div", { class: "stack-sm" }, h("p", { class: "muted small", text: "Times each beat at your speaking pace and flags the slow, vague or flat ones." }));
    var run = function () {
      return IG.post("/api/tools/beats", { script: ta.value, target: target.value, wpm: wpm.value }).then(function (r) {
        IG.clear(out);
        var total = r.total_seconds || 1;
        out.appendChild(h("div", { class: "stats" }, IG.stat("Length", total.toFixed(1) + "s", r.target ? "target " + r.target + "s" : null, r.target && Math.abs(total - r.target) > r.target * 0.25 ? "down" : "up"), IG.stat("Words", IG.n(r.total_words), r.wpm + " wpm")));
        out.appendChild(h("div", { class: "timeline", role: "img", "aria-label": "Beat timeline" }, r.beats.map(function (b) {
          return h("div", { class: b.label || "", style: { flex: String(b.dur) }, title: b.text, text: b.label === "HOOK" ? "H" : b.label === "CTA" ? "CTA" : String(b.n) });
        })));
        out.appendChild(h("div", { class: "table-wrap" }, h("table", { class: "t" },
          h("thead", null, h("tr", null, h("th", { text: "#" }), h("th", { text: "At" }), h("th", { text: "Line" }), h("th", { class: "n", text: "Sec" }))),
          h("tbody", null, r.beats.map(function (b) {
            return h("tr", null, h("td", { text: b.n }), h("td", { class: "num", text: b.start.toFixed(1) + "s" }),
              h("td", null, b.text, b.label ? h("span", { class: "badge", style: { marginLeft: "6px" }, text: b.label }) : null, (b.flags || []).map(function (f) { return h("div", { class: "small", style: { color: "var(--warn)" }, text: f }); })),
              h("td", { class: "n", text: b.dur.toFixed(1) }));
          })))));
        if (r.notes && r.notes.length) out.appendChild(IG.note("warn", h("ul", { style: { margin: 0, paddingLeft: "18px" } }, r.notes.map(function (n) { return h("li", { text: n }); }))));
      });
    };
    return twoCol(IG.card("Script", null, h("div", { class: "stack-sm" }, ta, h("div", { class: "form-grid" }, IG.field("Target (seconds)", target), IG.field("Speaking pace (wpm)", wpm)), h("div", null, IG.btn("Time it", { cls: "primary", onClick: run })))), IG.card("Beat sheet", null, out));
  }

  /* ---------- caption */
  function caption() {
    var ta = IG.textarea("caption", { rows: 10, placeholder: "Paste your caption" });
    var kw = IG.input("keywords", { placeholder: "e.g. freelance contract, design pricing" });
    var count = h("span", { class: "small faint num", text: "0 / 2,200" });
    ta.addEventListener("input", function () { count.textContent = IG.n(ta.value.length) + " / 2,200"; });
    var out = h("div", { class: "stack-sm" }, h("p", { class: "muted small", text: "Checks the first line that survives the “… more” cut, hashtags, the single ask and search terms." }));
    var run = function () {
      return IG.post("/api/tools/caption", { caption: ta.value, keywords: kw.value }).then(function (r) {
        IG.clear(out);
        var handle = (IG.accounts && IG.accounts.active) || "you";
        out.appendChild(h("div", { class: "row between" }, h("h3", { text: "In the feed" }), verdictBadge(r.verdict)));
        out.appendChild(h("div", { class: "feed" }, h("div", { class: "ph", text: "your post" }),
          h("div", { class: "cap" }, h("b", { text: handle + " " }), r.visible, r.truncated ? h("span", { class: "more", text: "… more" }) : null)));
        out.appendChild(h("div", { class: "stack-sm" }, r.checks.map(function (c) {
          return h("div", { class: "row", style: { alignItems: "flex-start", flexWrap: "nowrap" } }, verdictBadge(c.status), h("div", null, h("b", { class: "small", text: c.check }), h("div", { class: "small muted", text: c.detail })));
        })));
      });
    };
    return twoCol(IG.card("Caption", null, h("div", { class: "stack-sm" }, ta, h("div", { class: "row end" }, count), IG.field("Search terms you want to be found for", kw, "Comma-separated"), h("div", null, IG.btn("Check caption", { cls: "primary", onClick: run })))), IG.card("Result", null, out));
  }

  /* ---------- humanizer */
  function human() {
    var ta = IG.textarea("text", { rows: 10, placeholder: "Paste a draft: caption, script, comment or DM" });
    var out = h("div", { class: "stack-sm" }, h("p", { class: "muted small", text: "Strips em dashes, stock AI phrases and invisible characters, then scores before and after on five checks." }));
    var run = function () {
      return IG.post("/api/tools/humanize", { text: ta.value }).then(function (r) {
        IG.clear(out);
        out.appendChild(h("div", { class: "stats" },
          IG.stat("Before", Math.round(r.before.human_score) + "/100", r.before.verdict, r.before.human_score >= 70 ? "up" : "down"),
          IG.stat("After", Math.round(r.after.human_score) + "/100", r.after.verdict, r.after.human_score >= 70 ? "up" : "down")));
        out.appendChild(h("div", { class: "row between" }, h("h3", { text: "Cleaned" }), IG.btn("Copy", { cls: "sm", onClick: function () { IG.copy(r.text); } })));
        out.appendChild(h("div", { class: "planbox", style: { fontFamily: "var(--sans)", fontSize: "14.5px" }, text: r.text }));
        var rep = r.report || {}, changes = [];
        (rep.typographic || []).forEach(function (x) { changes.push(x.name + " ×" + x.count + " → " + JSON.stringify(x.to)); });
        (rep.lexical || []).forEach(function (x) { changes.push("“" + x.find + "” → “" + x.replace + "”"); });
        (rep.invisible || []).forEach(function (x) { changes.push("invisible: " + (x.name || JSON.stringify(x))); });
        (rep.structures || []).forEach(function (x) { changes.push("structure: " + (x.name || x.pattern || JSON.stringify(x))); });
        if (changes.length) out.appendChild(h("details", { class: "more" }, h("summary", { text: changes.length + " changes" }), h("ul", { class: "small", style: { margin: "6px 0 0", paddingLeft: "18px" } }, changes.map(function (c) { return h("li", { text: c }); }))));
        out.appendChild(h("div", { class: "checks" }, Object.keys(r.after.checks || {}).map(function (k) { var c = r.after.checks[k]; return h("div", { class: "c" }, h("b", { text: k + " · " + Math.round(c.score) }), c.detail); })));
      });
    };
    return twoCol(IG.card("Draft", null, h("div", { class: "stack-sm" }, ta, h("div", null, IG.btn("Humanize", { cls: "primary", onClick: run })))), IG.card("Result", null, out));
  }

  /* ---------- carousel */
  var EXAMPLE = { kind: "carousel", handle: "", alt: "", slides: [
    { role: "cover", title: "THE $18,000 CLAUSE", body: "One line I now put in every contract." },
    { title: "I approved the work.", body: "They asked for the money back nine days later." },
    { title: "What it says", body: "Payment is due on delivery, not on approval." },
    { title: "Why delivery wins", body: "Delivery is a date you can prove. Approval is a mood you cannot." },
    { role: "recap", title: "The rule", list: ["Payment on delivery", "Five days to raise changes", "Silence is acceptance"] },
    { role: "cta", title: "Comment CONTRACT", body: "I will send you the full clause." }] };

  function carousel() {
    var spec = JSON.parse(sessionStorage.getItem("igcarousel") || "null") || { kind: "carousel", handle: (IG.accounts && IG.accounts.active) ? "@" + IG.accounts.active : "", alt: "", slides: [{ role: "cover", title: "", body: "" }, { title: "", body: "" }] };
    var list = h("div", { class: "slides" });
    var out = h("div", { class: "stack-sm" });
    var persist = function () { try { sessionStorage.setItem("igcarousel", JSON.stringify(spec)); } catch (e) { /* ignore */ } };
    var items = function () { return spec.kind === "story" ? (spec.frames = spec.frames || [{ title: "" }]) : (spec.slides = spec.slides || []); };
    function draw() {
      IG.clear(list);
      var arr = items();
      arr.forEach(function (s, i) {
        var role = IG.select("role", spec.kind === "story" ? [["", "Frame"]] : [["", "Body"], ["cover", "Cover"], ["recap", "Recap list"], ["cta", "Call to action"]], s.role || "");
        var title = IG.input("title", { value: s.title || "", placeholder: i === 0 ? "Cover title, short and big" : "Title" });
        var body = IG.textarea("body", { rows: 2, value: s.body || "", placeholder: "Body text (25 words max reads best)" });
        var lst = IG.textarea("list", { rows: 3, value: (s.list || []).join("\n"), placeholder: "One point per line" });
        var extra = IG.input(spec.kind === "story" ? "sticker" : "note", { value: (spec.kind === "story" ? s.sticker : "") || "", placeholder: "poll: Yes / Not yet" });
        var listField = IG.field("Recap points", lst); listField.hidden = s.role !== "recap";
        var sync = function () {
          s.role = role.value || undefined; s.title = title.value; s.body = body.value;
          s.list = s.role === "recap" ? lst.value.split("\n").map(function (x) { return x.trim(); }).filter(Boolean) : undefined;
          if (spec.kind === "story") s.sticker = extra.value || undefined;
          listField.hidden = s.role !== "recap"; persist();
        };
        [role, title, body, lst, extra].forEach(function (el) { el.addEventListener("input", sync); el.addEventListener("change", sync); });
        var move = function (d) { var j = i + d; if (j < 0 || j >= arr.length) return; var t = arr[i]; arr[i] = arr[j]; arr[j] = t; persist(); draw(); };
        list.appendChild(h("div", { class: "slide-ed" },
          h("div", { class: "idx", text: String(i + 1) }),
          h("div", { class: "stack-sm" }, h("div", { class: "form-grid" }, IG.field("Type", role), IG.field("Title", title, null, "span-2")), IG.field("Text", body), listField,
            spec.kind === "story" ? IG.field("Sticker (optional)", extra) : null),
          h("div", { class: "tools" },
            h("button", { class: "btn ghost sm", type: "button", "aria-label": "Move slide " + (i + 1) + " up", onclick: function () { move(-1); } }, IG.icon("up")),
            h("button", { class: "btn ghost sm", type: "button", "aria-label": "Move slide " + (i + 1) + " down", onclick: function () { move(1); } }, IG.icon("down")),
            h("button", { class: "btn ghost sm danger", type: "button", "aria-label": "Delete slide " + (i + 1), onclick: function () { arr.splice(i, 1); persist(); draw(); } }, IG.icon("trash")))));
      });
    }
    var handle = IG.input("handle", { value: spec.handle || "", placeholder: "@yourhandle" });
    var alt = IG.textarea("alt", { rows: 2, value: spec.alt || "", placeholder: "Cover slide reading: …" });
    handle.addEventListener("input", function () { spec.handle = handle.value; persist(); });
    alt.addEventListener("input", function () { spec.alt = alt.value; persist(); });
    var kindSeg = IG.seg([["carousel", "Carousel 4:5"], ["story", "Story 9:16"]], spec.kind, function (k) { spec.kind = k; persist(); draw(); }, "Format");
    var render = function () {
      var arr = items().filter(function (s) { return (s.title || "").trim() || (s.body || "").trim() || (s.list && s.list.length); });
      if (!arr.length) { IG.toast("Write at least one slide.", "bad"); return; }
      var body = { kind: spec.kind, handle: spec.handle, alt: spec.alt };
      body[spec.kind === "story" ? "frames" : "slides"] = arr;
      return IG.runJob(IG.post("/api/render", { spec: body }), out, { label: "Rendering with Chrome…" }).then(function (r) {
        IG.clear(out);
        out.appendChild(h("div", { class: "row between" }, h("h3", { text: r.files.length + " images" }), h("a", { class: "btn primary sm", href: r.zip }, IG.icon("download"), h("span", { text: "Download all" }))));
        out.appendChild(h("div", { class: "gallery" }, r.files.map(function (f) {
          return h("figure", null, h("a", { href: f.url, target: "_blank", rel: "noopener" }, h("img", { src: f.url, alt: f.name, loading: "lazy" })),
            h("figcaption", null, h("span", { text: f.name }), h("a", { href: f.download, text: "Save" })));
        })));
        if (r.alt_text) out.appendChild(h("div", { class: "stack-sm" }, h("div", { class: "row between" }, h("h3", { text: "Alt text" }), IG.btn("Copy", { cls: "sm", onClick: function () { IG.copy(r.alt_text); } })), h("div", { class: "planbox", text: r.alt_text })));
        if (r.report) out.appendChild(h("details", { class: "more" }, h("summary", { text: "Render report" }), h("div", { class: "log", text: r.report })));
        out.appendChild(h("p", { class: "small muted", text: "Upload in file order. Nothing was uploaded for you." }));
      });
    };
    draw();
    var noChrome = IG.status && !IG.status.chrome;
    return h("div", { class: "stack" },
      noChrome ? IG.note("warn", "Rendering needs Google Chrome (or Chromium/Edge). Install it, or set CHROME_PATH, then restart IG Studio.") : null,
      twoCol(
        IG.card("Slides", "Write the approved copy. Slide 1 is the cover.", h("div", { class: "stack-sm" },
          kindSeg, list,
          h("div", { class: "row" }, IG.btn("Add slide", { icon: "plus", onClick: function () { items().push({ title: "", body: "" }); persist(); draw(); } }),
            IG.btn("Load example", { cls: "ghost", onClick: function () { spec = JSON.parse(JSON.stringify(EXAMPLE)); spec.handle = handle.value; persist(); IG.render("create"); } })),
          h("div", { class: "form-grid" }, IG.field("Handle on slides", handle), IG.field("Cover alt text", alt, null, "span-all")),
          h("div", null, IG.btn("Render images", { cls: "primary", onClick: render })))),
        IG.card("Images", "1080×1350 for carousels, 1080×1920 for stories", out.childNodes.length ? out : (out.appendChild(h("p", { class: "muted small", text: "Rendered slides show up here with a grid-crop preview and alt text." })), out))));
  }

  /* ---------- video */
  function video() {
    var file = h("input", { type: "file", accept: "video/*,.mov,.mp4,.m4v", id: "vid-file" });
    var up = h("div");
    var opts = h("form", { class: "stack-sm", hidden: true });
    var out = h("div", { class: "stack" });
    var source = null;
    var hook = IG.input("hook_text", { placeholder: "e.g. 5 HOURS -> 20 MIN", maxlength: "120" });
    var cut = h("input", { type: "checkbox", name: "cut_silence", checked: true });
    var caps = IG.select("captions", [["burn", "Burn in"], ["srt", "Separate .srt"], ["none", "None"]], "burn");
    var crop = IG.select("crop", [["auto", "Auto"], ["center", "Centre crop"], ["none", "Fit whole frame"]], "auto");
    var script = IG.textarea("script", { rows: 4, placeholder: "Optional: your script, one line per beat (used for captions if Whisper isn't installed)" });
    var start = IG.input("start", { placeholder: "00:00:00" });
    var end = IG.input("end", { placeholder: "00:00:30" });
    var maxLen = IG.input("max_length", { type: "number", min: "5", placeholder: "90" });
    var preset = IG.select("preset", [["veryfast", "Fast export"], ["fast", "Balanced"], ["medium", "Best quality (slower)"]], "fast");
    opts.appendChild(h("div", { class: "form-grid" },
      IG.field("Hook card (first 2.5s)", hook, "-> becomes an arrow", "span-2"),
      IG.field("Captions", caps), IG.field("Framing", crop),
      IG.field("Clip start", start, "Optional"), IG.field("Clip end", end, "Optional"),
      IG.field("Max length (s)", maxLen), IG.field("Export", preset)));
    opts.appendChild(h("label", { class: "check" }, cut, "Cut the pauses"));
    opts.appendChild(IG.field("Script", script));
    opts.appendChild(h("div", null, IG.btn("Make my reel", { cls: "primary", type: "submit" })));
    var noWhisper = IG.status && !IG.status.whisper;
    if (noWhisper) opts.appendChild(h("p", { class: "small muted", text: "No local Whisper found, so captions come from your script (approximate timing) or are skipped." }));
    file.addEventListener("change", function () {
      var f = file.files && file.files[0];
      if (!f) return;
      var bar = h("div", { class: "progress" }, h("i"));
      var lbl = h("span", { class: "small muted", text: "Uploading " + f.name + " (" + IG.n(f.size / 1048576, 1) + " MB)…" });
      IG.clear(up).appendChild(h("div", { class: "stack-sm" }, lbl, bar));
      IG.upload(f, "video", function (p) { bar.firstChild.style.width = Math.round(p * 100) + "%"; }).then(function (r) {
        source = r;
        IG.clear(up).appendChild(h("div", { class: "row" }, IG.icon("check"), h("span", { text: r.name + " is ready." })));
        opts.hidden = false;
      }).catch(function (e) { IG.clear(up).appendChild(IG.note("bad", e.message)); });
    });
    opts.addEventListener("submit", function (e) {
      e.preventDefault();
      if (!source) return;
      var body = IG.formData(opts);
      body.path = source.path;
      var btn = opts.querySelector("button[type=submit]");
      IG.busy(btn, function () {
        return IG.runJob(IG.post("/api/video/edit", body), out, { label: "Editing with ffmpeg… long videos take a few minutes" }).then(function (r) { showResult(r); });
      });
    });
    function showResult(r) {
      IG.clear(out);
      var rep = r.report || {};
      if (!r.video) { out.appendChild(IG.note("warn", "No video was written. " + ((rep.warnings || []).join(" ") || ""))); return; }
      var vid = h("video", { src: r.video.url, controls: true, playsinline: true, preload: "metadata" });
      var coverOut = h("div", { class: "stack-sm" });
      var side = h("div", { class: "stack-sm grow", style: { minWidth: "240px" } },
        h("div", { class: "stats" }, IG.stat("Length", (rep.output_duration || 0).toFixed(1) + "s", rep.window ? "from " + rep.window.length.toFixed(1) + "s" : null), IG.stat("Cut", (rep.seconds_cut || 0).toFixed(1) + "s", (rep.cuts || 0) + " cuts")),
        h("div", { class: "row" }, h("a", { class: "btn primary", href: r.video.download }, IG.icon("download"), h("span", { text: "Download reel.mp4" })),
          r.srt ? h("a", { class: "btn", href: r.srt.download, text: "Captions .srt" }) : null),
        (rep.warnings || []).length ? IG.note("warn", h("ul", { style: { margin: 0, paddingLeft: "18px" } }, rep.warnings.map(function (w) { return h("li", { text: w }); }))) : null,
        (rep.notes || []).length ? h("ul", { class: "small muted", style: { margin: 0, paddingLeft: "18px" } }, rep.notes.map(function (w) { return h("li", { text: w }); })) : null,
        h("div", { class: "card tint stack-sm" }, h("h3", { text: "Cover" }), h("p", { class: "small muted", text: "Pause the video on the frame you want, then grab it." }),
          IG.btn("Use current frame as cover", { onClick: function () {
            return IG.post("/api/video/cover", { video: r.video.path, at: vid.currentTime || 0 }).then(function (c) {
              IG.clear(coverOut).appendChild(h("div", { class: "row", style: { alignItems: "flex-start" } }, h("img", { src: c.url, alt: "Cover frame", style: { width: "120px", borderRadius: "10px", border: "1px solid var(--border)" } }),
                h("div", { class: "stack-sm" }, h("a", { class: "btn sm", href: c.download }, IG.icon("download"), h("span", { text: "Download cover" })), (c.warnings || []).map(function (w) { return h("div", { class: "small muted", text: w }); }))));
            });
          } }), coverOut));
      out.appendChild(h("div", { class: "video-wrap" }, vid, side));
      if (r.checks && r.checks.length) out.appendChild(h("div", { class: "stack-sm" }, h("h3", { text: "Safe-zone check frames" }), h("p", { class: "small muted", text: "Red areas are covered by Instagram's buttons and caption. Keep words out of them." }),
        h("div", { class: "gallery" }, r.checks.map(function (c) { return h("figure", null, h("img", { src: c.url, alt: c.name, loading: "lazy" }), h("figcaption", { text: c.name })); }))));
      out.appendChild(h("p", { class: "small muted", text: "Add music inside Instagram when you post, so it stays licensed. Nothing was uploaded." }));
    }
    var noFf = IG.status && !IG.status.ffmpeg;
    return h("div", { class: "stack" },
      noFf ? IG.note("warn", "Video editing needs ffmpeg. On a Mac: brew install ffmpeg. On Windows: winget install ffmpeg. Then restart IG Studio.") : null,
      IG.card("Your footage", "Cuts pauses, frames it 9:16 at 1080×1920, adds captions and a hook card. Runs on this computer.",
        h("div", { class: "stack-sm" }, IG.field("Video file (up to 4 GB)", file), up, opts)),
      out);
  }

  var BUILDERS = { hooks: hooks, beats: beats, caption: caption, human: human, carousel: carousel, video: video };
  IG.screen("create", {
    title: "Create", icon: "create",
    render: function (view, params) {
      var cur = params.tool || sessionStorage.getItem("igcreate") || "hooks";
      if (!BUILDERS[cur]) cur = "hooks";
      var body = h("div");
      var show = function (k) { cur = k; try { sessionStorage.setItem("igcreate", k); } catch (e) { /* ignore */ } IG.clear(body).appendChild(BUILDERS[k]()); };
      view.appendChild(h("div", { class: "stack" },
        h("div", { class: "row between" }, IG.seg(TOOLS, cur, show, "Tool"), h("span", { class: "small muted", text: "Instant. No AI, nothing leaves this computer." })),
        body));
      show(cur);
    }
  });
})();
