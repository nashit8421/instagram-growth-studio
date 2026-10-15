/* Boot. Normally the launcher opens /open?t=..., the server sets a cookie and
   redirects to a clean URL. Older links with #t=TOKEN still work: the token is
   kept in sessionStorage and the hash is cleared. */
(function () {
  "use strict";
  // Returns the tab named in the hash, after taking any token out of it.
  function readHash() {
    var raw = location.hash.replace(/^#/, "");
    var tab = raw || null;
    if (raw.indexOf("=") >= 0) {
      var hp = new URLSearchParams(raw);
      var t = hp.get("t");
      if (t) { IG.token = t; try { sessionStorage.setItem("igt", t); } catch (e) { /* private mode */ } }
      tab = hp.get("tab");
      history.replaceState(null, "", location.pathname + location.search + (tab ? "#" + tab : ""));
    }
    return tab;
  }
  var tab = readHash();
  try { IG.token = IG.token || sessionStorage.getItem("igt"); } catch (e) { /* private mode */ }

  IG.buildNav();
  window.addEventListener("hashchange", function () {
    if (IG._skipHash) { IG._skipHash = false; return; }
    IG.render(readHash() || "today");
  });
  document.getElementById("acct-select").addEventListener("change", function (e) {
    var v = e.target.value;
    if (v === "__new") { e.target.value = (IG.accounts && IG.accounts.active) || ""; IG.go("settings"); return; }
    if (IG.chat && IG.chat.running) { IG.toast("Wait for Claude to finish before switching accounts.", "bad"); e.target.value = (IG.accounts && IG.accounts.active) || ""; return; }
    IG.switchAccount(v || null).catch(IG.fail);
  });

  // No token in the page is fine: the cookie from /open authenticates.
  Promise.all([IG.loadStatus(), IG.loadAccounts().catch(function () { return null; })]).then(function () {
    IG.render(tab || "today");
    IG.kweoNudge();
  }).catch(function (e) {
    if (e.status !== 401) {
      var v = IG.clear(document.getElementById("view"));
      v.appendChild(IG.errorBox(e, function () { location.reload(); }));
    }
  });
})();
