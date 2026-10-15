/* Growth: follower check-ins, chart, report, this week's plan, milestones. */
(function () {
  "use strict";
  var h = IG.h;
  var NS = "http://www.w3.org/2000/svg";
  function s(tag, attrs, text) {
    var el = document.createElementNS(NS, tag);
    Object.keys(attrs || {}).forEach(function (k) { el.setAttribute(k, attrs[k]); });
    if (text !== undefined) el.textContent = text;
    return el;
  }
  function niceStep(range) {
    var raw = range / 4, mag = Math.pow(10, Math.floor(Math.log10(raw || 1)));
    var n = raw / mag;
    return (n <= 1 ? 1 : n <= 2 ? 2 : n <= 5 ? 5 : 10) * mag;
  }

  IG.lineChart = function (points, width) {
    var W = Math.max(320, Math.round(width || 720)), H = W < 560 ? 210 : 250, L = 52, R = 56, T = 16, B = 30;
    var svg = s("svg", { viewBox: "0 0 " + W + " " + H, role: "img", "aria-label": "Followers over time: " + points.map(function (p) { return p.date + " " + p.followers; }).join(", ") });
    if (points.length < 1) return svg;
    var xs = points.map(function (p) { return new Date(p.date + "T12:00:00").getTime(); });
    var ys = points.map(function (p) { return p.followers; });
    var x0 = Math.min.apply(null, xs), x1 = Math.max.apply(null, xs);
    if (x1 === x0) { x0 -= 86400000 * 3; x1 += 86400000 * 3; }
    var lo = Math.min.apply(null, ys), hi = Math.max.apply(null, ys);
    var pad = Math.max(1, (hi - lo) * 0.12);
    var step = niceStep((hi - lo) + 2 * pad || 10);
    var y0 = Math.floor((lo - pad) / step) * step, y1 = Math.ceil((hi + pad) / step) * step;
    if (y0 < 0) y0 = 0;
    var X = function (t) { return L + (t - x0) / (x1 - x0) * (W - L - R); };
    var Y = function (v) { return T + (1 - (v - y0) / (y1 - y0 || 1)) * (H - T - B); };
    for (var v = y0; v <= y1 + 1e-9; v += step) {
      svg.appendChild(s("line", { x1: L, x2: W - R, y1: Y(v), y2: Y(v), class: "grid-l" }));
      svg.appendChild(s("text", { x: L - 8, y: Y(v) + 4, "text-anchor": "end", class: "axis-t" }, IG.compact(v)));
    }
    var nLabels = Math.min(points.length, 5);
    for (var i = 0; i < nLabels; i++) {
      var idx = nLabels === 1 ? 0 : Math.round(i * (points.length - 1) / (nLabels - 1));
      svg.appendChild(s("text", { x: X(xs[idx]), y: H - 8, "text-anchor": i === 0 ? "start" : i === nLabels - 1 ? "end" : "middle", class: "axis-t" }, IG.date(points[idx].date)));
    }
    var d = points.map(function (p, i) { return (i ? "L" : "M") + X(xs[i]).toFixed(1) + " " + Y(p.followers).toFixed(1); }).join(" ");
    svg.appendChild(s("path", { d: d + " L" + X(xs[xs.length - 1]).toFixed(1) + " " + (H - B) + " L" + X(xs[0]).toFixed(1) + " " + (H - B) + " Z", class: "area" }));
    svg.appendChild(s("path", { d: d, class: "line" }));
    points.forEach(function (p, i) {
      var last = i === points.length - 1;
      var c = s("circle", { cx: X(xs[i]), cy: Y(p.followers), r: last ? 4.5 : 3, class: last ? "pt pt-last" : "pt" });
      c.appendChild(s("title", {}, IG.date(p.date) + ": " + IG.n(p.followers)));
      svg.appendChild(c);
    });
    var lp = points[points.length - 1];
    svg.appendChild(s("text", { x: X(xs[xs.length - 1]) + 8, y: Y(lp.followers) + 4, class: "lbl" }, IG.compact(lp.followers)));
    return svg;
  };

  function actionFor(a) {
    var sk = (a.skill || "").split(" ")[0];
    if (sk === "/ig-calendar") return function () { IG.go("calendar"); };
    if (sk === "/ig-edit") return function () { IG.go("create", { tool: "video" }); };
    return function () { IG.ask(sk + " " + a.action + ". (From my weekly growth plan: " + a.why + ")"); };
  }

  IG.screen("growth", {
    title: "Growth", icon: "growth",
    render: function (view, params, m) {
      view.classList.add("stack");
      var top = h("div", { class: "grid-2", style: { alignItems: "start" } });
      var chartCard = h("section", { class: "card chart" });
      var reportBox = h("div", { class: "stack" });
      view.appendChild(top);
      view.appendChild(chartCard);
      view.appendChild(reportBox);
      var reload = function () { IG.render("growth"); };
      top.appendChild(IG.card("Follower check-in", "Once a week is enough. Same day each week reads best.", IG.followersForm(reload, { label: "Followers today", submitLabel: "Log" })));
      var statBox = h("div", { class: "stats two" });
      top.appendChild(statBox);
      chartCard.appendChild(IG.loading());
      reportBox.appendChild(IG.loading());
      return Promise.all([IG.get("/api/grow/series"), IG.get("/api/grow/report").catch(function (e) { return { _err: e }; }),
        IG.get("/api/grow/plan").catch(function () { return null; }), IG.get("/api/grow/milestones").catch(function () { return { milestones: [] }; })]).then(function (res) {
        if (!IG.alive(m)) return;
        var pts = res[0].points, rep = res[1], plan = res[2], miles = res[3].milestones;
        IG.clear(chartCard);
        var f = rep && rep.followers || {};
        var g = f.growth || {};
        var weekly = f.weekly || [];
        var lastWeek = weekly.length ? weekly[weekly.length - 1] : null;
        statBox.appendChild(IG.stat("Followers", IG.n(f.current != null ? f.current : (pts.length ? pts[pts.length - 1].followers : null)), pts.length ? "last check " + IG.date(pts[pts.length - 1].date) : "no check-ins yet"));
        statBox.appendChild(IG.stat("Last 7 days", lastWeek != null ? (lastWeek >= 0 ? "+" : "") + IG.n(lastWeek) : "–", f.trend ? "trend " + f.trend : null, f.trend === "down" ? "down" : "up"));
        statBox.appendChild(IG.stat("Last " + ((rep && rep.weeks) || 4) + " weeks", g.net != null ? (g.net >= 0 ? "+" : "") + IG.n(g.net) : "–", g.rate_pct != null ? IG.n(g.rate_pct, 1) + "% growth" : null, g.net >= 0 ? "up" : "down"));
        statBox.appendChild(IG.stat("Posts / week", rep && rep.signals ? IG.n(rep.signals.posts_per_week, 1) : "–", "floor is 3"));
        chartCard.appendChild(h("div", { class: "card-h" }, h("div", null, h("h2", { text: "Followers" }), h("div", { class: "sub", text: pts.length + " check-ins" }))));
        if (pts.length >= 2) chartCard.appendChild(IG.lineChart(pts, chartCard.clientWidth - 42));
        else chartCard.appendChild(h("div", { class: "empty" }, h("p", { text: pts.length ? "One check-in so far. The line starts with the second." : "Log your followers above to start the chart." })));

        IG.clear(reportBox);
        if (rep && rep._err) { reportBox.appendChild(IG.errorBox(rep._err)); return; }
        var bn = rep && rep.bottleneck;
        if (bn) {
          reportBox.appendChild(h("section", { class: "card", style: { borderColor: "var(--accent)" } },
            h("div", { class: "card-h" }, h("div", null, h("div", { class: "small muted", text: "This week's bottleneck" }), h("h2", { style: { fontSize: "22px", marginTop: "2px" }, text: IG.cap(bn.name) })),
              bn.early ? h("span", { class: "badge warn", text: "early read, few posts" }) : null),
            h("p", { text: bn.reason }),
            h("div", { class: "row", style: { marginTop: "10px" } }, IG.btn("Weekly review with Claude", { icon: "assistant", onClick: function () { IG.ask("/ig-grow Run my weekly growth review. I already logged today's followers if the chart shows today."); } }))));
        }
        if (plan && plan.actions && plan.actions.length) {
          reportBox.appendChild(IG.card("This week's plan", "Ranked. Do the first ones first.", h("div", { class: "steps" }, plan.actions.map(function (a, i) {
            return h("div", { class: "step" + (i === 0 ? " first" : "") }, h("div", { class: "n", text: String(i + 1) }),
              h("div", null, h("div", { class: "t" }, a.action), h("div", { class: "why" }, a.why, " ", h("span", { class: "badge", text: a.skill }))),
              IG.btn("Do this", { cls: i === 0 ? "primary" : "", onClick: actionFor(a) }));
          }))));
        }
        var reached = (miles || []).filter(function (x) { return x.date; });
        reportBox.appendChild(IG.card("Milestones", null, reached.length ? h("div", { class: "chips" }, reached.map(function (x) {
          return h("span", { class: "badge ok", style: { fontSize: "13px", padding: "5px 12px" }, text: IG.compact(x.milestone) + (x.before_tracking ? " · before tracking" : " · " + IG.date(x.date)) });
        })) : h("p", { class: "muted", text: "Your first milestone shows up here." })));
      });
    }
  });
})();
