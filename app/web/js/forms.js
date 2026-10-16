/* Small shared forms: profile settings, a follower check-in, screenshots for Claude. */
(function () {
  "use strict";
  var h = IG.h;

  IG.COUNTRIES = [["US", "United States"], ["IN", "India"], ["GB", "United Kingdom"], ["CA", "Canada"], ["AU", "Australia"],
    ["NZ", "New Zealand"], ["IE", "Ireland"], ["DE", "Germany"], ["FR", "France"], ["ES", "Spain"], ["IT", "Italy"],
    ["NL", "Netherlands"], ["SE", "Sweden"], ["PL", "Poland"], ["PT", "Portugal"], ["BR", "Brazil"], ["MX", "Mexico"],
    ["AR", "Argentina"], ["CO", "Colombia"], ["AE", "United Arab Emirates"], ["SA", "Saudi Arabia"], ["EG", "Egypt"],
    ["TR", "Türkiye"], ["PK", "Pakistan"], ["BD", "Bangladesh"], ["LK", "Sri Lanka"], ["NP", "Nepal"], ["ID", "Indonesia"],
    ["PH", "Philippines"], ["MY", "Malaysia"], ["SG", "Singapore"], ["TH", "Thailand"], ["VN", "Vietnam"], ["JP", "Japan"],
    ["KR", "South Korea"], ["NG", "Nigeria"], ["KE", "Kenya"], ["ZA", "South Africa"], ["GH", "Ghana"]];
  var LANGS = [["en", "English"], ["hinglish", "Hinglish"], ["hi", "Hindi"], ["es", "Spanish"], ["pt", "Portuguese"], ["fr", "French"],
    ["de", "German"], ["ar", "Arabic"], ["ur", "Urdu"], ["id", "Indonesian"], ["it", "Italian"], ["tr", "Turkish"], ["ja", "Japanese"],
    ["ko", "Korean"], ["bn", "Bengali"], ["ta", "Tamil"], ["te", "Telugu"], ["mr", "Marathi"]];

  /* Profile settings. Claude fills these on its own; this is only for corrections. */
  IG.profileForm = function (initial, onSaved, opts) {
    initial = initial || {};
    opts = opts || {};
    var reg = String(initial.region || "");
    var code = IG.COUNTRIES.filter(function (c) { return c[0] === reg.toUpperCase() || c[1].toLowerCase() === reg.toLowerCase(); })[0];
    var region = IG.select("region_pick", [["", "Choose a country…"]].concat(IG.COUNTRIES.map(function (c) { return [c[0], c[1]]; })).concat([["__other", "Somewhere else…"]]),
      code ? code[0] : (reg ? "__other" : ""));
    var other = IG.input("region_other", { placeholder: "Country or region, e.g. LATAM", value: code ? "" : reg });
    var otherField = IG.field("Region", other);
    otherField.hidden = region.value !== "__other";
    region.addEventListener("change", function () { otherField.hidden = region.value !== "__other"; if (!otherField.hidden) other.focus(); });
    var niche = IG.input("niche", { placeholder: "e.g. contracts and pricing for freelance designers", value: initial.niche || "" });
    var type = IG.select("account_type", [["creator", "Creator"], ["business", "Business"]], initial.account_type || "creator");
    var langKnown = LANGS.some(function (l) { return l[0] === String(initial.language || "").toLowerCase(); });
    var lang = IG.select("language", LANGS.concat(langKnown || !initial.language ? [] : [[initial.language, initial.language]]),
      langKnown ? String(initial.language).toLowerCase() : (initial.language || "en"));
    var goal = IG.input("goal", { placeholder: "e.g. 10k followers by March", value: initial.goal || "" });
    var form = h("form", { class: "stack-sm", novalidate: true },
      h("div", { class: "form-grid" },
        IG.field("Audience country", region), otherField,
        IG.field("Account type", type),
        IG.field("Niche, in your words", niche, null, "span-all"),
        IG.field("Language", lang),
        IG.field("Goal (optional)", goal)),
      h("div", { class: "row" }, IG.btn(opts.submitLabel || "Save", { cls: "primary", type: "submit" })));
    form.addEventListener("submit", function (e) {
      e.preventDefault();
      var r = region.value === "__other" ? other.value.trim() : region.value;
      if (!r || !niche.value.trim()) { IG.toast("Country and niche are needed.", "bad"); return; }
      IG.busy(form.querySelector("button[type=submit]"), function () {
        return IG.post("/api/profile", { region: r, niche: niche.value.trim(), account_type: type.value, language: lang.value, goal: goal.value.trim() })
          .then(function (res) { IG.toast("Saved"); if (onSaved) onSaved(res.profile); });
      });
    });
    return form;
  };

  IG.followersForm = function (onSaved, opts) {
    opts = opts || {};
    var n = IG.input("followers", { type: "number", min: "0", inputmode: "numeric", placeholder: "e.g. 1460", value: opts.value || "", required: true });
    var form = h("form", { class: "row", style: { alignItems: "flex-end" } },
      h("div", { style: { flex: "1 1 200px", maxWidth: "260px" } }, IG.field(opts.label || "Followers right now", n, opts.hint)),
      IG.btn(opts.submitLabel || "Save", { cls: "primary", type: "submit" }));
    form.addEventListener("submit", function (e) {
      e.preventDefault();
      if (n.value === "") { n.focus(); return; }
      IG.busy(form.querySelector("button"), function () {
        return IG.post("/api/grow/checkin", { followers: n.value }).then(function (res) { IG.toast("Logged " + IG.n(n.value) + " followers"); if (onSaved) onSaved(res); });
      });
    });
    return form;
  };

  /* Upload screenshots and hand them to Claude with a prompt. */
  IG.screenshotAsk = function (prompt, label) {
    var file = h("input", { type: "file", accept: "image/*", multiple: true, class: "sr", id: "shot-" + Math.random().toString(36).slice(2) });
    var status = h("span", { class: "small muted" });
    var lab = h("label", { class: "btn", for: file.id }, IG.icon("upload"), h("span", { text: label || "Upload screenshots" }));
    file.addEventListener("change", function () {
      var files = Array.prototype.slice.call(file.files || []);
      if (!files.length) return;
      if (!IG.claudeReady()) { IG.toast("Install Claude Code first (see Settings).", "bad"); return; }
      status.textContent = "Uploading…";
      Promise.all(files.map(function (f) { return IG.upload(f, "image"); })).then(function (ups) {
        status.textContent = "";
        IG.ask(prompt, { send: true, attachments: ups.map(function (u) { return { path: u.path, name: u.name, url: u.url }; }) });
      }).catch(function (e) { status.textContent = ""; IG.fail(e); });
    });
    return h("div", { class: "row" }, file, lab, status);
  };
})();
