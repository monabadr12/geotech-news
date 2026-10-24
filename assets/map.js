/* Geotechnical News Desk — world map page: stories by the country they are about (circles), the ISSMGE
   member-society countries and those with no stories (gaps), the period and theme filters, zoom to a region,
   the country panel, the regions and the table view. Feed text is always inserted with textContent, and only
   web links are used. The geometry is assets/world.json (Natural Earth, Equal Earth projection). */
(function () {
  "use strict";
  var dataEl = document.getElementById("map-data"), canvas = document.getElementById("map-canvas");
  if (!dataEl || !canvas) return;
  var D;
  try { D = JSON.parse(dataEl.textContent); } catch (e) { return; }
  var root = document.body.getAttribute("data-root") || "";
  var SVGNS = "http://www.w3.org/2000/svg";
  var $ = function (id) { return document.getElementById(id); };
  var panel = $("map-panel"), note = $("map-note"), legendEl = $("map-legend"), live = $("map-live");
  var reduceMotion = window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches;

  var state = { p: 0, t: -1, zoom: "", cc: null, shown: 0 };
  var W = null;            // assets/world.json
  var cache = {};          // issue window key -> its located stories, read from exports/<key>.json
  var cur = null;          // what the filters select: counts per country and the totals
  var member = {};         // member-society countries
  D.regions.forEach(function (r) { r.m.forEach(function (c) { member[c] = true; }); });
  var generalIdx = Math.max(0, D.themes.indexOf("General"));
  var PAGE = 40;           // stories listed at a time in the panel

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
  function num(n) { return Number(n || 0).toLocaleString("en-GB"); }
  function plural(n, one, many) { return num(n) + " " + (n === 1 ? one : (many || one + "s")); }
  function pct(n, total) { return total ? Math.round(n / total * 100) + "%" : "–"; }
  var MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
  function fmtDate(iso) {  // 3 Sep 2026, as the pages built in Python write dates
    var d = new Date(String(iso || "").slice(0, 10) + "T00:00:00Z");
    return isNaN(d) ? "" : d.getUTCDate() + " " + MONTHS[d.getUTCMonth()] + " " + d.getUTCFullYear();
  }
  function safeUrl(u) { u = String(u || "").trim(); return /^https?:\/\//i.test(u) ? u : "#"; }
  function name(cc) { return (D.names && D.names[cc]) || cc; }
  function regionOf(cc) { var i = D.rc[cc]; return i == null ? null : D.regions[i]; }
  function canon(code) {
    code = String(code || "").trim().toUpperCase();
    code = D.alias[code] || code;
    return D.names[code] ? code : "";
  }
  function pick(counts, t) {
    if (!counts) return 0;
    if (t >= 0) return counts[String(t)] || 0;
    var s = 0;
    for (var k in counts) if (Object.prototype.hasOwnProperty.call(counts, k)) s += counts[k];
    return s;
  }
  function topThemes(counts, n) {
    return Object.keys(counts || {}).map(function (k) { return [counts[k], +k]; })
      .sort(function (a, b) { return b[0] - a[0] || a[1] - b[1]; }).slice(0, n || 2);
  }

  /* ---------- what the filters select ---------- */
  function compute() {
    var P = D.periods[state.p], t = state.t, counts = {}, located = 0;
    Object.keys(P.c).forEach(function (cc) {
      var v = pick(P.c[cc], t);
      if (v) { counts[cc] = v; located += v; }
    });
    var g = pick(P.g, t), u = pick(P.u, t);
    var regions = D.regions.map(function (r, i) {
      var row = { r: r, i: i, stories: 0, covered: 0, gaps: [] };
      Object.keys(counts).forEach(function (cc) { if (D.rc[cc] === i) row.stories += counts[cc]; });
      r.m.forEach(function (m) { if (counts[m]) row.covered++; else row.gaps.push(m); });
      row.gaps.sort(function (a, b) { return name(a).localeCompare(name(b)); });
      return row;
    });
    var codes = Object.keys(counts);
    if (located) Object.keys(member).forEach(function (m) { if (!counts[m]) codes.push(m); });
    var rows = codes.map(function (cc) {
      var themes = {};
      if (P.c[cc]) Object.keys(P.c[cc]).forEach(function (k) { if (t < 0 || +k === t) themes[k] = P.c[cc][k]; });
      return { cc: cc, n: counts[cc] || 0, name: name(cc), region: regionOf(cc), member: !!member[cc], themes: themes };
    }).sort(function (a, b) { return b.n - a.n || a.name.localeCompare(b.name); });
    var max = 0;
    codes.forEach(function (cc) { if ((counts[cc] || 0) > max) max = counts[cc]; });
    cur = { P: P, t: t, counts: counts, located: located, g: g, u: u, n: located + g + u, regions: regions, rows: rows, max: max };
  }
  function themeLabel() { return state.t >= 0 ? D.themes[state.t] : ""; }
  function periodText() {
    var P = cur.P;
    return P.l + (themeLabel() ? " · " + themeLabel() : "");
  }

  /* ---------- key figures, count, note ---------- */
  function stat(value, label, small) {
    var d = el("div", "stat");
    d.appendChild(el("b", "", value));
    d.appendChild(el("span", "", label));
    if (small) d.appendChild(el("small", "", small));
    return d;
  }
  function renderFigures() {
    var total = 0, covered = 0, withMember = 0;
    cur.regions.forEach(function (r) { total += r.r.m.length; covered += r.covered; });
    Object.keys(cur.counts).forEach(function (cc) { if (member[cc]) withMember++; });
    var k = $("map-kpis");
    k.textContent = "";
    k.appendChild(stat(num(cur.n), "Stories in the period", num(cur.located) + " located in a country"));
    k.appendChild(stat(num(Object.keys(cur.counts).length), "Countries with stories", withMember + " with an ISSMGE member society"));
    k.appendChild(stat(cur.located ? covered + " of " + total : "–", "Member-society countries covered",
      cur.located ? (total - covered) + " with no stories (the gaps)" : "Shown once stories are located"));
    k.appendChild(stat(num(cur.g + cur.u), "Global or not located",
      num(cur.g) + " global or several countries · " + num(cur.u) + " not located yet"));
    var nc = Object.keys(cur.counts).length;
    $("map-count").textContent = plural(cur.n, "story", "stories") + " · " + plural(nc, "country", "countries");
    $("map-sub").textContent = periodText() + " · " + cur.P.sub + ". Circle area shows the number of stories.";
    var msg = "";
    if (!cur.n) msg = themeLabel() ? "No " + themeLabel() + " stories in this period." : "No stories in this period.";
    else if (!cur.located) msg = "None of this period's " + plural(cur.n, "story", "stories") + " has a location yet. Claude reads each " +
      "story's country during the scan; stories archived earlier are located in batches after the next scan.";
    else if (cur.u) msg = plural(cur.u, "story", "stories") + " in this period " + (cur.u === 1 ? "has" : "have") +
      " no location yet; " + (cur.u === 1 ? "it is" : "they are") + " located after the next scan. Member-society countries " +
      "are marked as gaps only from the stories already located.";
    note.textContent = msg;
    note.hidden = !msg;
  }

  /* ---------- the regions ---------- */
  function renderRegions() {
    var box = $("map-regions");
    box.textContent = "";
    cur.regions.forEach(function (row) {
      var r = row.r, m = r.m.length, a = el("article", "map-region");
      var head = el("div", "mr-head");
      head.appendChild(el("h3", "", r.n));
      var zb = el("button", "linkbtn mr-zoom", "Show on map");
      zb.type = "button";
      zb.setAttribute("data-zoom", r.n);
      head.appendChild(zb);
      a.appendChild(head);
      var fig = el("p", "mr-fig");
      fig.appendChild(el("b", "", num(row.stories)));
      fig.appendChild(el("span", "", (row.stories === 1 ? "story" : "stories") + (cur.located ? " · " + pct(row.stories, cur.located) + " of located" : "")));
      a.appendChild(fig);
      var cov = el("p", "mr-cov");
      cov.appendChild(el("b", "", (cur.located ? row.covered : "–") + " of " + m));
      cov.appendChild(document.createTextNode(" member-society " + (m === 1 ? "country" : "countries") + " with stories"));
      a.appendChild(cov);
      var meter = el("div", "mr-meter"), fill = el("i");
      meter.setAttribute("aria-hidden", "true");
      fill.style.width = (m && cur.located ? row.covered / m * 100 : 0).toFixed(1) + "%";
      meter.appendChild(fill);
      a.appendChild(meter);
      var gaps = el("p", "mr-gaps");
      if (!m) gaps.textContent = "No member society is listed for this region in config.yaml.";
      else if (!cur.located) {
        gaps.appendChild(el("span", "members", "Member-society countries:"));
        gaps.appendChild(document.createTextNode(" " + r.m.map(name).sort(function (a, b) { return a.localeCompare(b); }).join(", ")));
      } else if (row.gaps.length) {
        gaps.appendChild(el("span", "", "No stories from:"));
        gaps.appendChild(document.createTextNode(" " + row.gaps.map(name).join(", ")));
      } else {
        gaps.className += " ok";
        gaps.textContent = "Every member-society country has stories in this period.";
      }
      a.appendChild(gaps);
      var extra = [];
      if (r.t.length) extra.push("Also " + r.t.join(", ") + " (transnational, not mapped).");
      if (r.x) extra.push("ISSMGE lists " + r.s + " societies here; the list used for the map is still being checked against issmge.org.");
      if (extra.length) a.appendChild(el("p", "mr-note", extra.join(" ")));
      box.appendChild(a);
    });
  }

  /* ---------- table view ---------- */
  function themeText(themes) {
    return topThemes(themes, 2).map(function (x) { return D.themes[x[1]] + " (" + x[0] + ")"; }).join(", ");
  }
  function ccButton(cc, cls, label) {
    var b = el("button", cls || "map-cc", label == null ? name(cc) : null);
    b.type = "button";
    b.setAttribute("data-cc", cc);
    return b;
  }
  function renderTable() {
    var tb = $("map-table").querySelector("tbody");
    tb.textContent = "";
    if (!cur.rows.length) {
      var tr0 = el("tr"), td0 = el("td", "viz-empty", "No located stories in this period.");
      td0.colSpan = 6;
      tr0.appendChild(td0);
      tb.appendChild(tr0);
      return;
    }
    cur.rows.forEach(function (row) {
      var tr = el("tr", row.member && !row.n ? "gap" : "");
      var th = el("th");
      th.scope = "row";
      th.appendChild(ccButton(row.cc));
      tr.appendChild(th);
      tr.appendChild(el("td", "", row.region ? row.region.n : "–"));
      tr.appendChild(el("td", "", row.member ? "Yes" : "No"));
      tr.appendChild(el("td", "num", num(row.n)));
      tr.appendChild(el("td", "num", pct(row.n, cur.located)));
      var td = el("td");
      if (row.n) td.textContent = themeText(row.themes);
      else td.appendChild(el("span", "gap-tag", "No stories"));
      tr.appendChild(td);
      tb.appendChild(tr);
    });
  }

  /* ---------- the panel: ranking, or one country's stories ---------- */
  function renderRanking() {
    panel.textContent = "";
    var ranked = cur.rows.filter(function (r) { return r.n; }), head = el("div", "mp-head");
    if (!ranked.length) {
      head.appendChild(el("h3", "", "Countries"));
      head.appendChild(el("p", "", cur.located || !cur.n ? "No located stories for this selection. Select any country on the map to see whether it has a member society."
        : "No located stories in this period yet. Select any country on the map to see whether it has a member society."));
      panel.appendChild(head);
      return;
    }
    head.appendChild(el("h3", "", "Countries with the most stories"));
    head.appendChild(el("p", "", periodText() + ". Select a country on the map or below to list its stories."));
    panel.appendChild(head);
    var ol = el("ol", "mp-top"), top = ranked[0].n;
    ranked.slice(0, 12).forEach(function (r) {
      var li = el("li"), b = ccButton(r.cc, "map-cc", ""), bar = el("span", "mp-bar"), fill = el("i");
      b.appendChild(el("span", "mp-n", r.name));
      fill.style.width = (r.n / top * 100).toFixed(1) + "%";
      bar.appendChild(fill);
      b.appendChild(bar);
      b.appendChild(el("b", "", num(r.n)));
      li.appendChild(b);
      ol.appendChild(li);
    });
    panel.appendChild(ol);
    if (ranked.length > 12) panel.appendChild(el("p", "mp-foot", (ranked.length - 12) + " more " + (ranked.length - 12 === 1 ? "country" : "countries") + " in the table view."));
  }

  function storyRows(rows) {  // export rows -> the page's own shape, located stories only
    var out = [];
    (rows || []).forEach(function (r) {
      if (!r || r.kind === "paper") return;
      var cc = canon(r.cc);
      if (!cc) return;
      var ti = D.themes.indexOf(r.th);
      out.push([cc, ti < 0 ? generalIdx : ti, String(r.d || "").slice(0, 10), r.t || "", r.te || "", safeUrl(r.l), r.s || "", r.pl || "", r.r || 0]);
    });
    return out;
  }
  var pending = {};
  function stories(P, done) {  // the located stories of a period, embedded or read from the windows' exports
    if (P === D.periods[0] && D.stories) { done(D.stories); return; }
    var need = P.w.filter(function (k) { return !cache[k]; });
    Promise.all(need.map(function (k) {
      if (!pending[k]) pending[k] = fetch(root + "exports/" + encodeURIComponent(k) + ".json").then(function (r) {
        if (!r.ok) throw new Error("status " + r.status);
        return r.json();
      }).then(function (rows) { cache[k] = storyRows(rows); }).catch(function (e) { delete pending[k]; throw e; });
      return pending[k];
    })).then(function () {
      var all = [];
      P.w.forEach(function (k) { all = all.concat(cache[k] || []); });
      done(all.filter(function (r) { return (!P.a || r[2] >= P.a) && (!P.b || r[2] <= P.b); }));
    }).catch(function () { done(null); });
  }

  function statusLine(cc, short) {
    var r = regionOf(cc), n = cur.counts[cc] || 0, parts = [];
    if (r) parts.push(r.n);
    parts.push(member[cc] ? "ISSMGE member society" : "no ISSMGE member society");
    if (member[cc] && !n && cur.located && !short) parts.push("no stories in this period (a gap)");
    return parts.join(" · ");
  }
  function openCountry(cc, focusPanel) {
    if (!cc) return;
    state.cc = cc;
    state.shown = PAGE;
    highlight(cc);
    panel.textContent = "";
    var head = el("div", "mp-head"), back = el("button", "linkbtn mp-back", "← All countries");
    back.type = "button";
    head.appendChild(back);
    var h = el("h3", "", name(cc));
    h.tabIndex = -1;
    head.appendChild(h);
    var n = cur.counts[cc] || 0;
    head.appendChild(el("p", "", statusLine(cc, true) + ". " + (n ? plural(n, "story", "stories") + " · " : "") + periodText() + "."));
    panel.appendChild(head);
    if (!n) {
      panel.appendChild(el("p", "mp-empty", member[cc] && cur.located
        ? "No story from " + name(cc) + " in this period: a gap worth a look when planning the issue."
        : "No stories from " + name(cc) + " in this period."));
      if (focusPanel) h.focus();
      return;
    }
    var list = el("ul", "mp-list"), wait = el("p", "mp-empty", "Loading the stories…");
    panel.appendChild(wait);
    var token = {};
    panel._token = token;
    stories(cur.P, function (rows) {
      if (panel._token !== token) return;  // another country was chosen meanwhile
      wait.remove();
      if (!rows) {
        var fail = el("p", "mp-empty", "The stories could not be loaded. They are also on the "), link = el("a", "", "Search page");
        link.href = root + "search.html";
        fail.appendChild(link);
        fail.appendChild(document.createTextNode("."));
        panel.appendChild(fail);
        return;
      }
      var mine = rows.filter(function (r) { return r[0] === cc && (state.t < 0 || r[1] === state.t); })
        .sort(function (a, b) { return a[2] < b[2] ? 1 : a[2] > b[2] ? -1 : (b[8] - a[8]); });
      panel.appendChild(list);
      var more = el("button", "btn mp-more");
      more.type = "button";
      function fill() {
        mine.slice(list.children.length, state.shown).forEach(function (r) { list.appendChild(storyItem(r)); });
        var left = mine.length - list.children.length;
        more.textContent = "Show " + Math.min(left, PAGE) + " more";
        more.hidden = left <= 0;
      }
      more.addEventListener("click", function () { state.shown += PAGE; fill(); });
      fill();
      panel.appendChild(more);
    });
    if (focusPanel) h.focus();
  }
  function storyItem(r) {
    var li = el("li", "mp-story"), color = D.tc[r[1]] || D.tc[generalIdx];
    li.style.setProperty("--tc", color);
    var a = el("a", "", r[4] || r[3]);
    a.href = safeUrl(r[5]);
    a.target = "_blank";
    a.rel = "noopener";
    a.dir = "auto";
    li.appendChild(a);
    if (r[4]) { var o = el("span", "mp-orig", "Original: " + r[3]); o.dir = "auto"; li.appendChild(o); }
    var meta = el("span", "mp-meta"), theme = el("span", "mp-theme");
    theme.appendChild(el("i", "mp-dot"));
    theme.appendChild(document.createTextNode(D.themes[r[1]] || ""));
    meta.appendChild(el("time", "", fmtDate(r[2])));
    meta.appendChild(theme);
    [r[7], r[6]].forEach(function (x) { if (x) meta.appendChild(el("span", "", x)); });
    if (r[8]) meta.appendChild(el("span", "mp-rel", r[8] + "/5"));
    li.appendChild(meta);
    return li;
  }
  function closeCountry() {
    state.cc = null;
    highlight(null);
    renderRanking();
  }
  panel.addEventListener("click", function (e) {
    if (e.target.closest(".mp-back")) closeCountry();
  });

  /* ---------- the map ---------- */
  var svg, gCountries, gBubbles, gLabels, gDots, ring, hatch, hatchLine, shapes = {}, view = null, anim = null;
  function frameAspect() {  // the world's own proportions; on a phone a region gets a taller frame
    return (canvas.clientWidth || 800) < 640 && state.zoom ? 1.6 : W.view[2] / W.view[3];
  }
  function fit(box) {  // a region's box grown to the frame's proportions, around its centre
    var a = frameAspect(), x = box[0], y = box[1], w = box[2], h = box[3];
    if (w / h > a) { var h2 = w / a; y -= (h2 - h) / 2; h = h2; } else { var w2 = h * a; x -= (w2 - w) / 2; w = w2; }
    return [x, y, w, h];
  }
  function target() { return fit(state.zoom && W.views[state.zoom] ? W.views[state.zoom] : W.view); }
  function setView(v) {
    view = v;
    svg.setAttribute("viewBox", v.map(function (n) { return n.toFixed(1); }).join(" "));
    sizeMarks();
  }
  function zoomTo(region) {
    state.zoom = region || "";
    document.querySelectorAll(".map-zoom button").forEach(function (b) {
      b.setAttribute("aria-pressed", String((b.getAttribute("data-zoom") || "") === state.zoom));
    });
    var sel = $("map-zoom-sel");
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
  function unit() { return view[2] / (canvas.clientWidth || 800); }  // viewBox units per screen pixel
  function radiusPx() { return Math.max(9, Math.min(24, (canvas.clientWidth || 800) * 0.03)); }
  function rOf(n) { return cur.max ? Math.max(3, radiusPx() * Math.sqrt(n / cur.max)) : 0; }

  function buildMap() {
    canvas.textContent = "";
    svg = sv("svg", { "class": "map-svg", "aria-hidden": "true", focusable: "false" });
    var defs = sv("defs", {});
    hatch = sv("pattern", { id: "map-hatch", patternUnits: "userSpaceOnUse", width: 6, height: 6, patternTransform: "rotate(45)" });
    hatch.appendChild(sv("rect", { "class": "map-hb", width: 6, height: 6 }));
    hatchLine = sv("rect", { "class": "map-hl", width: 1, height: 6 });
    hatch.appendChild(hatchLine);
    defs.appendChild(hatch);
    svg.appendChild(defs);
    svg.appendChild(sv("path", { "class": "map-sphere", d: W.sphere }));
    gCountries = sv("g", { "class": "map-countries" });
    Object.keys(W.countries).forEach(function (cc) {
      var c = W.countries[cc];
      if (!c.d) return;
      var p = sv("path", { "class": "map-c" + (member[cc] ? " member" : ""), d: c.d, "data-cc": cc });
      shapes[cc] = p;
      gCountries.appendChild(p);
    });
    if (W.land) gCountries.appendChild(sv("path", { "class": "map-c map-x", d: W.land }));
    svg.appendChild(gCountries);
    gDots = sv("g", { "class": "map-dots" });
    gBubbles = sv("g", { "class": "map-bubbles" });
    gLabels = sv("g", { "class": "map-labels" });  // above every circle, so a small circle never hides a number
    ring = sv("circle", { "class": "map-ring", r: 0 });
    ring.style.display = "none";
    svg.appendChild(gDots);
    svg.appendChild(gBubbles);
    svg.appendChild(gLabels);
    svg.appendChild(ring);
    canvas.appendChild(svg);
    view = target();
    svg.setAttribute("viewBox", view.join(" "));
    Object.keys(shapes).forEach(function (cc) {  // outline sizes, for the places too small to show a hatch
      try { var b = shapes[cc].getBBox(); shapes[cc]._size = Math.max(b.width, b.height); } catch (e) { shapes[cc]._size = 0; }
    });
  }

  function renderMap() {
    if (!W) return;
    Object.keys(shapes).forEach(function (cc) {
      var gap = member[cc] && cur.located > 0 && !cur.counts[cc];
      shapes[cc].classList.toggle("gap", !!gap);
      shapes[cc].classList.toggle("has", !!cur.counts[cc]);
      if (gap) gCountries.appendChild(shapes[cc]);  // drawn last, so the gap outline is not hidden by a neighbour
    });
    gBubbles.textContent = "";
    gLabels.textContent = "";
    var codes = Object.keys(cur.counts).filter(function (cc) { return W.countries[cc]; })
      .sort(function (a, b) { return cur.counts[b] - cur.counts[a]; });
    var labelled = codes.slice(0, 6);
    codes.forEach(function (cc) {
      var c = W.countries[cc].c, g = sv("g", { "class": "map-bg", "data-cc": cc });
      g.appendChild(sv("circle", { "class": "map-hit", cx: c[0], cy: c[1], r: 0 }));
      g.appendChild(sv("circle", { "class": "map-b", cx: c[0], cy: c[1], r: 0 }));
      if (labelled.indexOf(cc) >= 0) {
        var t = sv("text", { "class": "map-bl", x: c[0], y: c[1] });
        t.textContent = num(cur.counts[cc]);
        t._n = cur.counts[cc];
        gLabels.appendChild(t);
      }
      g._n = cur.counts[cc];
      gBubbles.appendChild(g);
    });
    sizeMarks();
    renderLegend();
    if (state.cc) highlight(state.cc);
  }

  function sizeMarks() {  // everything drawn in screen pixels, whatever the zoom
    if (!svg || !cur) return;
    var k = unit();
    [hatch, hatch.firstChild].forEach(function (e) { e.setAttribute("width", 6 * k); e.setAttribute("height", 6 * k); });
    hatchLine.setAttribute("width", 1.1 * k);
    hatchLine.setAttribute("height", 6 * k);
    Array.prototype.forEach.call(gBubbles.children, function (g) {
      var r = rOf(g._n);
      g.children[0].setAttribute("r", Math.max(r, 10) * k);
      g.children[1].setAttribute("r", r * k);
    });
    Array.prototype.forEach.call(gLabels.children, function (t) {
      t.setAttribute("font-size", 11 * k);
      t.style.display = rOf(t._n) >= 12 && String(t._n).length <= 3 ? "" : "none";
    });
    gDots.textContent = "";  // gap marks for member countries too small to show their hatch
    if (cur.located) Object.keys(member).forEach(function (cc) {
      var c = W.countries[cc];
      if (!c || cur.counts[cc] || (shapes[cc] && shapes[cc]._size / k >= 9)) return;
      gDots.appendChild(sv("circle", { "class": "map-gd", cx: c.c[0], cy: c.c[1], r: 4.5 * k, "data-cc": cc }));
    });
    if (ring._cc) placeRing(ring._cc);
  }

  /* legend: what the fills mean, and circle sizes on the current scale */
  function niceDown(v) {
    var p = Math.pow(10, Math.floor(Math.log(v) / Math.LN10)), f = v / p;
    return (f >= 5 ? 5 : f >= 2 ? 2 : 1) * p;
  }
  function renderLegend() {
    legendEl.textContent = "";
    renderSizes();
    var keys = el("ul", "viz-legend map-key");
    [["mk-member", "ISSMGE member-society country"], ["mk-gap", "Member society, no stories in this period"],
     ["mk-other", "Other country"]].forEach(function (x) {
      if (x[0] === "mk-gap" && !cur.located) return;
      var li = el("li");
      li.appendChild(el("i", x[0]));
      li.appendChild(document.createTextNode(x[1]));
      keys.appendChild(li);
    });
    legendEl.appendChild(keys);
  }
  function renderSizes() {
    if (!cur.max) return;
    var vals = [cur.max];
    var mid = niceDown(cur.max / 2);
    if (mid > 1 && mid < cur.max) vals.unshift(mid);
    if (cur.max > 1) vals.unshift(1);
    var box = el("div", "map-sizes"), rmax = rOf(cur.max);
    box.appendChild(el("span", "map-sizes-l", "Stories"));
    vals.forEach(function (v) {
      var r = rOf(v), s = sv("svg", { width: Math.ceil(2 * r + 4), height: Math.ceil(2 * rmax + 4), "aria-hidden": "true" });
      s.appendChild(sv("circle", { "class": "map-b", cx: r + 2, cy: 2 * rmax + 2 - r, r: r }));
      var item = el("span", "map-size");
      item.appendChild(s);
      item.appendChild(el("b", "", num(v)));
      box.appendChild(item);
    });
    legendEl.appendChild(box);
  }

  /* ---------- tooltip (pointer and keyboard) ---------- */
  var tip = el("div", "viz-tip");
  tip.hidden = true;
  tip.setAttribute("aria-hidden", "true");  // the panel, table and live text carry the same details
  document.body.appendChild(tip);
  function showTip(cc, x, y) {
    tip.textContent = "";
    var n = cur.counts[cc] || 0;
    tip.appendChild(el("div", "tt-h", name(cc)));
    var g = el("div", "tt-g");
    function row(color, value, label, on) {
      var k = el("i", "tt-k");
      if (color) k.style.setProperty("--c", color);
      g.appendChild(k);
      g.appendChild(el("b", on ? "on" : "", value));
      g.appendChild(el("span", on ? "on" : "", label));
    }
    row("", num(n), (n === 1 ? "story" : "stories") + (cur.located && n ? " · " + pct(n, cur.located) + " of located" : ""), true);
    var P = cur.P;
    if (n && P.c[cc]) topThemes(P.c[cc], 3).forEach(function (x) {
      if (state.t < 0 || x[1] === state.t) row(D.tc[x[1]], num(x[0]), D.themes[x[1]]);
    });
    tip.appendChild(g);
    tip.appendChild(el("div", "tt-f", statusLine(cc) + (n ? ". Select it to list the stories." : ".")));
    tip.hidden = false;
    var w = tip.offsetWidth, h = tip.offsetHeight, left = x + 14, top = y + 14;
    if (left + w > window.innerWidth - 8) left = x - w - 14;
    if (top + h > window.innerHeight - 8) top = y - h - 14;
    tip.style.left = Math.max(8, left) + "px";
    tip.style.top = Math.max(8, top) + "px";
  }
  function hideTip() { tip.hidden = true; }

  var hover = null;
  function highlight(cc) {
    if (hover && hover !== cc) mark(hover, false);
    hover = cc;
    if (cc) mark(cc, true);
    placeRing(cc);
  }
  function mark(cc, on) {
    if (shapes[cc]) {
      shapes[cc].classList.toggle("on", on);
      if (on) gCountries.appendChild(shapes[cc]);
    }
    if (gBubbles) Array.prototype.forEach.call(gBubbles.children, function (g) {
      if (g.getAttribute("data-cc") === cc) g.classList.toggle("on", on);
    });
  }
  function placeRing(cc) {  // a ring on the country chosen with the keyboard or open in the panel
    if (!ring) return;
    var c = cc && W.countries[cc], show = c && (keyIdx.on || cc === state.cc);
    ring._cc = show ? cc : null;
    if (!show) { ring.style.display = "none"; return; }
    var k = unit(), r = (cur.counts[cc] ? rOf(cur.counts[cc]) : 4.5) + 4;
    ring.setAttribute("cx", c.c[0]);
    ring.setAttribute("cy", c.c[1]);
    ring.setAttribute("r", r * k);
    ring.style.display = "";
  }

  function ccAt(e) {
    var t = e.target.closest ? e.target.closest("[data-cc]") : null;
    return t && canvas.contains(t) ? t.getAttribute("data-cc") : null;
  }
  var touch = false;
  canvas.addEventListener("pointerdown", function (e) { touch = e.pointerType === "touch"; });
  canvas.addEventListener("pointermove", function (e) {
    if (!W) return;
    var cc = ccAt(e);
    keyIdx.on = false;
    if (!cc) { if (hover !== state.cc) highlight(state.cc); hideTip(); return; }
    if (hover !== cc) highlight(cc);
    showTip(cc, e.clientX, e.clientY);
  });
  canvas.addEventListener("pointerleave", function () { if (!touch) { hideTip(); highlight(state.cc); } });
  canvas.addEventListener("click", function (e) {
    var cc = ccAt(e);
    if (cc) { openCountry(cc); if (touch) showTip(cc, e.clientX, e.clientY); }
  });
  document.addEventListener("pointerdown", function (e) { if (!canvas.contains(e.target)) hideTip(); });

  /* keyboard: the arrow keys walk the countries with stories and the member-society countries, west to east */
  var keyIdx = { i: -1, on: false };
  function keyOrder() {
    var list = Object.keys(cur.counts);
    Object.keys(member).forEach(function (m) { if (!cur.counts[m]) list.push(m); });
    return list.filter(function (cc) { return W.countries[cc]; })
      .sort(function (a, b) { return W.countries[a].c[0] - W.countries[b].c[0]; });
  }
  canvas.addEventListener("keydown", function (e) {
    if (!W) return;
    var list = keyOrder(), step = { ArrowRight: 1, ArrowDown: 1, ArrowLeft: -1, ArrowUp: -1 }[e.key];
    if (e.key === "Escape") { hideTip(); keyIdx.on = false; highlight(state.cc); live.textContent = ""; return; }
    if ((e.key === "Enter" || e.key === " ") && keyIdx.on && list[keyIdx.i]) { e.preventDefault(); openCountry(list[keyIdx.i], true); return; }
    if (!step || !list.length) return;
    e.preventDefault();
    var at = keyIdx.on ? list.indexOf(hover) : -1;
    keyIdx.i = at < 0 ? (step > 0 ? 0 : list.length - 1) : (at + step + list.length) % list.length;
    keyIdx.on = true;
    var cc = list[keyIdx.i];
    highlight(cc);
    var rect = canvas.getBoundingClientRect(), c = W.countries[cc].c;
    showTip(cc, rect.left + (c[0] - view[0]) / unit(), rect.top + (c[1] - view[1]) / unit());
    var n = cur.counts[cc] || 0;
    live.textContent = name(cc) + ": " + plural(n, "story", "stories") + ". " + statusLine(cc) + ".";
  });
  canvas.addEventListener("blur", function () { hideTip(); keyIdx.on = false; if (hover !== state.cc) highlight(state.cc); });

  /* ---------- controls ---------- */
  function renderAll() {
    compute();
    renderFigures();
    renderRegions();
    renderTable();
    renderMap();
    if (state.cc) openCountry(state.cc); else renderRanking();
  }
  var periodSel = $("map-period"), themeSel = $("map-theme");
  periodSel.addEventListener("change", function () {
    var i = D.periods.map(function (p) { return p.k; }).indexOf(periodSel.value);
    state.p = i < 0 ? 0 : i;
    renderAll();
  });
  themeSel.addEventListener("change", function () { state.t = +themeSel.value; renderAll(); });
  document.addEventListener("click", function (e) {
    var z = e.target.closest ? e.target.closest("[data-zoom]") : null;
    if (z) {
      var region = z.getAttribute("data-zoom") || "";
      if (z.classList.contains("mr-zoom")) { showView(false); $("map-fig").scrollIntoView({ behavior: reduceMotion ? "auto" : "smooth", block: "start" }); }
      zoomTo(region);
      return;
    }
    var b = e.target.closest ? e.target.closest("button.map-cc") : null;
    if (b) {
      var cc = b.getAttribute("data-cc");
      if (b.closest("#map-table")) {
        showView(false);
        $("map-fig").scrollIntoView({ behavior: reduceMotion ? "auto" : "smooth", block: "start" });
      }
      openCountry(cc, true);
    }
  });
  var zoomSel = $("map-zoom-sel");
  if (zoomSel) zoomSel.addEventListener("change", function () { zoomTo(zoomSel.value); });

  var fig = $("map-fig"), toggle = fig.querySelector(".viz-toggle");
  function showView(table) {
    fig.querySelector(".viz-chart").hidden = table;
    $("map-table").hidden = !table;
    toggle.querySelectorAll("button").forEach(function (x) {
      x.setAttribute("aria-pressed", String((x.getAttribute("data-view") === "table") === table));
    });
    hideTip();
    if (!table && W) requestAnimationFrame(function () { setView(target()); });
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
      renderLegend();
    });
  });

  /* ---------- start ---------- */
  compute();
  renderLegend();
  function syncMenus() {  // a browser may bring back the last choices (reload, Back): show what the menus say
    var p = Math.max(0, D.periods.map(function (x) { return x.k; }).indexOf(periodSel.value));
    var t = themeSel.value === "" || isNaN(+themeSel.value) ? -1 : +themeSel.value;
    if (p !== state.p || t !== state.t) { state.p = p; state.t = t; renderAll(); }
  }
  window.addEventListener("pageshow", syncMenus);
  window.addEventListener("load", syncMenus);
  fetch(root + "assets/world.json").then(function (r) {
    if (!r.ok) throw new Error("status " + r.status);
    return r.json();
  }).then(function (w) {
    W = w;
    buildMap();
    renderMap();
  }).catch(function () {
    canvas.textContent = "";
    canvas.appendChild(el("p", "map-loading", "The map could not be loaded. The Table button lists every country, and the regions below give the same figures."));
  });
})();
