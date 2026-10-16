/* Boot. Normally the launcher opens /open?t=..., the server sets a cookie and
   redirects to a clean URL. Older links with #t=TOKEN still work: the token is
   kept in sessionStorage and the hash is cleared. Screen links look like
   #post?w=2026-10-19&id=mon. */
(function () {
  "use strict";
  var OLD = { today: "week", calendar: "week", assistant: "week", create: "tools" };

  // Returns {id, params} from the hash, after taking any token out of it.
  function readHash() {
    var raw = location.hash.replace(/^#/, "");
    if (/(^|&)(t|tab)=/.test(raw)) {
      var hp = new URLSearchParams(raw);
      var t = hp.get("t");
      if (t) { IG.token = t; try { sessionStorage.setItem("igt", t); } catch (e) { /* private mode */ } }
      raw = hp.get("tab") || "";
      history.replaceState(null, "", location.pathname + location.search + (raw ? "#" + raw : ""));
    }
    var q = raw.indexOf("?");
    var id = q >= 0 ? raw.slice(0, q) : raw;
    var params = {};
    if (q >= 0) new URLSearchParams(raw.slice(q + 1)).forEach(function (v, k) { params[k] = v; });
    id = OLD[id] || id || "week";
    return { id: id, params: params };
  }
  var start = readHash();
  try { IG.token = IG.token || sessionStorage.getItem("igt"); } catch (e) { /* private mode */ }

  /* Re-render whatever is on screen, with the params in the address bar. */
  IG.refresh = function () { var r = readHash(); IG.params = r.params; IG.render(r.id); };

  IG.buildNav();
  window.addEventListener("hashchange", function () {
    if (IG._skipHash) { IG._skipHash = false; return; }
    var r = readHash();
    IG.params = r.params;
    IG.render(r.id);
  });
  document.getElementById("ask-btn").addEventListener("click", function () { IG.toggleChat(); });
  document.getElementById("acct-select").addEventListener("change", function (e) {
    var v = e.target.value;
    var keep = (IG.accounts && IG.accounts.active) || "";
    if (v === "__new") { e.target.value = keep; IG.go("week", { new: 1 }); return; }
    if (IG.busyWith()) { IG.toast("Wait for Claude to finish before switching accounts.", "bad"); e.target.value = keep; return; }
    IG.switchAccount(v || null).catch(IG.fail);
  });

  // No token in the page is fine: the cookie from /open authenticates.
  Promise.all([IG.loadStatus(), IG.loadAccounts().catch(function () { return null; })]).then(function () {
    IG.params = start.params;
    IG.render(start.id);
    if (/^#?assistant/.test(location.hash) || start.params.chat) IG.openChat();
  }).catch(function (e) {
    if (e.status !== 401) {
      var v = IG.clear(document.getElementById("view"));
      v.appendChild(IG.errorBox(e, function () { location.reload(); }));
    }
  });
})();
