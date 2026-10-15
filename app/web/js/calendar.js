/* Calendar: this week's plan as reminders. Nothing is ever posted. */
(function () {
  "use strict";
  var h = IG.h;
  var DAYS = ["MON", "TUE", "WED", "THU", "FRI", "SAT", "SUN"];

  function timeOf(iso) {
    var m = String(iso || "").match(/T(\d{2}):(\d{2})/);
    if (!m) return "";
    var hh = +m[1], mm = m[2], ap = hh >= 12 ? "pm" : "am";
    hh = hh % 12 || 12;
    return hh + (mm === "00" ? "" : ":" + mm) + ap;
  }

  IG.screen("calendar", {
    title: "Calendar", icon: "calendar",
    render: function (view, params, m) {
      view.classList.add("stack");
      view.appendChild(IG.loading());
      return Promise.all([IG.get("/api/calendar"), IG.get("/api/text?name=plan.md")]).then(function (res) {
        if (!IG.alive(m)) return;
        IG.clear(view);
        var cal = res[0], plan = res[1];
        if (!cal.exists) {
          view.appendChild(h("div", { class: "card empty" }, h("h3", { text: "No plan for this week yet" }),
            h("p", { text: "Claude builds the week from your trends, your growth plan and what actually happened this week." }),
            h("div", { class: "row", style: { justifyContent: "center", marginTop: "12px" } }, IG.btn("Plan my week", { cls: "primary", icon: "assistant", onClick: function () { IG.ask("/ig-plan Plan my week. What happened this week: "); } }))));
          return;
        }
        var p = cal.parsed || {};
        var evs = p.events || [];
        var weekOf = p.week_of;
        view.appendChild(h("section", { class: "card" },
          h("div", { class: "card-h" },
            h("div", null, h("h2", { text: weekOf ? "Week of " + new Date(weekOf + "T12:00:00").toLocaleDateString(undefined, { day: "numeric", month: "long" }) : "This week" }),
              h("div", { class: "sub", text: evs.length + " reminders · " + (p.time_zone || "local time") + (plan.modified ? " · plan updated " + IG.date(plan.modified.slice(0, 10)) : "") })),
            h("div", { class: "row" },
              IG.btn("Download .ics", { icon: "download", onClick: function () {
                return IG.post("/api/calendar/ics", {}).then(function (r) {
                  var a = h("a", { href: r.url, download: "" }); document.body.appendChild(a); a.click(); a.remove();
                  IG.toast(r.events + " reminders saved to ig-week.ics");
                });
              } }),
              IG.claudeReady() ? IG.btn("Add to Google Calendar", { cls: "primary", icon: "assistant", onClick: function () {
                IG.ask("/ig-calendar Add this week's plan to my Google Calendar as reminders. Show me the checklist first and ask me before creating or changing anything.", { send: true });
              } }) : null)),
          cal.error ? IG.note("bad", cal.error) : null,
          (p.warnings || []).length ? IG.note("warn", p.warnings.join(" ")) : null,
          h("div", { class: "week", style: { marginTop: "6px" } }, DAYS.map(function (d, i) {
            var date = weekOf ? new Date(new Date(weekOf + "T12:00:00").getTime() + i * 86400000) : null;
            var iso = date ? date.toISOString().slice(0, 10) : null;
            var today = iso && iso === new Date().toISOString().slice(0, 10);
            var dayEvs = evs.filter(function (e) { return iso && String(e.start).slice(0, 10) === iso; });
            return h("div", { class: "d" + (today ? " today" : "") },
              h("div", { class: "dh" }, h("span", { text: d }), h("span", { text: date ? date.getDate() : "" })),
              dayEvs.length ? dayEvs.map(function (e) {
                return h("div", { class: "ev " + e.kind, title: e.description || "" }, h("b", { text: timeOf(e.start) + " · " + e.kind }), e.summary.replace(/^IG( prep)?:\s*/, ""));
              }) : h("div", { class: "small faint", text: "rest" }));
          })),
          h("p", { class: "small muted", style: { marginTop: "12px" }, text: "Reminders only. Nothing posts automatically. You post by hand when the reminder goes off." })));
        view.appendChild(h("section", { class: "card" },
          h("div", { class: "card-h" }, h("div", null, h("h2", { text: "plan.md" }), h("div", { class: "sub", text: "Written by /ig-plan. Change it by asking Claude to replan." })),
            IG.claudeReady() ? IG.btn("Replan with Claude", { icon: "assistant", onClick: function () { IG.ask("/ig-plan Replan my week. What changed: "); } }) : null),
          h("div", { class: "planbox", text: plan.text || "" })));
      });
    }
  });
})();
