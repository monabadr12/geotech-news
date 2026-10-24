/* Geotechnical News Desk — trends page: chart tooltips (pointer and keyboard) and the chart / table switch.
   Tooltip text comes from the page's data-tip attributes and is always inserted with textContent. */
(function () {
  "use strict";
  var tipEl = document.createElement("div");
  tipEl.className = "viz-tip";
  tipEl.hidden = true;
  tipEl.setAttribute("aria-hidden", "true");  // the table view is the accessible twin of every chart
  document.body.appendChild(tipEl);

  function add(parent, tag, cls, text) {
    var el = document.createElement(tag);
    if (cls) el.className = cls;
    if (text != null) el.textContent = text;
    parent.appendChild(el);
    return el;
  }
  /* data = {h: heading, r: [[colour class, value, label, series index], ...], f: footer} */
  function render(data, hi) {
    tipEl.textContent = "";
    add(tipEl, "div", "tt-h", data.h);
    if (data.r && data.r.length) {
      var g = add(tipEl, "div", "tt-g");
      data.r.forEach(function (r) {
        var on = hi != null && r[3] === hi ? " on" : "";
        add(g, "i", "tt-k " + (r[0] || "") + on);
        add(g, "b", on.trim(), r[1]);
        add(g, "span", on.trim(), r[2]);
      });
    }
    if (data.f) add(tipEl, "div", "tt-f", data.f);
    tipEl.hidden = false;
  }
  function place(x, y) {  // beside the pointer, kept inside the window
    var w = tipEl.offsetWidth, h = tipEl.offsetHeight;
    var left = x + 14, top = y + 14;
    if (left + w > window.innerWidth - 8) left = x - w - 14;
    if (top + h > window.innerHeight - 8) top = y - h - 14;
    tipEl.style.left = Math.max(8, left) + "px";
    tipEl.style.top = Math.max(8, top) + "px";
  }
  var owner = null;  // the chart the tooltip currently belongs to
  function hide(g) { if (!g || owner === g) { tipEl.hidden = true; owner = null; } }
  function parse(s) { try { return JSON.parse(s); } catch (e) { return null; } }
  var touch = false;
  document.addEventListener("pointerdown", function (e) { touch = e.pointerType === "touch"; }, true);

  /* charts whose marks carry their own tooltip: columns, bars, dumbbells, heat-table cells */
  document.querySelectorAll(".viz-plot:not(.viz-line), .hbars, .dbs, table.heat").forEach(function (g) {
    var marks = Array.prototype.slice.call(g.querySelectorAll("[data-tip]"));
    var cols = g.tagName === "TABLE" ? (g.querySelector("tbody tr") || g).querySelectorAll("[data-tip]").length : 1;
    var cur = null, idx = -1;
    function show(el, hi, x, y) {
      var data = parse(el.getAttribute("data-tip"));
      if (!data) return;
      if (cur && cur !== el) cur.classList.remove("on");
      cur = el;
      el.classList.add("on");
      g.classList.add("hovering");
      render(data, hi);
      owner = g;
      if (x == null) {  // keyboard: anchor on the mark
        var r = el.getBoundingClientRect();
        x = r.left + r.width / 2;
        y = r.top + Math.min(r.height / 2, 24);
      }
      place(x, y);
    }
    function clear() {
      if (cur) cur.classList.remove("on");
      cur = null;
      g.classList.remove("hovering");
      hide(g);
    }
    function move(e) {
      var el = e.target.closest ? e.target.closest("[data-tip]") : null;
      if (!el || !g.contains(el)) { clear(); return; }
      var s = e.target.getAttribute("data-s");
      idx = marks.indexOf(el);
      show(el, s == null ? null : +s, e.clientX, e.clientY);
    }
    g.addEventListener("pointermove", move);
    g.addEventListener("pointerdown", move);
    g.addEventListener("pointerleave", function () { if (!touch) clear(); });
    document.addEventListener("pointerdown", function (e) { if (!g.contains(e.target)) clear(); });
    g.addEventListener("blur", clear);
    g.addEventListener("keydown", function (e) {
      var step = { ArrowRight: 1, ArrowLeft: -1, ArrowDown: cols, ArrowUp: -cols }[e.key];
      if (e.key === "Escape") { clear(); return; }
      if (!step || !marks.length) return;
      e.preventDefault();
      idx = idx < 0 ? (step > 0 ? 0 : marks.length - 1) : Math.min(marks.length - 1, Math.max(0, idx + step));
      show(marks[idx], null);
    });
  });

  /* line charts: a crosshair finds the month; small multiples share one crosshair and one tooltip */
  document.querySelectorAll(".viz-line").forEach(function (g) {
    var tips = parse(g.getAttribute("data-tips"));
    if (!tips || !tips.length) return;
    var panels = g.classList.contains("sm-grid") ? Array.prototype.slice.call(g.querySelectorAll(".smp")) : [g];
    panels.forEach(function (p) {
      p._area = p.querySelector(".sm-plot") || p.querySelector(".viz-area");
      p._ys = p.getAttribute("data-ys") ? parse(p.getAttribute("data-ys")) : null;
    });
    var idx = -1;
    function show(i, x, y) {
      idx = i;
      var t = tips[i];
      panels.forEach(function (p) {
        var xh = p._area.querySelector(".xh"), xd = p._area.querySelector(".hd");
        var yv = p._ys ? p._ys[i] : t.y;
        xh.style.left = t.x + "%";
        xh.hidden = false;
        xd.hidden = yv == null;
        if (yv != null) { xd.style.left = t.x + "%"; xd.style.top = yv + "px"; }
      });
      render(t.t, null);
      owner = g;
      if (x == null) {
        var r = panels[0]._area.getBoundingClientRect();
        x = r.left + r.width * t.x / 100;
        y = r.top;
      }
      place(x, y);
    }
    function clear() {
      panels.forEach(function (p) {
        p._area.querySelector(".xh").hidden = true;
        p._area.querySelector(".hd").hidden = true;
      });
      hide(g);
    }
    function move(e) {
      var p = (e.target.closest && e.target.closest(".smp")) || panels[0];
      var r = p._area.getBoundingClientRect();
      if (!r.width) return;
      var at = (e.clientX - r.left) / r.width * 100, best = 0;
      tips.forEach(function (t, i) { if (Math.abs(t.x - at) < Math.abs(tips[best].x - at)) best = i; });
      show(best, e.clientX, e.clientY);
    }
    g.addEventListener("pointermove", move);
    g.addEventListener("pointerdown", move);
    g.addEventListener("pointerleave", function () { if (!touch) clear(); });
    document.addEventListener("pointerdown", function (e) { if (!g.contains(e.target)) clear(); });
    g.addEventListener("blur", clear);
    g.addEventListener("keydown", function (e) {
      var step = { ArrowRight: 1, ArrowLeft: -1 }[e.key];
      if (e.key === "Escape") { clear(); return; }
      if (!step) return;
      e.preventDefault();
      show(idx < 0 ? (step > 0 ? 0 : tips.length - 1) : Math.min(tips.length - 1, Math.max(0, idx + step)), null);
    });
  });

  /* heat tables run oldest to newest issue window, then Total: where they scroll sideways (phones), open them
     at the right end, so the current window and the totals show first. Redone once the web fonts are in,
     unless the reader has scrolled the table meanwhile. */
  var wraps = [];
  document.querySelectorAll("table.heat").forEach(function (t) {
    var w = t.closest(".table-wrap");
    if (w) wraps.push(w);
  });
  function toEnd() {
    wraps.forEach(function (w) {
      if (w._end != null && w.scrollLeft !== w._end) return;  // moved by the reader
      w.scrollLeft = w.scrollWidth;
      w._end = w.scrollLeft;
    });
  }
  toEnd();
  if (document.fonts && document.fonts.ready) document.fonts.ready.then(toEnd);

  /* chart / table switch */
  document.querySelectorAll(".viz-toggle").forEach(function (t) {
    var fig = t.closest(".viz");
    t.addEventListener("click", function (e) {
      var b = e.target.closest("button");
      if (!b) return;
      var table = b.getAttribute("data-view") === "table";
      fig.querySelector(".viz-chart").hidden = table;
      fig.querySelector(".viz-table").hidden = !table;
      t.querySelectorAll("button").forEach(function (x) { x.setAttribute("aria-pressed", String(x === b)); });
      hide();
    });
  });
})();
