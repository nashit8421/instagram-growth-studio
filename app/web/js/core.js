/* IG Studio core: DOM helpers, API, uploads, job streams, router, dialogs. */
(function () {
  "use strict";
  var IG = window.IG = {
    token: null, screens: {}, order: [], current: null, params: {}, mount: 0,
    status: null, accounts: null, state: null
  };

  /* ---------------- icons (constant SVG strings, trusted) */
  var P = {
    today: '<circle cx="12" cy="12" r="4"/><path d="M12 2v2M12 20v2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M2 12h2M20 12h2M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4"/>',
    account: '<circle cx="12" cy="8" r="4"/><path d="M4 21c1.5-4 4.5-6 8-6s6.5 2 8 6"/>',
    assistant: '<path d="M12 3l1.8 4.7L18.5 9.5l-4.7 1.8L12 16l-1.8-4.7L5.5 9.5l4.7-1.8z"/><path d="M19 15l.8 2.2L22 18l-2.2.8L19 21l-.8-2.2L16 18l2.2-.8z"/>',
    create: '<path d="M4 20l4-1L19 8a2.1 2.1 0 0 0-3-3L5 16z"/><path d="M14 7l3 3"/>',
    posts: '<rect x="3" y="3" width="7" height="7" rx="1.5"/><rect x="14" y="3" width="7" height="7" rx="1.5"/><rect x="3" y="14" width="7" height="7" rx="1.5"/><rect x="14" y="14" width="7" height="7" rx="1.5"/>',
    growth: '<path d="M3 17l6-6 4 4 8-8"/><path d="M15 7h6v6"/>',
    trends: '<path d="M12 22c4 0 7-3 7-7 0-4-3-6-4-9-1 2-2 3-3.5 3.5C11 7 10 5 10 3 7 5 5 9 5 14c0 4.5 3 8 7 8z"/>',
    calendar: '<rect x="3" y="5" width="18" height="16" rx="2"/><path d="M3 10h18M8 3v4M16 3v4"/>',
    settings: '<circle cx="12" cy="12" r="3"/><path d="M19.4 15a1.7 1.7 0 0 0 .3 1.8l.1.1a2 2 0 1 1-2.8 2.8l-.1-.1a1.7 1.7 0 0 0-1.8-.3 1.7 1.7 0 0 0-1 1.5V21a2 2 0 1 1-4 0v-.1a1.7 1.7 0 0 0-1.1-1.5 1.7 1.7 0 0 0-1.8.3l-.1.1a2 2 0 1 1-2.8-2.8l.1-.1a1.7 1.7 0 0 0 .3-1.8 1.7 1.7 0 0 0-1.5-1H3a2 2 0 1 1 0-4h.1a1.7 1.7 0 0 0 1.5-1.1 1.7 1.7 0 0 0-.3-1.8l-.1-.1a2 2 0 1 1 2.8-2.8l.1.1a1.7 1.7 0 0 0 1.8.3H9a1.7 1.7 0 0 0 1-1.5V3a2 2 0 1 1 4 0v.1a1.7 1.7 0 0 0 1 1.5 1.7 1.7 0 0 0 1.8-.3l.1-.1a2 2 0 1 1 2.8 2.8l-.1.1a1.7 1.7 0 0 0-.3 1.8V9a1.7 1.7 0 0 0 1.5 1H21a2 2 0 1 1 0 4h-.1a1.7 1.7 0 0 0-1.5 1z"/>',
    check: '<path d="M5 12.5l4.5 4.5L19 7.5"/>',
    x: '<path d="M6 6l12 12M18 6L6 18"/>',
    alert: '<path d="M12 3l10 18H2z"/><path d="M12 10v5M12 18v.5"/>',
    info: '<circle cx="12" cy="12" r="9"/><path d="M12 11v6M12 7.5v.5"/>',
    upload: '<path d="M12 16V4M7 9l5-5 5 5"/><path d="M4 16v3a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2v-3"/>',
    download: '<path d="M12 4v12M7 11l5 5 5-5"/><path d="M4 16v3a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2v-3"/>',
    send: '<path d="M4 12l16-8-6 16-2-6z"/>',
    stop: '<rect x="6" y="6" width="12" height="12" rx="2"/>',
    plus: '<path d="M12 5v14M5 12h14"/>',
    trash: '<path d="M4 7h16M10 11v6M14 11v6M6 7l1 13h10l1-13M9 7V4h6v3"/>',
    up: '<path d="M6 15l6-6 6 6"/>',
    down: '<path d="M6 9l6 6 6-6"/>',
    clip: '<path d="M20 11l-8.5 8.5a5 5 0 0 1-7-7L13 4a3.5 3.5 0 0 1 5 5l-8.5 8.5a2 2 0 0 1-3-3L14 7"/>',
    refresh: '<path d="M20 11a8 8 0 0 0-14.6-4.5L4 8M4 4v4h4M4 13a8 8 0 0 0 14.6 4.5L20 16M20 20v-4h-4"/>',
    folder: '<path d="M3 7a2 2 0 0 1 2-2h4l2 2h8a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z"/>',
    arrow: '<path d="M5 12h14M13 6l6 6-6 6"/>',
    lock: '<rect x="5" y="11" width="14" height="10" rx="2"/><path d="M8 11V8a4 4 0 0 1 8 0v3"/>',
    eye: '<path d="M2 12s3.5-7 10-7 10 7 10 7-3.5 7-10 7S2 12 2 12z"/><circle cx="12" cy="12" r="3"/>'
  };
  IG.icon = function (name, cls) {
    var span = document.createElement("span");
    span.className = "ic-wrap";
    span.style.display = "inline-flex";
    span.setAttribute("aria-hidden", "true");
    span.innerHTML = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.9" stroke-linecap="round" stroke-linejoin="round"' +
      (cls ? ' class="' + cls + '"' : "") + ">" + (P[name] || "") + "</svg>";
    return span.firstChild;
  };

  /* ---------------- DOM builder */
  function h(tag, attrs) {
    var el = document.createElement(tag);
    var kids = Array.prototype.slice.call(arguments, 2);
    if (attrs && (typeof attrs !== "object" || attrs instanceof Node || Array.isArray(attrs))) { kids.unshift(attrs); attrs = null; }
    if (attrs) {
      Object.keys(attrs).forEach(function (k) {
        var v = attrs[k];
        if (v === null || v === undefined || v === false) return;
        if (k === "class") el.className = v;
        else if (k === "text") el.textContent = v;
        else if (k === "html") el.innerHTML = v; // only used with trusted / escaped content
        else if (k.slice(0, 2) === "on" && typeof v === "function") el.addEventListener(k.slice(2), v);
        else if (k === "dataset") Object.keys(v).forEach(function (d) { el.dataset[d] = v[d]; });
        else if (k === "style" && typeof v === "object") Object.keys(v).forEach(function (s) { el.style[s] = v[s]; });
        else if (k === "value" && (tag === "input" || tag === "textarea" || tag === "select")) el.value = v;
        else if (k === "checked") el.checked = !!v;
        else if (v === true) el.setAttribute(k, "");
        else el.setAttribute(k, v);
      });
    }
    append(el, kids);
    return el;
  }
  function append(el, kids) {
    kids.forEach(function (k) {
      if (k === null || k === undefined || k === false) return;
      if (Array.isArray(k)) append(el, k);
      else if (k instanceof Node) el.appendChild(k);
      else el.appendChild(document.createTextNode(String(k)));
    });
  }
  IG.h = h;
  IG.clear = function (el) { while (el.firstChild) el.removeChild(el.firstChild); return el; };
  IG.md = function (text) {
    var d = h("div", { class: "md" });
    d.innerHTML = window.IGmd.render(text); // escaped inside
    d.querySelectorAll("[data-copy]").forEach(function (b) {
      b.addEventListener("click", function () {
        var code = b.parentNode.querySelector("code");
        IG.copy(code ? code.textContent : "");
      });
    });
    return d;
  };
  IG.copy = function (text) {
    var done = function () { IG.toast("Copied"); };
    if (navigator.clipboard && navigator.clipboard.writeText) {
      navigator.clipboard.writeText(text).then(done, function () { fallback(); });
    } else fallback();
    function fallback() {
      var t = h("textarea", { style: { position: "fixed", opacity: "0" } }); t.value = text;
      document.body.appendChild(t); t.select();
      try { document.execCommand("copy"); done(); } catch (e) { IG.toast("Copy failed", "bad"); }
      t.remove();
    }
  };

  /* ---------------- formatting */
  IG.n = function (x, digits) {
    if (x === null || x === undefined || x === "" || isNaN(+x)) return "–";
    return (+x).toLocaleString(undefined, { maximumFractionDigits: digits === undefined ? 0 : digits });
  };
  IG.pct = function (x, digits) {
    if (x === null || x === undefined || x === "" || isNaN(+x)) return "–";
    return (+x * 100).toLocaleString(undefined, { maximumFractionDigits: digits === undefined ? 2 : digits }) + "%";
  };
  IG.compact = function (x) {
    if (x === null || x === undefined || x === "" || isNaN(+x)) return "–";
    x = +x;
    if (Math.abs(x) >= 1e6) return (x / 1e6).toFixed(x >= 1e7 ? 0 : 1).replace(/\.0$/, "") + "M";
    if (Math.abs(x) >= 1e4) return (x / 1e3).toFixed(x >= 1e5 ? 0 : 1).replace(/\.0$/, "") + "K";
    return x.toLocaleString();
  };
  IG.date = function (iso) {
    if (!iso) return "–";
    var d = new Date(iso.length <= 10 ? iso + "T12:00:00" : iso);
    if (isNaN(d)) return iso;
    return d.toLocaleDateString(undefined, { day: "numeric", month: "short" });
  };
  IG.cap = function (s) { s = String(s || ""); return s.charAt(0).toUpperCase() + s.slice(1); };

  /* ---------------- toasts */
  IG.toast = function (msg, kind) {
    var t = h("div", { class: "toast" + (kind ? " " + kind : ""), text: msg });
    document.getElementById("toasts").appendChild(t);
    setTimeout(function () { t.remove(); }, kind === "bad" ? 6000 : 2800);
  };
  IG.fail = function (e) { IG.toast((e && e.message) || String(e), "bad"); };

  /* ---------------- API */
  IG.api = function (path, opts) {
    opts = opts || {};
    var o = { method: opts.method || (opts.body !== undefined ? "POST" : "GET"), headers: { "X-IG-Token": IG.token || "" } };
    if (opts.body !== undefined) { o.headers["Content-Type"] = "application/json"; o.body = JSON.stringify(opts.body); }
    return fetch(path, o).catch(function () {
      throw new Error("Can't reach IG Studio. Start it again from the launcher.");
    }).then(function (r) {
      return r.json().catch(function () { return null; }).then(function (data) {
        if (!r.ok) {
          var err = new Error((data && data.error) || ("Request failed (" + r.status + ")"));
          err.status = r.status; err.data = data;
          if (r.status === 401) IG.showAuthError();
          throw err;
        }
        return data;
      });
    });
  };
  IG.get = function (p) { return IG.api(p); };
  IG.post = function (p, b) { return IG.api(p, { body: b || {} }); };
  IG.q = function (obj) {
    return Object.keys(obj).filter(function (k) { return obj[k] !== undefined && obj[k] !== null && obj[k] !== ""; })
      .map(function (k) { return encodeURIComponent(k) + "=" + encodeURIComponent(obj[k]); }).join("&");
  };

  IG.upload = function (file, kind, onProgress) {
    return new Promise(function (resolve, reject) {
      var x = new XMLHttpRequest();
      x.open("POST", "/api/upload?" + IG.q({ kind: kind, name: file.name || ("pasted-" + Date.now() + ".png") }));
      x.setRequestHeader("X-IG-Token", IG.token || "");
      if (x.upload && onProgress) x.upload.onprogress = function (e) { if (e.lengthComputable) onProgress(e.loaded / e.total); };
      x.onload = function () {
        var d = null; try { d = JSON.parse(x.responseText); } catch (e) { /* empty */ }
        if (x.status >= 200 && x.status < 300) resolve(d); else reject(new Error((d && d.error) || "Upload failed (" + x.status + ")"));
      };
      x.onerror = function () { reject(new Error("Upload failed. Is IG Studio still running?")); };
      x.send(file);
    });
  };

  /* Stream a job's events (SSE over fetch so the token goes in a header). */
  IG.stream = function (id, onEvent) {
    var last = -1, stopped = false, ctrl = null;
    var done = (async function () {
      var tries = 0;
      while (!stopped) {
        ctrl = new AbortController();
        var ended = false;
        try {
          var r = await fetch("/api/jobs/" + id + "/events?from=" + (last + 1), { headers: { "X-IG-Token": IG.token }, signal: ctrl.signal });
          if (!r.ok) { onEvent({ type: "end", status: "error", error: "Lost track of this job (" + r.status + ")." }); return; }
          var reader = r.body.getReader(), dec = new TextDecoder(), buf = "";
          for (;;) {
            var chunk = await reader.read();
            if (chunk.done) break;
            buf += dec.decode(chunk.value, { stream: true });
            var idx;
            while ((idx = buf.indexOf("\n\n")) >= 0) {
              var block = buf.slice(0, idx); buf = buf.slice(idx + 2);
              var data = block.split("\n").filter(function (l) { return l.indexOf("data: ") === 0; }).map(function (l) { return l.slice(6); }).join("\n");
              if (!data) continue;
              var ev; try { ev = JSON.parse(data); } catch (e) { continue; }
              last = ev.seq; tries = 0;
              try { onEvent(ev); } catch (e) { console.error(e); }
              if (ev.type === "end") ended = true;
            }
          }
        } catch (e) { if (stopped) return; }
        if (ended || stopped) return;
        if (++tries > 30) { onEvent({ type: "end", status: "error", error: "Lost the connection to IG Studio." }); return; }
        await new Promise(function (res) { setTimeout(res, 1000); });
      }
    })();
    return {
      done: done,
      stop: function () { stopped = true; if (ctrl) ctrl.abort(); },
      cancel: function () { return IG.post("/api/jobs/" + id + "/cancel"); }
    };
  };

  /* Run a job and render a compact progress panel into `box`. Resolves with the result data. */
  IG.runJob = function (startPromise, box, opts) {
    opts = opts || {};
    IG.clear(box);
    var bar = h("div", { class: "progress indet" }, h("i"));
    var label = h("span", { class: "small muted", text: opts.label || "Working…" });
    var log = h("div", { class: "log", hidden: !opts.showLog });
    var cancelBtn = h("button", { class: "btn sm ghost", type: "button", text: "Cancel" });
    var t0 = Date.now();
    var timer = h("span", { class: "small faint num" });
    var tick = setInterval(function () { timer.textContent = Math.round((Date.now() - t0) / 1000) + "s"; }, 1000);
    box.appendChild(h("div", { class: "stack-sm" }, h("div", { class: "row between" }, h("div", { class: "row" }, h("span", { class: "spin" }), label, timer), cancelBtn), bar, log));
    return startPromise.then(function (res) {
      return new Promise(function (resolve, reject) {
        var s = IG.stream(res.job, function (ev) {
          if (ev.type === "log") {
            log.hidden = false;
            log.appendChild(document.createTextNode(ev.line + "\n"));
            log.scrollTop = log.scrollHeight;
            if (opts.onLog) opts.onLog(ev.line, label);
          } else if (ev.type === "result") {
            box._result = ev.data;
          } else if (ev.type === "end") {
            clearInterval(tick);
            if (ev.status === "done") { IG.clear(box); resolve(box._result || ev.result || {}); }
            else {
              IG.clear(box);
              var msg = ev.status === "cancelled" ? "Cancelled." : (ev.error || "It failed.");
              box.appendChild(h("div", { class: "note " + (ev.status === "cancelled" ? "" : "bad") }, IG.icon("alert"), h("div", { class: "pre" }, msg)));
              if (log.textContent && ev.status !== "cancelled") box.appendChild(h("details", { class: "more" }, h("summary", { text: "Show log" }), h("div", { class: "log", text: log.textContent })));
              var err = new Error(msg); err.handled = true; reject(err);
            }
          }
        });
        cancelBtn.addEventListener("click", function () { cancelBtn.disabled = true; s.cancel().catch(IG.fail); });
      });
    }, function (e) { clearInterval(tick); IG.clear(box); throw e; });
  };

  /* ---------------- forms */
  IG.field = function (label, control, hint, cls) {
    var id = control.id || ("f" + Math.random().toString(36).slice(2, 9));
    control.id = id;
    return h("div", { class: "field" + (cls ? " " + cls : "") },
      h("label", { for: id, text: label }), control, hint ? h("span", { class: "hint", text: hint }) : null);
  };
  IG.input = function (name, attrs) {
    attrs = Object.assign({ type: "text", name: name }, attrs || {});
    return h("input", attrs);
  };
  IG.select = function (name, options, value, attrs) {
    var s = h("select", Object.assign({ name: name }, attrs || {}));
    options.forEach(function (o) {
      var v = Array.isArray(o) ? o[0] : o, l = Array.isArray(o) ? o[1] : o;
      s.appendChild(h("option", { value: v, text: l }));
    });
    if (value !== undefined && value !== null) s.value = value;
    return s;
  };
  IG.textarea = function (name, attrs) { return h("textarea", Object.assign({ name: name }, attrs || {})); };
  IG.formData = function (form) {
    var out = {};
    form.querySelectorAll("input[name], select[name], textarea[name]").forEach(function (el) {
      if (el.type === "checkbox") out[el.name] = el.checked;
      else if (el.type === "radio") { if (el.checked) out[el.name] = el.value; }
      else out[el.name] = el.value.trim();
    });
    return out;
  };
  IG.busy = function (btn, fn) {
    if (btn.disabled) return Promise.resolve();
    var old = Array.prototype.slice.call(btn.childNodes);
    btn.disabled = true;
    btn.insertBefore(h("span", { class: "spin" }), btn.firstChild);
    return Promise.resolve().then(fn).catch(function (e) { if (!e || !e.handled) IG.fail(e); }).finally(function () {
      btn.disabled = false;
      IG.clear(btn); old.forEach(function (n) { btn.appendChild(n); });
    });
  };
  IG.btn = function (label, opts) {
    opts = opts || {};
    var b = h("button", { type: opts.type || "button", class: "btn" + (opts.cls ? " " + opts.cls : ""), title: opts.title || null, "aria-label": opts.aria || null },
      opts.icon ? IG.icon(opts.icon) : null, label ? h("span", { text: label }) : null);
    if (opts.onClick) b.addEventListener("click", function (e) { var r = opts.onClick(e, b); if (r && r.then && opts.busy !== false) IG.busy(b, function () { return r; }); });
    return b;
  };
  IG.seg = function (options, value, onChange, label) {
    var wrap = h("div", { class: "seg", role: "group", "aria-label": label || null });
    options.forEach(function (o) {
      var b = h("button", { type: "button", "aria-pressed": String(o[0] === value), text: o[1] });
      b.addEventListener("click", function () {
        wrap.querySelectorAll("button").forEach(function (x) { x.setAttribute("aria-pressed", "false"); });
        b.setAttribute("aria-pressed", "true");
        onChange(o[0]);
      });
      wrap.appendChild(b);
    });
    return wrap;
  };
  IG.card = function (title, sub, body, actions) {
    return h("section", { class: "card" },
      (title || actions) ? h("div", { class: "card-h" }, h("div", null, title ? h("h2", { text: title }) : null, sub ? h("div", { class: "sub", text: sub }) : null), actions || null) : null,
      body);
  };
  IG.stat = function (k, v, d, dcls) {
    return h("div", { class: "stat" }, h("div", { class: "k", text: k }), h("div", { class: "v" + (String(v).length > 10 ? " sm" : ""), text: v }), d ? h("div", { class: "d" + (dcls ? " " + dcls : ""), text: d }) : null);
  };
  IG.note = function (kind, text, extra) {
    return h("div", { class: "note " + (kind || "") }, IG.icon(kind === "bad" || kind === "warn" ? "alert" : "info"), h("div", { class: "grow" }, typeof text === "string" ? h("div", { text: text }) : text, extra || null));
  };
  IG.loading = function (text) {
    return h("div", { class: "row muted small", style: { padding: "16px 0" } }, h("span", { class: "spin" }), text || "Loading…");
  };
  IG.errorBox = function (e, retry) {
    return IG.note("bad", (e && e.message) || String(e), retry ? h("div", { style: { marginTop: "8px" } }, IG.btn("Try again", { cls: "sm", onClick: retry })) : null);
  };

  /* ---------------- dialog */
  IG.dialog = function (title, body, actions) {
    var d = h("dialog", { "aria-label": title });
    var close = function () { d.close(); d.remove(); };
    var foot = h("div", { class: "dlg-f" });
    (actions || [{ label: "Close" }]).forEach(function (a) {
      var b = IG.btn(a.label, { cls: a.primary ? "primary" : (a.cls || ""), type: a.submit ? "submit" : "button" });
      b.addEventListener("click", function (e) {
        if (!a.onClick) { close(); return; }
        e.preventDefault();
        IG.busy(b, function () { return Promise.resolve(a.onClick(close)); });
      });
      foot.appendChild(b);
    });
    d.appendChild(h("div", { class: "dlg-h" }, h("h2", { text: title }), h("button", { class: "btn ghost sm", type: "button", "aria-label": "Close", onclick: close }, IG.icon("x"))));
    d.appendChild(h("div", { class: "dlg-b" }, body));
    d.appendChild(foot);
    d.addEventListener("cancel", function (e) { e.preventDefault(); close(); });
    document.body.appendChild(d);
    d.showModal();
    var first = d.querySelector(".dlg-b input, .dlg-b textarea, .dlg-b select");
    if (first) first.focus();
    return close;
  };

  /* ---------------- router */
  IG.screen = function (id, def) { IG.screens[id] = def; if (IG.order.indexOf(id) < 0) IG.order.push(id); };
  IG.go = function (id, params) {
    IG.params = params || {};
    if (location.hash !== "#" + id) { IG._skipHash = true; location.hash = id; }
    IG.render(id);
  };
  IG.alive = function (m) { return m === IG.mount; };
  IG.render = function (id) {
    if (!IG.screens[id]) id = "today";
    IG.current = id;
    var def = IG.screens[id];
    IG.mount++;
    var m = IG.mount;
    document.getElementById("page-title").textContent = def.title;
    document.title = def.title + " · IG Studio";
    document.querySelectorAll("#nav a, #tabs a").forEach(function (a) {
      if (a.dataset.id === id) a.setAttribute("aria-current", "page"); else a.removeAttribute("aria-current");
    });
    var cur = document.querySelector('#tabs a[data-id="' + id + '"]');
    if (cur && cur.scrollIntoView) cur.scrollIntoView({ block: "nearest", inline: "nearest" });
    var view = IG.clear(document.getElementById("view"));
    try {
      var r = def.render(view, IG.params || {}, m);
      if (r && r.catch) r.catch(function (e) { if (IG.alive(m)) view.appendChild(IG.errorBox(e, function () { IG.render(id); })); });
    } catch (e) { view.appendChild(IG.errorBox(e)); console.error(e); }
    IG.params = {};
  };
  IG.buildNav = function () {
    var nav = IG.clear(document.getElementById("nav")), tabs = IG.clear(document.getElementById("tabs"));
    IG.order.forEach(function (id) {
      var def = IG.screens[id];
      if (def.hidden) return;
      var a = h("a", { href: "#" + id, dataset: { id: id } }, IG.icon(def.icon || id), h("span", { text: def.title }));
      nav.appendChild(a);
      tabs.appendChild(h("a", { href: "#" + id, dataset: { id: id }, text: def.short || def.title }));
    });
  };
  IG.setBadge = function (id, n) {
    var a = document.querySelector('#nav a[data-id="' + id + '"]');
    if (!a) return;
    var b = a.querySelector(".badge-n");
    if (!n) { if (b) b.remove(); return; }
    if (!b) { b = h("span", { class: "badge-n" }); a.appendChild(b); }
    b.textContent = n;
  };

  /* ---------------- AI handoff */
  IG.ask = function (prompt, opts) {
    opts = opts || {};
    IG.pendingAsk = { prompt: prompt, send: !!opts.send, attachments: opts.attachments || [] };
    IG.go("assistant");
  };
  IG.claudeReady = function () { return !!(IG.status && IG.status.claude && IG.status.claude.found); };
  IG.installCard = function () {
    return h("section", { class: "card" },
      h("div", { class: "card-h" }, h("div", null, h("h2", { text: "Install Claude Code to use the Assistant" }),
        h("div", { class: "sub", text: "Writing scripts, captions, plans and trend research is done by Claude. Everything else in IG Studio works without it." }))),
      h("ol", { class: "small", style: { margin: "0 0 12px", paddingLeft: "20px" } },
        h("li", null, "Install it from ", h("a", { href: "https://claude.com/claude-code", target: "_blank", rel: "noopener noreferrer", text: "claude.com/claude-code" }), "."),
        h("li", { text: "Open a terminal, run claude once and log in with your Claude subscription." }),
        h("li", { text: "Quit IG Studio (Settings → Quit) and start it again." })));
  };

  /* ---------------- accounts + state */
  IG.loadStatus = function () {
    return IG.get("/api/status").then(function (s) {
      IG.status = s;
      var dot = document.getElementById("side-dot");
      dot.className = "dot" + (s.claude.found ? "" : " off");
      IG.renderInstallBanner(s.install);
      return s;
    });
  };
  /* kweo nudge: shown at startup when kweo is missing or not connected */
  var KWEO_SNOOZE = "ig.kweoNudgeSnooze";
  IG.kweoNudge = function () {
    var el = document.getElementById("kweo-banner");
    var until = 0;
    try { until = +localStorage.getItem(KWEO_SNOOZE) || 0; } catch (e) { /* storage blocked */ }
    if (Date.now() < until) return Promise.resolve();
    return IG.get("/api/kweo").then(function (k) {
      IG.kweo = k;
      IG.clear(el);
      if (k.ready) { el.hidden = true; return; }
      var installed = !!k.app;
      var msg = installed
        ? "kweo is installed but not connected yet. Connect it so IG Studio can read your Instagram without API keys."
        : "Get kweo, the free AI browser. IG Studio uses it to read your Instagram where you're already logged in, so you never need API keys.";
      var main = installed
        ? h("button", { class: "btn primary sm", type: "button", text: "Connect kweo", onclick: function () { el.hidden = true; IG.go("account"); } })
        : h("a", { class: "btn primary sm", href: "https://kweo.ai", target: "_blank", rel: "noopener noreferrer", text: "Get kweo" });
      var later = h("button", { class: "btn ghost sm", type: "button", text: "Not now", onclick: function () {
        try { localStorage.setItem(KWEO_SNOOZE, String(Date.now() + 7 * 864e5)); } catch (e) { /* storage blocked */ }
        el.hidden = true;
      } });
      el.appendChild(h("div", { class: "note info" }, h("span", { text: msg }), h("div", { class: "row-btns" }, main, later)));
      el.hidden = false;
    }).catch(function () { el.hidden = true; });
  };

  IG.renderInstallBanner = function (inst) {
    var el = IG.clear(document.getElementById("install-banner"));
    if (!inst || !inst.needed) { el.hidden = true; return; }
    var fresh = inst.missing.length && !inst.outdated.length && inst.missing.indexOf("ig") >= 0;
    var msg = fresh
      ? "IG Studio works now. Install the skills into Claude Code so the Assistant and the /ig command can use them too."
      : "A newer version of the skills came with this download (" + (inst.missing.length + inst.outdated.length) + " to update). Your current ones are backed up first.";
    var btn = h("button", { class: "btn primary sm", type: "button", text: fresh ? "Install skills" : "Update skills" });
    btn.onclick = function () {
      btn.disabled = true; btn.textContent = "Installing…";
      IG.post("/api/install-skills").then(function (r) {
        IG.toast("Installed " + r.installed.length + " skills" + (r.backup ? ". Old ones backed up." : "."), "ok");
        return IG.loadStatus();
      }).catch(function (e) {
        btn.disabled = false; btn.textContent = "Try again";
        IG.toast((e && e.message) || "Install failed", "bad");
      });
    };
    el.appendChild(h("div", { class: "note info" }, h("span", { text: msg }), btn));
    el.hidden = false;
  };
  IG.loadAccounts = function () {
    return IG.get("/api/accounts").then(function (a) {
      IG.accounts = a;
      var sel = IG.clear(document.getElementById("acct-select"));
      if (!a.accounts.length) sel.appendChild(h("option", { value: "", text: "my account" }));
      a.accounts.forEach(function (x) { sel.appendChild(h("option", { value: x.handle, text: x.handle })); });
      sel.appendChild(h("option", { value: "__new", text: "+ Add account…" }));
      sel.value = a.active || "";
      return a;
    }).catch(function (e) {
      var sel = IG.clear(document.getElementById("acct-select"));
      sel.appendChild(h("option", { value: "", text: "my account" }));
      throw e;
    });
  };
  IG.accountKey = function () { return (IG.accounts && IG.accounts.active) || "_default"; };
  IG.handle = function () {
    var a = IG.accounts && IG.accounts.active;
    if (a) return "@" + a;
    var p = IG.state && IG.state.profile;
    return (p && p.handle) ? "@" + p.handle : "your account";
  };
  IG.switchAccount = function (handle) {
    var p = handle ? IG.post("/api/accounts/use", { handle: handle }) : IG.post("/api/accounts/use", { none: true });
    return p.then(function () { IG.state = null; return IG.loadAccounts(); }).then(function () {
      if (IG.onAccountChange) IG.onAccountChange();
      IG.toast("Switched to " + (handle ? "@" + handle : "the default account"));
      IG.render(IG.current || "today");
    });
  };

  IG.showAuthError = function () {
    if (IG._authShown) return;
    IG._authShown = true;
    var view = IG.clear(document.getElementById("view"));
    view.appendChild(h("div", { class: "card", style: { maxWidth: "560px" } },
      h("h2", { text: "Open IG Studio from its launcher" }),
      h("p", { class: "muted", style: { marginTop: "8px" } , text: "This page needs the private link IG Studio opens for you. Double-click the IG Studio launcher again; it will open the right page (or reuse the running one)." })));
  };
})();
