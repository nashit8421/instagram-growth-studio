/* Boot: read the token from the #hash, keep it in sessionStorage, clear the hash. */
(function () {
  "use strict";
  var raw = location.hash.replace(/^#/, "");
  var tab = null;
  if (raw.indexOf("=") >= 0) {
    var hp = new URLSearchParams(raw);
    if (hp.get("t")) { try { sessionStorage.setItem("igt", hp.get("t")); } catch (e) { IG.token = hp.get("t"); } }
    tab = hp.get("tab");
  } else if (raw) tab = raw;
  try { IG.token = IG.token || sessionStorage.getItem("igt"); } catch (e) { /* private mode */ }
  history.replaceState(null, "", location.pathname + location.search + (tab ? "#" + tab : ""));

  IG.buildNav();
  window.addEventListener("hashchange", function () {
    if (IG._skipHash) { IG._skipHash = false; return; }
    IG.render(location.hash.replace(/^#/, "") || "today");
  });
  document.getElementById("acct-select").addEventListener("change", function (e) {
    var v = e.target.value;
    if (v === "__new") { e.target.value = (IG.accounts && IG.accounts.active) || ""; IG.go("settings"); return; }
    if (IG.chat && IG.chat.running) { IG.toast("Wait for Claude to finish before switching accounts.", "bad"); e.target.value = (IG.accounts && IG.accounts.active) || ""; return; }
    IG.switchAccount(v || null).catch(IG.fail);
  });

  if (!IG.token) { IG.showAuthError(); return; }
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
