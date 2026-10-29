/* Geotechnical News Desk — the map on the Events page: where the upcoming events take place. A circle per city (in
   the middle of the country when the city is not given or not on events.py's list of cities), gold where at least
   one ISSMGE event is, numbered with the events there; places too close to tell apart share a circle until you zoom
   in. A tap or click lists the events there beside the map (below it on narrow screens), each linking to its card in
   the list. The filters above the map (events.js) apply to it too; the Table view lists every country and event.
   Names are always inserted with textContent. The outlines are assets/world.json, drawn as on the World map (map.js). */
(function () {
  "use strict";
  var dataEl = document.getElementById("evm-data"), canvas = document.getElementById("evm-canvas");
  if (!dataEl || !canvas) return;
  var D;
  try { D = JSON.parse(dataEl.textContent); } catch (e) { return; }
  var root = document.body.getAttribute("data-root") || "";
  var SVGNS = "http://www.w3.org/2000/svg";
  var $ = function (id) { return document.getElementById(id); };
  var fig = $("evm-fig"), panel = $("evm-panel"), live = $("evm-live"), sub = $("evm-sub"), table = $("evm-table");
  var reduceMotion = window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  // a touch screen: every circle answers a finger within 22 px (a 44 px target), and circles whose targets would
  // overlap share one circle until you zoom in, so a tap never picks the neighbour
  var coarse = !!(window.matchMedia && window.matchMedia("(any-pointer: coarse)").matches);

  var shown = null;                  // the events the filters show: {id: true}, or null for all
  var state = { zoom: "", sel: null, all: false };  // sel: {type: "mark", places: [i…]} | {type: "country", cc} | {type: "off", which}
  var TOP = 8;                       // countries listed before "Show all"
  var cur = null;                    // what is shown: places with their events, countries, events not on the map
  var W = null, svg, gCountries, gMarks, gRings, shapes = {}, view = null, anim = null, marks = [];

  /* ---------- small helpers ---------- */
  function el(tag, cls, text) {
    var e = document.createElement(tag);
    if (cls) e.className = cls;
    if (text != null) e.textContent = text;
    return e;
  }
  function sv(tag, attrs) {
    var e = document.createElementNS(SVGNS, tag);
    for (var k in attrs) if (Object.prototype.hasOwnProperty.call(attrs, k)) e.setAttribute(k, attrs[k]);
    return e;
  }
  function plural(n, one, many) { return n + " " + (n === 1 ? one : (many || one + "s")); }
  function name(cc) { return (D.names && D.names[cc]) || cc; }
  function issmgeCount(list) { return list.filter(function (r) { return r.s; }).length; }
  function countLine(list) {  // "3 events · 1 ISSMGE event"
    var s = issmgeCount(list);
    return plural(list.length, "event") + (s ? " · " + plural(s, "ISSMGE event") : "");
  }
  function andList(names) {
    return names.length < 2 ? names.join("") : names.slice(0, -1).join(", ") + " and " + names[names.length - 1];
  }

  /* ---------- what the filters select ---------- */
  function compute() {
    var per = D.places.map(function (p, i) { return { i: i, p: p, ev: [] }; });
    var online = [], unknown = [], countries = {};
    D.events.forEach(function (r) {
      if (shown && !shown[r.i]) return;
      if (r.p >= 0) {
        per[r.p].ev.push(r);
        var cc = D.places[r.p].cc;
        (countries[cc] = countries[cc] || []).push(r);
      } else if (r.o) online.push(r);
      else unknown.push(r);
    });
    var ranked = Object.keys(countries).map(function (cc) { return { cc: cc, name: name(cc), ev: countries[cc] }; })
      .sort(function (a, b) { return b.ev.length - a.ev.length || a.name.localeCompare(b.name); });
    cur = { places: per.filter(function (x) { return x.ev.length; }), online: online, unknown: unknown,
      countries: countries, ranked: ranked };
  }
  function summary() {  // the same sentence as events.map_summary()
    var onMap = 0;
    cur.places.forEach(function (x) { onMap += x.ev.length; });
    var off = [];
    if (cur.online.length) off.push(cur.online.length + " online only");
    if (cur.unknown.length) off.push(cur.unknown.length + " with no place given yet");
    return plural(onMap, "event") + " in " + plural(cur.places.length, "place") + " in " +
      plural(cur.ranked.length, "country", "countries") + "." + (off.length ? " Not on the map: " + off.join(", ") + "." : "");
  }

  /* ---------- the map ---------- */
  function frameAspect() {  // the world's own proportions; on a phone a region gets a taller frame
    return (canvas.clientWidth || 800) < 640 && state.zoom ? 1.6 : W.view[2] / W.view[3];
  }
  function fit(box) {
    var a = frameAspect(), x = box[0], y = box[1], w = box[2], h = box[3];
    if (w / h > a) { var h2 = w / a; y -= (h2 - h) / 2; h = h2; } else { var w2 = h * a; x -= (w2 - w) / 2; w = w2; }
    return [x, y, w, h];
  }
  function target() {  // the region's box, with room around it for the circles at its edges (Punta Arenas)
    var box = state.zoom && W.views[state.zoom] ? W.views[state.zoom] : W.view, pad = 18 * box[2] / (canvas.clientWidth || 800);
    return fit([box[0] - pad, box[1] - pad, box[2] + 2 * pad, box[3] + 2 * pad]);
  }
  function unit() { return view[2] / (canvas.clientWidth || 800); }  // map units per screen pixel
  function radius(n) {  // in screen pixels: 8 for one event, larger for more; a little smaller on a phone's small map
    var scale = Math.max(0.75, Math.min(1, (canvas.clientWidth || 800) / 640));
    return Math.min(22, 8 + 3.2 * Math.sqrt(n - 1)) * scale;
  }
  function reach(n) { return Math.max(radius(n), coarse ? 22 : 16); }  // how far from its middle a circle answers, in pixels
  function setView(v) {
    view = v;
    svg.setAttribute("viewBox", v.map(function (n) { return n.toFixed(1); }).join(" "));
    renderMarks();
  }
  function zoomTo(region) {
    state.zoom = region || "";
    fig.querySelectorAll(".evm-zoom button").forEach(function (b) {
      b.setAttribute("aria-pressed", String((b.getAttribute("data-zoom") || "") === state.zoom));
    });
    var sel = $("evm-zoom-sel");
    if (sel) sel.value = state.zoom;
    if (!W) return;
    var from = view.slice(), to = target();
    if (anim) cancelAnimationFrame(anim);
    if (reduceMotion) { setView(to); return; }
    var t0 = null;
    function step(ts) {
      if (t0 == null) t0 = ts;
      var k = Math.min(1, (ts - t0) / 450), e = k < .5 ? 2 * k * k : 1 - Math.pow(-2 * k + 2, 2) / 2;
      setView(from.map(function (f, i) { return f + (to[i] - f) * e; }));
      if (k < 1) anim = requestAnimationFrame(step); else anim = null;
    }
    anim = requestAnimationFrame(step);
  }

  function buildMap() {
    canvas.textContent = "";
    svg = sv("svg", { "class": "map-svg", "aria-hidden": "true", focusable: "false" });
    svg.appendChild(sv("path", { "class": "map-sphere", d: W.sphere }));
    gCountries = sv("g", { "class": "map-countries" });
    Object.keys(W.countries).forEach(function (cc) {
      var c = W.countries[cc];
      if (!c.d) return;
      shapes[cc] = sv("path", { "class": "map-c", d: c.d, "data-cc": cc });
      gCountries.appendChild(shapes[cc]);
    });
    if (W.land) gCountries.appendChild(sv("path", { "class": "map-c map-x", d: W.land }));
    svg.appendChild(gCountries);
    gMarks = sv("g", { "class": "evm-marks" });
    gRings = sv("g", { "class": "evm-rings" });
    svg.appendChild(gMarks);
    svg.appendChild(gRings);
    canvas.appendChild(svg);
    view = target();
    svg.setAttribute("viewBox", view.join(" "));
  }

  /* places closer on screen than their circles share one circle (the larger groups first), so every circle can be
     told apart and tapped; zooming in separates them */
  function cluster() {
    var k = unit();
    var items = cur.places.map(function (x) {
      return { places: [x], n: x.ev.length, x: x.p.x, y: x.p.y };
    });
    var merged = true;
    while (merged) {
      merged = false;
      items.sort(function (a, b) { return b.n - a.n || a.x - b.x; });
      for (var a = 0; a < items.length && !merged; a++) {
        for (var b = a + 1; b < items.length; b++) {
          var A = items[a], B = items[b], dx = (A.x - B.x) / k, dy = (A.y - B.y) / k;
          var apart = Math.max(radius(A.n) + radius(B.n) + 3, coarse ? reach(A.n) + reach(B.n) : 0);
          if (Math.sqrt(dx * dx + dy * dy) < apart) {
            var n = A.n + B.n;
            A.x = (A.x * A.n + B.x * B.n) / n;
            A.y = (A.y * A.n + B.y * B.n) / n;
            A.places = A.places.concat(B.places);
            A.n = n;
            items.splice(b, 1);
            merged = true;
            break;
          }
        }
      }
    }
    return items.sort(function (a, b) { return a.x - b.x; });  // west to east: the order of the arrow keys
  }
  function eventsOf(m) {
    var out = [];
    m.places.forEach(function (x) { out = out.concat(x.ev); });
    return out;
  }
  function byEvents(places) {  // most events first, then by name
    return places.slice().sort(function (a, b) { return b.ev.length - a.ev.length || a.p.n.localeCompare(b.p.n); });
  }
  function placesTitle(places) {  // "Antwerp, Belgium", or "London, Lyon, Graz and 6 more places"
    places = byEvents(places);
    if (places.length <= 2) return andList(places.map(function (x) { return x.p.n; }));
    var short = places.map(function (x) { return x.p.e ? x.p.n.split(",")[0] : x.p.n; });
    return places.length === 3 ? andList(short) : short.slice(0, 3).join(", ") + " and " + plural(places.length - 3, "more place");
  }
  function markTitle(m) { return placesTitle(m.places); }
  function renderMarks() {
    if (!svg || !cur) return;
    var k = unit();
    gMarks.textContent = "";
    marks = cluster();
    marks.forEach(function (m, idx) {
      var list = eventsOf(m), r = radius(m.n);
      m.issmge = issmgeCount(list) > 0;
      var g = sv("g", { "class": "evm-m" + (m.issmge ? " iss" : ""), "data-m": idx });
      g.appendChild(sv("circle", { "class": "evm-hit", cx: m.x, cy: m.y, r: reach(m.n) * k }));
      g.appendChild(sv("circle", { "class": "evm-c", cx: m.x, cy: m.y, r: r * k }));
      if (m.n > 1) {
        var t = sv("text", { "class": "evm-n", x: m.x, y: m.y, "font-size": (m.n > 9 ? 11 : 12) * k });
        t.textContent = m.n;
        g.appendChild(t);
      }
      m.g = g;
      gMarks.appendChild(g);
    });
    Object.keys(shapes).forEach(function (cc) { shapes[cc].classList.toggle("host", !!cur.countries[cc]); });
    showSelection();
  }
  function selectedPlaces() {  // the places of the current selection, as {place index: true}
    var out = {}, sel = state.sel;
    if (!sel) return out;
    if (sel.type === "mark") sel.places.forEach(function (i) { out[i] = true; });
    if (sel.type === "country") cur.places.forEach(function (x) { if (x.p.cc === sel.cc) out[x.i] = true; });
    return out;
  }
  function showSelection() {  // a ring around the circles of the selection (and the one chosen with the keys)
    if (!gRings) return;
    gRings.textContent = "";
    var k = unit(), want = selectedPlaces();
    marks.forEach(function (m, idx) {
      var on = m.places.some(function (x) { return want[x.i]; }) || (keys.on && keys.i === idx);
      m.g.classList.toggle("on", on);
      if (on) gRings.appendChild(sv("circle", { "class": "evm-ring", cx: m.x, cy: m.y, r: (radius(m.n) + 4) * k }));
    });
    Object.keys(shapes).forEach(function (cc) {
      shapes[cc].classList.toggle("on", !!(state.sel && state.sel.type === "country" && state.sel.cc === cc));
    });
  }

  /* ---------- the panel: the countries, or the events of a place ---------- */
  function rankButton(label, list, attr, value, top) {  // top: the longest list in the panel, so all bars share one scale
    var b = el("button", "map-cc evm-cc"), bar = el("span", "mp-bar evm-bar"), s = issmgeCount(list);
    b.type = "button";
    b.setAttribute(attr, value);
    b.setAttribute("aria-label", label + ": " + countLine(list));
    var names = el("span", "evm-cc-name");
    names.appendChild(el("span", "mp-n", label));
    if (s) names.appendChild(el("small", "evm-cc-s", plural(s, "ISSMGE event")));  // in words, not only the gold bar
    b.appendChild(names);
    var iss = el("i", "evm-bar-iss"), other = el("i", "evm-bar-other");
    iss.style.width = (s / top * 100).toFixed(1) + "%";
    other.style.width = ((list.length - s) / top * 100).toFixed(1) + "%";
    bar.appendChild(iss);
    bar.appendChild(other);
    b.appendChild(bar);
    b.appendChild(el("b", "", String(list.length)));
    return b;
  }
  function renderRanking() {
    panel.textContent = "";
    var head = el("div", "mp-head"), h = el("h3", "", "Countries with events");
    h.tabIndex = -1;  // where the focus goes back to from a place's list
    head.appendChild(h);
    head.appendChild(el("p", "", cur.ranked.length ? "Select a circle on the map, or a country below, to list its events."
      : "No event shown here has a place on the map."));
    panel.appendChild(head);
    var top = Math.max(1, cur.online.length, cur.unknown.length);
    cur.ranked.forEach(function (c) { top = Math.max(top, c.ev.length); });
    if (cur.ranked.length) {
      var ol = el("ol", "mp-top"), more = cur.ranked.length - TOP;
      cur.ranked.forEach(function (c, i) {
        var li = el("li");
        li.appendChild(rankButton(c.name, c.ev, "data-cc", c.cc, top));
        if (i >= TOP && !state.all) li.hidden = true;
        ol.appendChild(li);
      });
      panel.appendChild(ol);
      if (more > 0 && !state.all) {
        var all = el("button", "linkbtn evm-all", "Show all " + cur.ranked.length + " countries");
        all.type = "button";
        panel.appendChild(all);
      }
    }
    if (cur.online.length || cur.unknown.length) {
      panel.appendChild(el("h4", "evm-h4", "Not on the map"));
      var ul = el("ul", "mp-top");
      [["online", "Online only", cur.online], ["unknown", "Place not given yet", cur.unknown]].forEach(function (x) {
        if (!x[2].length) return;
        var li = el("li");
        li.appendChild(rankButton(x[1], x[2], "data-off", x[0], top));
        ul.appendChild(li);
      });
      panel.appendChild(ul);
    }
  }
  function eventItem(r, placeName) {
    var li = el("li", "mp-story evm-ev " + (r.k || "k-other")), a = el("a", "", r.n);
    a.href = "#ev-" + encodeURIComponent(r.i);
    a.title = r.t || r.n;
    a.dir = "auto";
    li.appendChild(a);
    var meta = el("span", "mp-meta");
    meta.appendChild(el("span", "", r.d));
    if (r.c && (!placeName || placeName.indexOf(r.c) !== 0)) meta.appendChild(el("span", "", r.c));
    if (r.s) meta.appendChild(el("span", "evm-badge", "ISSMGE"));
    if (r.o && r.p >= 0) meta.appendChild(el("span", "", "also online"));  // held there and online
    li.appendChild(meta);
    return li;
  }
  function renderSelection(focus) {
    var sel = state.sel, groups = [], title = "", note = "", list = [];
    if (sel.type === "mark") {
      var want = {};
      sel.places.forEach(function (i) { want[i] = true; });
      var ps = byEvents(cur.places.filter(function (x) { return want[x.i]; }));
      groups = ps.map(function (x) { return { name: x.p.n, exact: x.p.e, ev: x.ev }; });
      title = placesTitle(ps);
    } else if (sel.type === "country") {
      groups = byEvents(cur.places.filter(function (x) { return x.p.cc === sel.cc; }))
        .map(function (x) { return { name: x.p.n, exact: x.p.e, ev: x.ev }; });
      title = name(sel.cc);
      var region = D.regions && D.regions[sel.cc];
      if (region) note = "ISSMGE region: " + region + ".";
    } else {
      var off = sel.which === "online" ? cur.online : cur.unknown;
      groups = [{ name: "", exact: 1, ev: off }];
      title = sel.which === "online" ? "Online only" : "Place not given yet";
      note = sel.which === "online" ? "Held online, so not on the map."
        : "The calendar does not give a place for these yet, so they are not on the map.";
    }
    groups.forEach(function (g) { list = list.concat(g.ev); });
    if (!list.length) { state.sel = null; renderRanking(); return; }
    panel.textContent = "";
    var head = el("div", "mp-head"), back = el("button", "linkbtn mp-back", "← All countries");
    back.type = "button";
    head.appendChild(back);
    var h = el("h3", "", title);
    h.tabIndex = -1;
    head.appendChild(h);
    head.appendChild(el("p", "", countLine(list) + (note ? ". " + note : ".") + " Select an event to go to it in the list."));
    panel.appendChild(head);
    groups.forEach(function (g) {
      if (groups.length > 1) panel.appendChild(el("h4", "evm-h4", g.name));
      if (!g.exact && g.name) panel.appendChild(el("p", "evm-mid", "Shown in the middle of the country: the city is not given, or not on the map's list of cities."));
      var ul = el("ul", "mp-list");
      g.ev.forEach(function (r) { ul.appendChild(eventItem(r, g.name)); });
      panel.appendChild(ul);
    });
    if (focus) h.focus();
  }
  function renderPanel(focus) { if (state.sel) renderSelection(focus); else renderRanking(); }
  function select(sel, opts) {
    state.sel = sel;
    renderPanel(opts && opts.focus);
    showSelection();
    if (opts && opts.reveal) {  // below the map on a narrow screen: bring the list into view
      var r = panel.getBoundingClientRect();
      if (r.top > window.innerHeight * 0.7) window.scrollBy({ top: r.top - window.innerHeight * 0.3, behavior: reduceMotion ? "auto" : "smooth" });
    }
  }
  panel.addEventListener("click", function (e) {
    if (e.target.closest(".evm-all")) {  // the rest of the countries, the focus on the first of them
      state.all = true;
      renderRanking();
      var first = panel.querySelectorAll(".mp-top button")[TOP];
      if (first) first.focus();
      return;
    }
    if (e.target.closest(".mp-back")) { select(null, { focus: false }); panel.querySelector("h3").focus(); return; }
    var b = e.target.closest("button[data-cc], button[data-off]");
    if (b) {
      if (b.hasAttribute("data-cc")) select({ type: "country", cc: b.getAttribute("data-cc") }, { focus: true });
      else select({ type: "off", which: b.getAttribute("data-off") }, { focus: true });
    }
  });

  /* ---------- the table view (rebuilt when the filters change; the page itself has it for readers without JavaScript) ---------- */
  function eventLinks(list) {
    var ul = el("ul", "evm-tl");
    list.forEach(function (r) {
      var li = el("li"), a = el("a", "", r.n);
      a.href = "#ev-" + encodeURIComponent(r.i);
      li.appendChild(a);
      li.appendChild(el("span", "", [r.c, r.d].filter(Boolean).join(" · ") + (r.s ? " · ISSMGE" : "")));
      ul.appendChild(li);
    });
    return ul;
  }
  function tableRow(label, region, list, cls) {
    var tr = el("tr", cls || ""), th = el("th", "", label);
    th.scope = "row";
    tr.appendChild(th);
    tr.appendChild(el("td", "", region));
    tr.appendChild(el("td", "num", String(list.length)));
    tr.appendChild(el("td", "num", String(issmgeCount(list))));
    var td = el("td");
    td.appendChild(eventLinks(list));
    tr.appendChild(td);
    return tr;
  }
  function renderTable() {
    var t = table.querySelector("table");
    if (!t) return;
    t.querySelectorAll("tbody").forEach(function (b) { b.remove(); });
    var body = el("tbody");
    cur.ranked.forEach(function (c) { body.appendChild(tableRow(c.name, (D.regions && D.regions[c.cc]) || "–", c.ev)); });
    if (!cur.ranked.length) {
      var tr = el("tr"), td = el("td", "viz-empty", "No event shown here has a place on the map.");
      td.colSpan = 5;
      tr.appendChild(td);
      body.appendChild(tr);
    }
    t.appendChild(body);
    if (cur.online.length || cur.unknown.length) {
      var foot = el("tbody", "evm-off-body");
      if (cur.online.length) foot.appendChild(tableRow("Online only", "Not on the map", cur.online, "evm-off-row"));
      if (cur.unknown.length) foot.appendChild(tableRow("Place not given yet", "Not on the map", cur.unknown, "evm-off-row"));
      t.appendChild(foot);
    }
  }

  /* ---------- pointer: a tooltip with the mouse, the list on a tap or click ---------- */
  var tip = el("div", "viz-tip");
  tip.hidden = true;
  tip.setAttribute("aria-hidden", "true");  // the panel and the live text say the same
  document.body.appendChild(tip);
  function showTip(m, x, y) {
    tip.textContent = "";
    tip.appendChild(el("div", "tt-h", markTitle(m)));
    var list = eventsOf(m);
    tip.appendChild(el("div", "", countLine(list)));
    tip.appendChild(el("div", "tt-f", "Select to list " + (list.length === 1 ? "it" : "them") + "."));
    tip.hidden = false;
    var w = tip.offsetWidth, h = tip.offsetHeight, left = x + 14, top = y + 14;
    if (left + w > window.innerWidth - 8) left = x - w - 14;
    if (top + h > window.innerHeight - 8) top = y - h - 14;
    tip.style.left = Math.max(8, left) + "px";
    tip.style.top = Math.max(8, top) + "px";
  }
  function hideTip() { tip.hidden = true; }
  function markAt(e) {  // the circle nearest the pointer, within its reach (where two reaches overlap, the nearer wins)
    if (!svg || !view || !marks.length) return null;
    var rect = svg.getBoundingClientRect();
    if (!rect.width) return null;
    var k = view[2] / rect.width, x = view[0] + (e.clientX - rect.left) * k, y = view[1] + (e.clientY - rect.top) * k;
    var best = null, bestD = Infinity;
    marks.forEach(function (m) {
      var d = Math.sqrt((m.x - x) * (m.x - x) + (m.y - y) * (m.y - y)) / k;
      if (d <= reach(m.n) && d < bestD) { best = m; bestD = d; }
    });
    return best;
  }
  var touch = false;
  canvas.addEventListener("pointerdown", function (e) { touch = e.pointerType !== "mouse"; });
  canvas.addEventListener("pointermove", function (e) {
    if (e.pointerType !== "mouse") return;
    var m = markAt(e);
    if (m) showTip(m, e.clientX, e.clientY); else hideTip();
  });
  canvas.addEventListener("pointerleave", hideTip);
  canvas.addEventListener("click", function (e) {
    var m = markAt(e);
    if (!m) return;
    hideTip();
    keys.on = false;
    select({ type: "mark", places: m.places.map(function (x) { return x.i; }) }, { reveal: touch });
    live.textContent = markTitle(m) + ": " + countLine(eventsOf(m)) + ", listed beside the map.";
  });

  /* ---------- keyboard: the arrow keys walk the circles west to east, Enter lists the events, Escape stops ---------- */
  var keys = { i: -1, on: false };
  canvas.addEventListener("keydown", function (e) {
    if (!W || !marks.length) return;
    if (e.key === "Escape" || e.key === "Esc") { keys.on = false; hideTip(); showSelection(); live.textContent = ""; return; }
    if ((e.key === "Enter" || e.key === " ") && keys.on && marks[keys.i]) {
      e.preventDefault();
      var m = marks[keys.i];
      select({ type: "mark", places: m.places.map(function (x) { return x.i; }) }, { focus: true });
      return;
    }
    var step = { ArrowRight: 1, ArrowDown: 1, ArrowLeft: -1, ArrowUp: -1 }[e.key];
    if (!step) return;
    e.preventDefault();
    keys.i = !keys.on || keys.i < 0 || keys.i >= marks.length ? (step > 0 ? 0 : marks.length - 1)
      : (keys.i + step + marks.length) % marks.length;
    keys.on = true;
    var mk = marks[keys.i], rect = canvas.getBoundingClientRect(), k = unit();
    showSelection();
    showTip(mk, rect.left + (mk.x - view[0]) / k, rect.top + (mk.y - view[1]) / k);
    live.textContent = markTitle(mk) + ": " + countLine(eventsOf(mk)) + ". Press Enter to list them.";
  });
  canvas.addEventListener("blur", function () { hideTip(); if (keys.on) { keys.on = false; showSelection(); } });

  /* ---------- controls ---------- */
  fig.addEventListener("click", function (e) {
    var z = e.target.closest ? e.target.closest(".evm-zoom [data-zoom]") : null;
    if (z) zoomTo(z.getAttribute("data-zoom") || "");
  });
  var zoomSel = $("evm-zoom-sel");
  if (zoomSel) zoomSel.addEventListener("change", function () { zoomTo(zoomSel.value); });
  var toggle = fig.querySelector(".viz-toggle");
  function showView(asTable) {
    fig.querySelector(".evm-chart").hidden = asTable;
    table.hidden = !asTable;
    toggle.querySelectorAll("button").forEach(function (x) {
      x.setAttribute("aria-pressed", String((x.getAttribute("data-view") === "table") === asTable));
    });
    hideTip();
    if (!asTable && W) requestAnimationFrame(function () { setView(target()); });
  }
  toggle.addEventListener("click", function (e) {
    var b = e.target.closest("button");
    if (b) showView(b.getAttribute("data-view") === "table");
  });
  var resizing = null, lastW = canvas.clientWidth;
  window.addEventListener("resize", function () {
    if (resizing || !W) return;
    resizing = requestAnimationFrame(function () {
      resizing = null;
      if (canvas.clientWidth === lastW || !canvas.clientWidth) return;
      lastW = canvas.clientWidth;
      setView(target());
    });
  });

  /* ---------- the filters (events.js) ---------- */
  function renderAll() {
    compute();
    sub.textContent = summary();
    renderPanel(false);
    renderTable();
    renderMarks();
  }
  function fromList() {  // the cards the filters leave in the list, as the page is now
    var cards = document.querySelectorAll(".ev-list .ev-card");
    if (!cards.length) return null;
    var out = {}, all = true;
    Array.prototype.forEach.call(cards, function (c) {
      if (c.hidden) all = false; else out[c.id.replace(/^ev-/, "")] = true;
    });
    return all ? null : out;
  }
  document.addEventListener("events-filtered", function (e) {
    var ids = e.detail || [], set = {};
    ids.forEach(function (i) { set[i] = true; });
    shown = ids.length === document.querySelectorAll(".ev-list .ev-card").length ? null : set;
    renderAll();
  });

  /* ---------- start ---------- */
  shown = fromList();
  renderAll();
  fetch(root + "assets/world.json").then(function (r) {
    if (!r.ok) throw new Error("status " + r.status);
    return r.json();
  }).then(function (w) {
    W = w;
    buildMap();
    renderMarks();
  }).catch(function () {
    canvas.textContent = "";
    canvas.appendChild(el("p", "map-loading", "The map could not be loaded. The Table button lists every country and its events."));
  });
})();
