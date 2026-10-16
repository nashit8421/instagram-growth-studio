/* Settings: accounts, system checks, kweo, data folder, quit. */
(function () {
  "use strict";
  var h = IG.h;

  function item(ok, title, detail, action) {
    return h("div", { class: "status-item" },
      h("span", { class: "ic " + (ok ? "ok" : "bad") }, IG.icon(ok ? "check" : "alert")),
      h("div", null, h("div", { class: "t", text: title }), detail ? (typeof detail === "string" ? h("div", { class: "d", text: detail }) : detail) : null),
      action || h("span"));
  }

  function accountsCard() {
    var a = IG.accounts || { accounts: [] };
    var input = IG.input("handle", { placeholder: "newhandle", autocomplete: "off", spellcheck: "false" });
    var form = h("form", { class: "row", style: { alignItems: "flex-end" } },
      h("div", { style: { flex: "1 1 200px", maxWidth: "280px" } }, IG.field("Add an account (yours or a client's)", input)),
      IG.btn("Add and switch", { cls: "primary", type: "submit" }),
      h("span", { class: "small muted", style: { flexBasis: "100%" }, text: "Each account keeps its own voice, posts, brand and plan in its own folder." }));
    form.addEventListener("submit", function (e) {
      e.preventDefault();
      var v = input.value.trim().replace(/^@/, "");
      if (!v) { input.focus(); return; }
      IG.busy(form.querySelector("button"), function () {
        return IG.post("/api/accounts/new", { handle: v }).then(function () { return IG.loadAccounts(); }).then(function () {
          IG.state = null; if (IG.onAccountChange) IG.onAccountChange(); IG.toast("Added @" + v); IG.go("week");
        });
      });
    });
    var rows = a.accounts.map(function (x) {
      return h("div", { class: "row between", style: { padding: "10px 0", borderTop: "1px solid var(--border)" } },
        h("div", { class: "grow" }, h("b", { text: "@" + x.handle }), x.active ? h("span", { class: "badge ok", style: { marginLeft: "8px" }, text: "active" }) : null,
          h("div", { class: "small muted ellipsis", text: x.path })),
        x.active ? null : IG.btn("Switch", { cls: "sm", onClick: function () { return IG.switchAccount(x.handle); } }));
    });
    if (!a.accounts.length) rows.push(h("p", { class: "muted small", text: "One account, stored in " + (a.data_dir || "the default folder") + ". Add an account to manage more than one." }));
    if (a.accounts.length && a.active) rows.push(h("div", { style: { paddingTop: "8px" } }, h("button", { class: "link-btn small", type: "button", text: "Use the single default folder instead", onclick: function () { IG.switchAccount(null).catch(IG.fail); } })));
    return IG.card("Accounts", null, h("div", { class: "stack-sm" }, h("div", null, rows), form));
  }

  IG.screen("settings", {
    title: "Settings", icon: "settings", hidden: true,
    render: function (view, params, m) {
      view.classList.add("stack");
      view.appendChild(IG.loading());
      return Promise.all([IG.loadStatus(), IG.loadAccounts().catch(function () { return null; })]).then(function () {
        if (!IG.alive(m)) return;
        IG.clear(view);
        var s = IG.status;
        view.appendChild(h("div", { class: "page-h" }, h("h1", { text: "Settings" })));
        view.appendChild(accountsCard());
        var profBox = h("div", null, IG.loading());
        view.appendChild(IG.card("About " + IG.handle(), "Claude fills these from the scan. Change them only if they're wrong.", profBox));
        IG.get("/api/state?quick=1").then(function (st) {
          IG.state = st;
          IG.clear(profBox).appendChild(IG.profileForm(st.profile || {}, function () { IG.state = null; }));
        }).catch(function (e) { IG.clear(profBox).appendChild(IG.errorBox(e)); });
        view.appendChild(IG.card("Tools", "For doing a step by hand. Claude uses the same tools when it prepares your week.",
          h("div", { class: "chips" }, [["hooks", "Hook scorer"], ["beats", "Script timer"], ["caption", "Caption checker"], ["human", "Humanizer"], ["carousel", "Carousel maker"], ["video", "Video editor"]].map(function (t) {
            return h("a", { class: "chip", href: IG.hashFor("tools", { tool: t[0] }), text: t[1] });
          }))));

        var kweoBox = h("div", { class: "d" }, h("span", { class: "spin", style: { width: "12px", height: "12px" } }));
        var kweoItemWrap = h("div");
        var checks = h("div", { class: "status-list" },
          item(s.claude.found, "Claude Code", s.claude.found ? (s.claude.version || "installed") + " · " + s.claude.path : h("div", { class: "d" }, "Needed for the Assistant. Install from ", h("a", { href: "https://claude.com/claude-code", target: "_blank", rel: "noopener noreferrer", text: "claude.com/claude-code" }), ", run claude once to log in, then restart IG Studio.")),
          kweoItemWrap,
          item(!!s.ffmpeg, "ffmpeg", s.ffmpeg || "Needed for the video editor. Mac: brew install ffmpeg · Windows: winget install ffmpeg · Linux: your package manager."),
          item(!!s.whisper, "Whisper (optional)", s.whisper || "For word-timed captions. Mac: brew install whisper-cpp. Without it, captions come from your script."),
          item(!!s.chrome, "Chrome", s.chrome || "Needed to render carousel and story images. Install Google Chrome, or set CHROME_PATH."),
          item(s.skills.found, "ig skills", s.skills.found ? s.skills.list.length + " skills in " + s.skills.dir : "Not found in " + s.skills.dir + ". Install the skill pack, or set IG_SKILLS_DIR."),
          item(true, "Python", s.python + " · IG Studio " + s.version));
        kweoItemWrap.appendChild(item(false, "kweo browser", kweoBox));
        view.appendChild(IG.card("System checks", "What IG Studio found on this computer", checks,
          IG.btn("Re-check", { cls: "sm", icon: "refresh", onClick: function () { s.claude.version = null; IG.render("settings"); } })));
        IG.get("/api/kweo").then(function (k) {
          IG.clear(kweoItemWrap).appendChild(item(!!k.ready, "kweo browser",
            h("div", { class: "stack-sm" }, h("div", { class: "d", text: IG.kweoText(k) }),
              !k.ready && k.app && (k.server === "auth" || k.server === "open") ? IG.kweoConnectBox() : null)));
        }).catch(function (e) { IG.clear(kweoItemWrap).appendChild(item(false, "kweo browser", e.message)); });

        view.appendChild(IG.card("Your data", "Everything IG Studio and the skills write lives here, on this computer.",
          h("div", { class: "stack-sm" },
            h("dl", { class: "kv" }, h("dt", { text: "Active folder" }), h("dd", { class: "mono", text: s.data_dir }), h("dt", { text: "Home" }), h("dd", { class: "mono", text: s.ig_home })),
            h("div", null, IG.btn("Open folder", { icon: "folder", onClick: function () { return IG.post("/api/open-folder"); } })))));

        view.appendChild(IG.card("Privacy", null, h("ul", { class: "small", style: { margin: 0, paddingLeft: "18px" } },
          h("li", { text: "IG Studio runs only on this computer (127.0.0.1) and needs the private link its launcher opens." }),
          h("li", { text: "Nothing is ever posted, liked, followed, commented or sent. You post." }),
          h("li", { text: "Only Claude talks to the internet, when you ask it to (research, your calendar after you say yes)." }))));

        view.appendChild(IG.card("Stop IG Studio", "Stops the local server. Open it again with the launcher.", IG.btn("Quit IG Studio", { cls: "danger", onClick: function () {
          IG.dialog("Quit IG Studio?", h("p", { text: "Any running Claude reply or video export will stop." }), [{ label: "Cancel" }, { label: "Quit", primary: true, onClick: function (close) {
            return IG.post("/api/quit").then(function () {
              close();
              var v = IG.clear(document.getElementById("view"));
              v.appendChild(h("div", { class: "card", style: { maxWidth: "520px" } }, h("h2", { text: "IG Studio has stopped" }), h("p", { class: "muted", style: { marginTop: "8px" }, text: "You can close this tab. Double-click the launcher to start it again." })));
            });
          } }]);
        } })));
      });
    }
  });
})();
