/* Geotechnical News Desk — page filters and archive search. */
(function () {
  "use strict";
  var root = document.body.getAttribute("data-root") || "";

  function esc(s) {
    return String(s == null ? "" : s).replace(/[&<>"']/g, function (c) {
      return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c];
    });
  }

  /* ---------- filters on digest and issue pages ---------- */
  document.querySelectorAll(".js-filter").forEach(function (bar) {
    var scope = bar.parentNode;
    var text = bar.querySelector(".f-text"), rel = bar.querySelector(".f-rel"), use = bar.querySelector(".f-use");
    var count = bar.querySelector(".f-count");
    var cards = Array.prototype.slice.call(scope.querySelectorAll(".theme-section .story"));
    function apply() {
      var q = text.value.trim().toLowerCase(), min = +rel.value, u = use.value, shown = 0;
      cards.forEach(function (c) {
        var ok = +c.dataset.rel >= min &&
          (!u || c.dataset.use === u) && (!q || c.dataset.text.indexOf(q) !== -1);
        c.hidden = !ok;
        if (ok) shown++;
      });
      scope.querySelectorAll(".theme-section").forEach(function (sec) {
        var n = sec.querySelectorAll(".story:not([hidden])").length;
        sec.hidden = n === 0;
        var badge = sec.querySelector(".count");
        if (badge) badge.textContent = n;
        var link = scope.querySelector(".theme-toc a[href='#" + sec.id + "'] b");
        if (link) { link.textContent = n; link.parentNode.hidden = n === 0; }
      });
      count.textContent = shown === cards.length ? cards.length + " stories" : "Showing " + shown + " of " + cards.length;
    }
    [text, rel, use].forEach(function (el) { el.addEventListener("input", apply); });
    apply();
  });

  /* ---------- archive search ---------- */
  var app = document.getElementById("search-app");
  if (!app) return;
  var els = {};
  ["q", "q_window", "q_theme", "q_use", "q_rel", "q_sort"].forEach(function (id) { els[id] = document.getElementById(id); });
  var results = document.getElementById("results"), countEl = document.getElementById("result-count");
  var moreBtn = document.getElementById("more"), exportBtn = document.getElementById("export");
  var all = [], matches = [], limit = 50;

  var params = new URLSearchParams(location.search);
  Object.keys(els).forEach(function (id) { if (params.get(id)) els[id].value = params.get(id); });

  function fmt(iso) {
    if (!iso) return "";
    var d = new Date(iso + "T00:00:00Z");
    return d.toLocaleDateString("en-GB", { day: "numeric", month: "short", year: "numeric", timeZone: "UTC" });
  }

  function card(s) {
    var title = s.te || s.t, rel = s.r
      ? "<span class='rel rel-" + s.r + "' title='Geotechnical relevance: " + s.r + " of 5'><i></i><i></i><i></i><i></i><i></i><b>" + s.r + "/5</b></span>"
      : "<span class='rel rel-kw'>Keyword-ranked</span>";
    var meta = ["<span class='src'>" + esc(s.s) + "</span>"];
    if (s.p) meta.push("<time>" + esc(fmt(s.p)) + "</time>");
    if (s.c) meta.push("<span>" + esc(s.c) + " edition</span>");
    var useSlug = s.u ? s.u.split(" ")[0].toLowerCase().replace(/-+$/, "") : "";
    return "<article class='story'><div class='story-top'><a class='story-title' href='" + esc(s.l) + "' target='_blank' rel='noopener'>" +
      esc(title) + "</a>" + rel + "</div>" +
      (s.te ? "<div class='orig' dir='auto'>Original: " + esc(s.t) + "</div>" : "") +
      (s.a ? "<p class='angle'><span>Magazine angle</span>" + esc(s.a) + "</p>" : (s.x ? "<p class='summary'>" + esc(s.x) + "…</p>" : "")) +
      "<div class='story-meta'>" + (s.u ? "<span class='use use-" + esc(useSlug) + "'>" + esc(s.u) + "</span>" : "") +
      "<span class='theme-tag'>" + esc(s.th) + "</span>" + meta.join(" · ") + "</div>" +
      "<div class='found'>Found in the <a href='" + root + "digests/" + esc(s.d) + ".html'>" + esc(fmt(s.d)) + " digest</a> · " +
      "<a href='" + root + "issues/" + esc(s.w) + ".html'>" + esc(s.w.split("-")[1] + " " + s.w.split("-")[0]) + " window</a></div></article>";
  }

  function run() {
    var words = els.q.value.trim().toLowerCase().split(/\s+/).filter(Boolean);
    var w = els.q_window.value, th = els.q_theme.value, u = els.q_use.value, min = +els.q_rel.value;
    matches = all.filter(function (s) {
      if (w && s.w !== w) return false;
      if (th && s.th !== th) return false;
      if (u && s.u !== u) return false;
      if (s.r < min) return false;
      if (!words.length) return true;
      var hay = s._hay || (s._hay = [s.t, s.te, s.a, s.s, s.c, s.th, s.x, (s.k || []).join(" ")].join(" ").toLowerCase());
      return words.every(function (x) { return hay.indexOf(x) !== -1; });
    });
    matches.sort(els.q_sort.value === "new"
      ? function (a, b) { return (b.p || b.d) < (a.p || a.d) ? -1 : 1; }
      : function (a, b) { return (b.r - a.r) || (b.rk - a.rk); });
    limit = 50;
    draw();
    var qs = new URLSearchParams();
    Object.keys(els).forEach(function (id) { if (els[id].value && els[id].value !== "0" && els[id].value !== "rel") qs.set(id, els[id].value); });
    history.replaceState(null, "", qs.toString() ? "?" + qs : location.pathname);
  }

  function draw() {
    countEl.textContent = matches.length + (matches.length === 1 ? " story" : " stories") + " found in " + all.length + " archived";
    results.innerHTML = matches.length ? matches.slice(0, limit).map(card).join("") : "<p class='empty'>No stories match these filters.</p>";
    moreBtn.hidden = matches.length <= limit;
  }

  function csvCell(v) { v = String(v == null ? "" : v); return /[",\n]/.test(v) ? '"' + v.replace(/"/g, '""') + '"' : v; }
  exportBtn.addEventListener("click", function () {
    var head = ["Digest date", "Issue window", "Theme", "Relevance (1-5)", "Suggested use", "Headline (English)", "Original headline",
      "Magazine angle", "Source", "Google News edition", "Published", "Link", "Keywords"];
    var rows = matches.map(function (s) {
      return [s.d, s.w, s.th, s.r || "", s.u, s.te || s.t, s.te ? s.t : "", s.a, s.s, s.c, s.p, s.l, (s.k || []).join(", ")].map(csvCell).join(",");
    });
    var blob = new Blob(["﻿" + [head.join(",")].concat(rows).join("\r\n")], { type: "text/csv;charset=utf-8" });
    var a = document.createElement("a");
    a.href = URL.createObjectURL(blob);
    a.download = "geotech-news-search.csv";
    document.body.appendChild(a); a.click(); a.remove();
  });
  moreBtn.addEventListener("click", function () { limit += 50; draw(); });
  Object.keys(els).forEach(function (id) { els[id].addEventListener("input", run); });

  fetch(root + "exports/index.json").then(function (r) { return r.json(); }).then(function (windows) {
    return Promise.all(windows.map(function (w) {
      return fetch(root + "exports/" + w.key + ".json").then(function (r) { return r.json(); });
    }));
  }).then(function (lists) {
    all = [].concat.apply([], lists);
    run();
  }).catch(function () {
    countEl.textContent = "The archive could not be loaded. If you opened this file from disk, view it on the published website instead.";
  });
})();
