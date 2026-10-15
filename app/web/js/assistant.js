/* Assistant: chat with Claude running the ig skills, streamed. */
(function () {
  "use strict";
  var h = IG.h;
  var CHIPS = [
    ["Write a reel", "/ig-reel Write a reel about: "],
    ["Make a carousel", "/ig-carousel Make a carousel about: "],
    ["Find trends", "/ig-trends Find what's trending in my region and my niche this week, then update my trend board."],
    ["Pick a song", "/ig-audio Pick the sound for my next reel. It's about: "],
    ["Weekly growth review", "/ig-grow Run my weekly growth review."],
    ["Plan my week", "/ig-plan Plan my week. What happened this week: "],
    ["Fix my profile", "/ig-profile Score my profile and rewrite what loses points. (Attach a screenshot of the top of your profile.)"],
    ["Check a reel", "/ig-perf Check how my latest reel is doing. (Attach an insights screenshot if you have one.)"]
  ];
  var chat = IG.chat = { key: null, session_id: null, messages: [], job: null, stream: null, running: false };
  var ui = null; // {log, input, sendBtn, stopBtn, attachList, pending: []}

  function storeKey() { return "igchat:" + chat.key; }
  function save() {
    try {
      var msgs = chat.messages.slice(-80).map(function (m) {
        var c = Object.assign({}, m);
        if (c.files) c.files = c.files.map(function (f) { return { path: f.path, name: f.name, kind: f.kind }; });
        if (c.attachments) c.attachments = c.attachments.map(function (f) { return { path: f.path, name: f.name }; });
        if (c.running) { c.running = false; c.error = c.error || "Stopped when the page was closed."; }
        return c;
      });
      localStorage.setItem(storeKey(), JSON.stringify({ session_id: chat.session_id, messages: msgs }));
    } catch (e) { /* storage is a convenience */ }
  }
  function load() {
    var key = IG.accountKey();
    if (chat.key === key) return Promise.resolve();
    if (chat.stream) { chat.stream.stop(); chat.stream = null; }
    chat.key = key; chat.session_id = null; chat.messages = []; chat.running = false; chat.job = null;
    var d = null;
    try { d = JSON.parse(localStorage.getItem(storeKey()) || "null"); } catch (e) { d = null; }
    if (!d) return Promise.resolve();
    chat.session_id = d.session_id || null;
    chat.messages = d.messages || [];
    var paths = [];
    chat.messages.forEach(function (m) { (m.files || []).concat(m.attachments || []).forEach(function (f) { if (f.path) paths.push(f.path); }); });
    if (!paths.length) return Promise.resolve();
    return IG.post("/api/sign", { paths: paths }).then(function (r) {
      chat.messages.forEach(function (m) {
        (m.files || []).concat(m.attachments || []).forEach(function (f) { var u = r.urls[f.path]; if (u) { f.url = u.url; f.download = u.download; } else f.gone = true; });
      });
    }).catch(function () { /* old links just won't preview */ });
  }
  IG.onAccountChange = function () { if (!chat.running) chat.key = null; };

  /* ---------- rendering */
  function fileView(f) {
    if (f.gone || !f.url) return h("div", { class: "f" }, h("span", { class: "badge", text: f.name }));
    if (f.kind === "image") return h("div", { class: "f" }, h("a", { href: f.url, target: "_blank", rel: "noopener" }, h("img", { src: f.url, alt: f.name, loading: "lazy" })), h("div", { class: "cap ellipsis", text: f.name }));
    if (f.kind === "video") return h("div", { class: "f" }, h("video", { src: f.url, controls: true, preload: "metadata", playsinline: true }), h("div", { class: "cap" }, h("a", { href: f.download || f.url, text: "Download " + f.name })));
    if (f.kind === "calendar") return h("div", { class: "f" }, h("a", { class: "btn sm", href: f.download || f.url }, IG.icon("calendar"), h("span", { text: f.name })));
    return h("div", { class: "f" }, h("a", { class: "btn sm", href: f.download || f.url }, IG.icon("download"), h("span", { text: f.name })));
  }

  function paint(m, el) {
    IG.clear(el);
    if (m.role === "user") {
      el.className = "msg user";
      el.appendChild(document.createTextNode(m.text));
      if (m.attachments && m.attachments.length) el.appendChild(h("div", { class: "att", text: "📎 " + m.attachments.map(function (a) { return a.name; }).join(", ") }));
      return;
    }
    el.className = "msg bot" + (m.error ? " err" : "");
    var b = h("div", { class: "bubble" });
    if (m.tools && m.tools.length) {
      b.appendChild(h("div", { class: "tools-list" }, m.tools.map(function (t) {
        var state = t.error ? "err" : (t.done || !m.running ? "done" : "run");
        return h("div", { class: "tool " + state + (t.sub ? " sub" : "") },
          h("span", { class: "ic" }, state === "run" ? h("span", { class: "spin", style: { width: "12px", height: "12px", borderWidth: "2px" } }) : IG.icon(state === "err" ? "x" : "check")),
          h("span", { class: "ellipsis", text: t.summary + (state === "run" ? "…" : "") }));
      })));
    }
    if (m.text) b.appendChild(IG.md(m.text));
    else if (m.running) b.appendChild(h("div", { class: "typing", "aria-label": "Claude is working" }, h("i"), h("i"), h("i")));
    if (m.files && m.files.length) b.appendChild(h("div", { class: "files" }, m.files.map(fileView)));
    if (m.error) b.appendChild(IG.note(m.status === "cancelled" ? "" : "bad", m.error));
    el.appendChild(b);
  }

  var raf = null;
  function repaintLast() {
    if (!ui || raf) return;
    raf = requestAnimationFrame(function () {
      raf = null;
      if (!ui) return;
      var last = chat.messages[chat.messages.length - 1];
      var el = ui.log.lastElementChild;
      if (last && el) {
        var nearBottom = ui.log.scrollHeight - ui.log.scrollTop - ui.log.clientHeight < 120;
        paint(last, el);
        if (nearBottom) ui.log.scrollTop = ui.log.scrollHeight;
      }
      syncButtons();
    });
  }
  function renderLog() {
    if (!ui) return;
    IG.clear(ui.log);
    if (!chat.messages.length) {
      ui.log.appendChild(h("div", { class: "card tint", style: { maxWidth: "680px" } },
        h("h2", { text: "What should we make?" }),
        h("p", { class: "muted", style: { margin: "6px 0 14px" }, text: "Claude runs the ig skills for you: it writes in your voice, scores hooks, renders slides and plans the week. It asks before anything goes in your calendar and never posts for you." }),
        h("div", { class: "chips" }, CHIPS.map(chipBtn))));
    }
    chat.messages.forEach(function (m) { var el = h("div"); paint(m, el); ui.log.appendChild(el); });
    ui.log.scrollTop = ui.log.scrollHeight;
    syncButtons();
  }
  function syncButtons() {
    if (!ui) return;
    ui.sendBtn.hidden = chat.running;
    ui.stopBtn.hidden = !chat.running;
  }
  function chipBtn(c) {
    return h("button", { class: "chip", type: "button", text: c[0], onclick: function () { setInput(c[1]); } });
  }
  function setInput(text) {
    if (!ui) return;
    ui.input.value = text;
    autosize();
    ui.input.focus();
    ui.input.setSelectionRange(text.length, text.length);
  }
  function autosize() { ui.input.style.height = "auto"; ui.input.style.height = Math.min(240, ui.input.scrollHeight + 2) + "px"; }

  /* ---------- sending */
  function send(text, attachments) {
    text = (text || "").trim();
    if (!text || chat.running) return;
    attachments = attachments || [];
    chat.messages.push({ role: "user", text: text, attachments: attachments });
    var bot = { role: "bot", text: "", tools: [], files: [], running: true };
    chat.messages.push(bot);
    chat.running = true;
    renderLog();
    save();
    IG.post("/api/chat", { prompt: text, session_id: chat.session_id, attachments: attachments.map(function (a) { return a.path; }) }).then(function (res) {
      chat.job = res.job;
      chat.stream = IG.stream(res.job, function (ev) { onEvent(bot, ev); });
    }).catch(function (e) {
      bot.running = false; bot.error = e.message; chat.running = false;
      repaintLast(); save();
    });
  }
  function onEvent(bot, ev) {
    if (ev.type === "session") chat.session_id = ev.session_id;
    else if (ev.type === "text") bot.text += ev.text;
    else if (ev.type === "tool") bot.tools.push({ id: ev.id, summary: ev.summary, sub: ev.sub });
    else if (ev.type === "tool_done") { bot.tools.forEach(function (t) { if (t.id === ev.id) { t.done = true; t.error = ev.error; } }); }
    else if (ev.type === "file") { if (!bot.files.some(function (f) { return f.path === ev.path; })) bot.files.push({ path: ev.path, name: ev.name, kind: ev.kind, url: ev.url, download: ev.download }); }
    else if (ev.type === "end") {
      bot.running = false; chat.running = false; chat.stream = null; chat.job = null;
      if (ev.session_id) chat.session_id = ev.session_id;
      bot.status = ev.status;
      if (ev.status === "cancelled") bot.error = "Stopped.";
      else if (ev.status !== "done") bot.error = ev.error || "Claude stopped.";
      save();
      if (IG.current !== "assistant") IG.toast(ev.status === "done" ? "Claude replied" : "Claude stopped");
    }
    repaintLast();
  }

  function addFiles(files) {
    files = Array.prototype.slice.call(files || []).filter(function (f) { return /^image\//.test(f.type); });
    if (!files.length) { IG.toast("Only images can be attached here.", "bad"); return; }
    files.forEach(function (f) {
      var item = { name: f.name || "pasted.png", uploading: true };
      ui.pending.push(item);
      drawAttach();
      IG.upload(f, "image").then(function (up) { item.uploading = false; item.path = up.path; item.url = up.url; item.name = up.name; drawAttach(); })
        .catch(function (e) { ui.pending.splice(ui.pending.indexOf(item), 1); drawAttach(); IG.fail(e); });
    });
  }
  function drawAttach() {
    IG.clear(ui.attachList);
    ui.pending.forEach(function (a, i) {
      ui.attachList.appendChild(h("span", { class: "a" }, a.url ? h("img", { src: a.url, alt: "" }) : h("span", { class: "spin", style: { width: "14px", height: "14px" } }),
        h("span", { class: "ellipsis", style: { maxWidth: "140px" }, text: a.name }),
        h("button", { class: "btn ghost sm", type: "button", "aria-label": "Remove " + a.name, onclick: function () { ui.pending.splice(i, 1); drawAttach(); } }, IG.icon("x"))));
    });
  }

  IG.screen("assistant", {
    title: "Assistant", icon: "assistant",
    render: function (view, params, m) {
      if (!IG.claudeReady()) { view.appendChild(IG.installCard()); return; }
      view.appendChild(IG.loading());
      return load().then(function () {
        if (!IG.alive(m)) return;
        IG.clear(view);
        var log = h("div", { class: "chat-log", "aria-live": "polite", "aria-label": "Conversation" });
        var input = IG.textarea("prompt", { rows: 2, placeholder: "Ask Claude… (Enter to send, Shift+Enter for a new line)", "aria-label": "Message" });
        var file = h("input", { type: "file", accept: "image/*", multiple: true, class: "sr", id: "chat-file" });
        var sendBtn = IG.btn("Send", { cls: "primary sm", icon: "send" });
        var stopBtn = IG.btn("Stop", { cls: "sm danger", icon: "stop" });
        var attachList = h("div", { class: "attach-list" });
        ui = { log: log, input: input, sendBtn: sendBtn, stopBtn: stopBtn, attachList: attachList, pending: [] };
        var doSend = function () {
          if (ui.pending.some(function (a) { return a.uploading; })) { IG.toast("Wait for the image to finish uploading."); return; }
          var atts = ui.pending.slice();
          var text = input.value;
          if (!text.trim()) return;
          input.value = ""; ui.pending = []; drawAttach(); autosize();
          send(text, atts);
        };
        sendBtn.addEventListener("click", doSend);
        stopBtn.addEventListener("click", function () { if (chat.stream) chat.stream.cancel().catch(IG.fail); });
        input.addEventListener("keydown", function (e) { if (e.key === "Enter" && !e.shiftKey && !e.isComposing) { e.preventDefault(); doSend(); } });
        input.addEventListener("input", autosize);
        input.addEventListener("paste", function (e) {
          var items = (e.clipboardData && e.clipboardData.files) || [];
          if (items.length) { e.preventDefault(); addFiles(items); }
        });
        file.addEventListener("change", function () { addFiles(file.files); file.value = ""; });
        var composer = h("div", { class: "composer" }, attachList, input,
          h("div", { class: "bar-row" },
            h("div", { class: "row", style: { gap: "4px" } },
              h("label", { class: "btn ghost sm", for: "chat-file", title: "Attach images (insights screenshots, your profile…)" }, IG.icon("clip"), h("span", { text: "Image" })), file,
              IG.btn("New chat", { cls: "ghost sm", icon: "plus", onClick: function () {
                if (chat.running) { IG.toast("Stop the current reply first."); return; }
                chat.session_id = null; chat.messages = []; save(); renderLog();
              } })),
            h("div", { class: "row", style: { gap: "6px" } }, h("span", { class: "tiny faint", text: "Never posts for you" }), stopBtn, sendBtn)));
        composer.addEventListener("dragover", function (e) { e.preventDefault(); });
        composer.addEventListener("drop", function (e) { e.preventDefault(); addFiles(e.dataTransfer.files); });
        var chipsRow = chat.messages.length ? h("div", { class: "chips", style: { marginBottom: "8px" } }, CHIPS.map(chipBtn)) : null;
        view.appendChild(h("div", { class: "chat" }, log, h("div", null, chipsRow, composer)));
        renderLog();
        var p = IG.pendingAsk; IG.pendingAsk = null;
        if (p) {
          if (p.attachments && p.attachments.length) { ui.pending = p.attachments.slice(); drawAttach(); }
          if (p.send && !chat.running) { send(p.prompt, ui.pending.slice()); ui.pending = []; drawAttach(); }
          else setInput(p.prompt);
        } else input.focus();
      });
    },
    leave: function () { ui = null; }
  });

  // Keep painting while the view is mounted; drop references when it is not.
  var origRender = IG.render;
  IG.render = function (id) { if (id !== "assistant") ui = null; return origRender(id); };
})();
