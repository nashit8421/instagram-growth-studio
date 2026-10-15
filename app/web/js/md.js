/* Minimal safe markdown: everything is HTML-escaped first, then a small
   subset of markdown is turned into tags. Links must be http(s) or mailto. */
(function () {
  "use strict";
  function esc(s) {
    return String(s).replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;").replace(/'/g, "&#39;");
  }

  function inline(s) {
    // s is already escaped. Protect code spans first.
    var codes = [];
    s = s.replace(/`([^`\n]+)`/g, function (_, c) { codes.push(c); return "\u0000" + (codes.length - 1) + "\u0000"; });
    s = s.replace(/\[([^\]\n]+)\]\(([^)\s]+)\)/g, function (m, text, url) {
      var u = url.replace(/&amp;/g, "&");
      if (!/^(https?:\/\/|mailto:)/i.test(u)) return m;
      return '<a href="' + esc(u) + '" target="_blank" rel="noopener noreferrer">' + text + "</a>";
    });
    s = s.replace(/(^|[\s(])(https?:\/\/[^\s<)]+[^\s<).,;:!?'"])/g, function (m, pre, url) {
      return pre + '<a href="' + url + '" target="_blank" rel="noopener noreferrer">' + url + "</a>";
    });
    s = s.replace(/\*\*([^*\n]+)\*\*/g, "<strong>$1</strong>");
    s = s.replace(/(^|[^*\w])\*([^*\n]+)\*(?![*\w])/g, "$1<em>$2</em>");
    s = s.replace(/(^|[^_\w])_([^_\n]+)_(?![_\w])/g, "$1<em>$2</em>");
    s = s.replace(/\u0000(\d+)\u0000/g, function (_, i) { return "<code>" + codes[+i] + "</code>"; });
    return s;
  }

  function render(src) {
    var lines = String(src || "").replace(/\r\n?/g, "\n").split("\n");
    var out = [], i = 0;
    function para(buf) { if (buf.length) out.push("<p>" + buf.map(function (l) { return inline(esc(l)); }).join("<br>") + "</p>"); }
    var buf = [];
    while (i < lines.length) {
      var line = lines[i];
      var fence = line.match(/^\s*(```|~~~)(.*)$/);
      if (fence) {
        para(buf); buf = [];
        var code = [];
        i++;
        while (i < lines.length && !lines[i].trim().startsWith(fence[1])) { code.push(lines[i]); i++; }
        i++;
        out.push('<pre><button type="button" class="btn sm copy" data-copy>Copy</button><code>' + esc(code.join("\n")) + "</code></pre>");
        continue;
      }
      if (/^\s*$/.test(line)) { para(buf); buf = []; i++; continue; }
      var hm = line.match(/^(#{1,6})\s+(.*)$/);
      if (hm) { para(buf); buf = []; var lv = Math.min(hm[1].length + 1, 4); out.push("<h" + lv + ">" + inline(esc(hm[2])) + "</h" + lv + ">"); i++; continue; }
      if (/^\s*(?:(?:-\s*){3,}|(?:\*\s*){3,}|(?:_\s*){3,})$/.test(line)) { para(buf); buf = []; out.push("<hr>"); i++; continue; }
      if (/^\s*>/.test(line)) {
        para(buf); buf = [];
        var q = [];
        while (i < lines.length && /^\s*>/.test(lines[i])) { q.push(lines[i].replace(/^\s*>\s?/, "")); i++; }
        out.push("<blockquote>" + render(q.join("\n")) + "</blockquote>");
        continue;
      }
      if (/^\s*\|.*\|\s*$/.test(line) && i + 1 < lines.length && /^\s*\|?\s*:?-{2,}/.test(lines[i + 1])) {
        para(buf); buf = [];
        var rows = [];
        while (i < lines.length && /^\s*\|.*\|\s*$/.test(lines[i])) { rows.push(lines[i]); i++; }
        var cells = function (r) { return r.trim().replace(/^\||\|$/g, "").split("|").map(function (c) { return inline(esc(c.trim())); }); };
        var head = cells(rows[0]);
        var html = "<table><thead><tr>" + head.map(function (c) { return "<th>" + c + "</th>"; }).join("") + "</tr></thead><tbody>";
        rows.slice(2).forEach(function (r) { html += "<tr>" + cells(r).map(function (c) { return "<td>" + c + "</td>"; }).join("") + "</tr>"; });
        out.push(html + "</tbody></table>");
        continue;
      }
      var lm = line.match(/^(\s*)([-*+]|\d+[.)])\s+(.*)$/);
      if (lm) {
        para(buf); buf = [];
        var ordered = /\d/.test(lm[2]);
        var items = [];
        while (i < lines.length) {
          var m2 = lines[i].match(/^(\s*)([-*+]|\d+[.)])\s+(.*)$/);
          if (m2) { items.push(m2[3]); i++; continue; }
          if (/^\s{2,}\S/.test(lines[i]) && items.length) { items[items.length - 1] += "\n" + lines[i].trim(); i++; continue; }
          break;
        }
        var tag = ordered ? "ol" : "ul";
        out.push("<" + tag + ">" + items.map(function (it) {
          var cb = it.match(/^\[( |x|X)\]\s+(.*)$/s);
          if (cb) return "<li>" + (cb[1] === " " ? "☐ " : "☑ ") + inline(esc(cb[2])).replace(/\n/g, "<br>") + "</li>";
          return "<li>" + inline(esc(it)).replace(/\n/g, "<br>") + "</li>";
        }).join("") + "</" + tag + ">");
        continue;
      }
      buf.push(line);
      i++;
    }
    para(buf);
    return out.join("\n");
  }

  window.IGmd = { render: render, esc: esc };
})();
