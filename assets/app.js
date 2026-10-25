/* Geotechnical News Desk — filters, archive search, Scan now and issue brief buttons, and AI assistant. */
(function () {
  "use strict";
  var root = document.body.getAttribute("data-root") || "";
  var repo = document.body.getAttribute("data-repo") || "";

  function esc(s) {
    return String(s == null ? "" : s).replace(/[&<>"']/g, function (c) {
      return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c];
    });
  }
  /* small per-browser preferences (no keys are stored); storage can be unavailable (private mode) */
  var store = {
    get: function (k) { try { return localStorage.getItem(k) || ""; } catch (e) { return ""; } },
    set: function (k, v) { try { v ? localStorage.setItem(k, v) : localStorage.removeItem(k); } catch (e) { /* ignore */ } }
  };
  var KEYS = { model: "gnd_model", scan: "gnd_scan_started", brief: "gnd_brief_started", passcode: "gnd_passcode",
    events: "gnd_events_started", weekly: "gnd_weekly_started" };

  function fmt(iso) {
    if (!iso) return "";
    var d = new Date(iso.slice(0, 10) + "T00:00:00Z");
    return d.toLocaleDateString("en-GB", { day: "numeric", month: "short", year: "numeric", timeZone: "UTC" });
  }

  /* ---------- toast ---------- */
  var toastEl = document.getElementById("toast"), toastTimer;
  /* owner: the storage key of the run being followed; closing its message stops following */
  function toast(html, kind, sticky, owner) {
    if (!toastEl) return;
    toastEl.className = "toast" + (kind ? " " + kind : "");
    toastEl.innerHTML = html + "<button type='button' class='toast-x' aria-label='Close'>×</button>";
    toastEl.hidden = false;
    toastEl.dataset.owner = owner || "";
    clearTimeout(toastTimer);
    if (!sticky) toastTimer = setTimeout(function () { toastEl.hidden = true; }, 9000);
  }
  if (toastEl) toastEl.addEventListener("click", function (e) {
    if (e.target.classList.contains("toast-x")) { toastEl.hidden = true; if (toastEl.dataset.owner) store.set(toastEl.dataset.owner, ""); }
  });

  /* ---------- Scan now and Generate / update brief ----------
     Starting a GitHub workflow needs a signed-in GitHub user, so these buttons open the
     workflow's page on GitHub (where you are signed in) and this page then follows the
     run through GitHub's public API and says when it has finished. */
  var WORKFLOWS = {
    scan: { file: "scan.yml", key: KEYS.scan, button: "Scan now", noun: "scan", minutes: "3–4",
      wait: "This page will follow the scan and tell you when the new digest is ready.",
      done: "Scan finished. The website refreshes about a minute later — <a href='#' class='reload-link'>reload the page</a>." },
    brief: { file: "brief.yml", key: KEYS.brief, button: "Generate / update brief", noun: "issue brief", minutes: "3–6",
      wait: "This page will follow Claude while it drafts the brief and tell you when the Word file is ready.",
      done: "The issue brief is ready. The website refreshes about a minute later — <a href='#' class='reload-link'>reload the page</a> to download it." },
    /* task: the "What to do" choice; extras.yml names each run after it, so a run of the other task is not taken for this one */
    events: { file: "extras.yml", task: "refresh the events calendar", key: KEYS.events, button: "Refresh calendar", noun: "calendar refresh", minutes: "3–6",
      wait: "This page will follow Claude while it reads the organisers' calendars and tell you when the calendar is updated.",
      done: "The events calendar is updated. The website refreshes about a minute later — <a href='#' class='reload-link'>reload the page</a>." },
    weekly: { file: "extras.yml", task: "send the weekly summary now", key: KEYS.weekly, button: "Send summary now", noun: "weekly summary", minutes: "1–2",
      wait: "This page will follow the run and tell you when the e-mail has gone.",
      done: "The weekly summary was sent. The website refreshes about a minute later — <a href='#' class='reload-link'>reload the page</a>." }
  };
  function ghPage(w) { return "https://github.com/" + repo + "/actions/workflows/" + w.file; }

  /* how prompt: what to do on the GitHub page before pressing the green button */
  function follow(w, btn, started, how) {
    var page = ghPage(w), noun = w.noun.charAt(0).toUpperCase() + w.noun.slice(1);
    var runs = "https://api.github.com/repos/" + repo + "/actions/workflows/" + w.file + "/runs?per_page=5";
    function setRunning(on) { if (btn) btn.classList.toggle("running", on); }
    function stop() { store.set(w.key, ""); setRunning(false); }
    function say(html, kind) { toast(html, kind, true, w.key); }
    setRunning(true);
    var tick = function () {
      fetch(runs, { headers: { Accept: "application/vnd.github+json" } }).then(function (r) {
        if (!r.ok) throw new Error("status " + r.status);
        return r.json();
      }).then(function (j) {
        if (!store.get(w.key)) { setRunning(false); return; }  // dismissed
        var dispatched = (j.workflow_runs || []).filter(function (x) {
          return x.event === "workflow_dispatch" && new Date(x.created_at).getTime() >= started - 60000;
        });  // newest first
        var run = dispatched.filter(function (x) { return !w.task || x.display_title === w.task; })[0];
        var other = !run && w.task ? dispatched[0] : null;  // the same workflow, run for its other task
        var mins = Math.max(0, Math.round((Date.now() - started) / 60000));
        if (!run) {
          if (Date.now() - started > 10 * 60000) {
            stop();
            toast("No " + w.noun + " was started on GitHub. Press <b>" + w.button + "</b> again, then <b>Run workflow</b> on the GitHub page.", "err", true);
            return;
          }
          say((other ? "The run started on GitHub is “" + esc(other.display_title) + "”, not the " + w.noun + ". " +
              "On the GitHub tab, press <b>Run workflow</b> again" : "On the GitHub tab, press <b>Run workflow</b>") +
            (how ? ", " + how + "," : "") + " and then the green <b>Run workflow</b> button. " +
            w.wait + " <a href='" + page + "' target='_blank' rel='noopener'>Open GitHub again</a>", other ? "err" : "");
        } else if (run.status !== "completed") {
          say(noun + " " + (run.status === "queued" ? "queued" : "running") + " · " + mins + " min so far. It usually takes " + w.minutes + " minutes. " +
            "<a href='" + esc(run.html_url) + "' target='_blank' rel='noopener'>Watch on GitHub</a>", "");
        } else {
          stop();
          if (run.conclusion === "success") toast(w.done, "ok", true);
          else toast("The " + w.noun + " ended with “" + esc(run.conclusion) + "”. <a href='" + esc(run.html_url) + "' target='_blank' rel='noopener'>See the log on GitHub</a>.", "err", true);
          return;
        }
        if (Date.now() - started < 25 * 60000) setTimeout(tick, 20000);
        else stop();
      }).catch(function () {
        // GitHub allows 60 public API calls an hour; if they run out, stop following quietly
        stop();
        toast("This page can't follow the " + w.noun + " right now. <a href='" + page + "' target='_blank' rel='noopener'>Check its progress on GitHub</a>.", "", true);
      });
    };
    tick();
  }

  function startButton(w, btn, how) {
    if (btn) btn.addEventListener("click", function () {
      window.open(ghPage(w), "_blank", "noopener");
      var started = Date.now();
      store.set(w.key, String(started));
      follow(w, btn, started, how);
    });
    var pending = +store.get(w.key);  // a run started on another page or before a reload
    if (pending && Date.now() - pending < 25 * 60000) follow(w, btn, pending, how);
  }

  startButton(WORKFLOWS.scan, document.getElementById("scan-btn"), "");
  var briefBtn = document.getElementById("brief-btn");
  startButton(WORKFLOWS.brief, briefBtn, !briefBtn ? "enter the issue window unless it is the current quarter"
    : briefBtn.getAttribute("data-current") ? "leave <b>Issue window</b> empty for the current quarter"
    : "type <b>" + esc(briefBtn.getAttribute("data-window")) + "</b> under <b>Issue window</b> (and tick <b>Final</b> if the quarter has closed)");
  startButton(WORKFLOWS.events, document.getElementById("events-btn"), "choose <b>refresh the events calendar</b> under <b>What to do</b>");
  startButton(WORKFLOWS.weekly, document.getElementById("weekly-btn"), "choose <b>send the weekly summary now</b> under <b>What to do</b>");
  document.addEventListener("click", function (e) {
    if (e.target.classList && e.target.classList.contains("reload-link")) { e.preventDefault(); location.reload(); }
  });

  /* ---------- filters on digest and issue pages ---------- */
  document.querySelectorAll(".js-filter").forEach(function (bar) {
    var scope = bar.parentNode;
    var text = bar.querySelector(".f-text"), rel = bar.querySelector(".f-rel"), use = bar.querySelector(".f-use");
    var count = bar.querySelector(".f-count");
    var cards = Array.prototype.slice.call(scope.querySelectorAll(".theme-section .story"));
    function apply() {
      var q = text.value.trim().toLowerCase(), min = +rel.value, u = use.value, shown = 0;
      cards.forEach(function (c) {
        var ok = +c.dataset.rel >= min && (!u || c.dataset.use === u) && (!q || c.dataset.text.indexOf(q) !== -1);
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

  /* ---------- archive data (search page and assistant) ---------- */
  var archivePromise, COUNTRY_NAMES = {};
  function getJSON(path) {
    return fetch(root + path).then(function (r) { if (!r.ok) throw new Error("status " + r.status); return r.json(); });
  }
  function loadArchive() {
    if (!archivePromise) {
      archivePromise = fetch(root + "exports/index.json").then(function (r) { return r.json(); }).then(function (windows) {
        return Promise.all(windows.map(function (w) {
          return fetch(root + "exports/" + w.key + ".json").then(function (r) { return r.json(); });
        })).then(function (lists) { return { windows: windows, stories: [].concat.apply([], lists) }; });
      }).then(function (data) {
        // English names of the countries stories are about (an older site has none: the codes are shown)
        return getJSON("exports/countries.json").then(function (names) { COUNTRY_NAMES = names || {}; })
          .catch(function () { /* codes only */ }).then(function () { return data; });
      });
    }
    return archivePromise;
  }
  function windowLabel(key) { var p = key.split("-"); return p[1] + " " + p[0]; }
  function countryName(cc) { return cc ? COUNTRY_NAMES[cc] || cc : ""; }
  function placeText(s) {  // "Moniquirá, Boyacá, Colombia": where it happened, as Claude read it
    var place = String(s.pl || "").trim(), country = countryName(s.cc);
    if (country && place.toLowerCase().indexOf(country.toLowerCase()) !== -1) country = "";
    return [place, country].filter(Boolean).join(", ");
  }
  var PIN = "<svg class='ico' viewBox='0 0 24 24' fill='none' stroke='currentColor' stroke-width='2' stroke-linecap='round' " +
    "stroke-linejoin='round' aria-hidden='true'><path d='M20 10c0 6-8 12-8 12s-8-6-8-12a8 8 0 0 1 16 0Z'/><circle cx='12' cy='10' r='3'/></svg>";
  var CHECK = "<svg class='ico' viewBox='0 0 24 24' fill='none' stroke='currentColor' stroke-width='2' stroke-linecap='round' " +
    "stroke-linejoin='round' aria-hidden='true'><path d='m9 11 3 3L22 4'/><path d='M21 12v7a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h11'/></svg>";

  function isPaper(s) { return s.kind === "paper"; }
  function card(s) {
    var paper = isPaper(s), title = s.te || s.t, rel = s.r
      ? "<span class='rel rel-" + s.r + "' title='" + (paper ? "Use in practice: " : "Geotechnical relevance: ") + s.r + " of 5'><i></i><i></i><i></i><i></i><i></i><b>" + s.r + "/5</b></span>"
      : "<span class='rel rel-kw'>" + (paper ? "Not rated" : "Keyword-ranked") + "</span>";
    var meta = ["<span class='src'>" + esc(s.s) + "</span>"], where = placeText(s);
    if (s.p) meta.push("<time>" + esc(fmt(s.p)) + "</time>");
    if (where) meta.push("<span class='loc'>" + PIN + esc(where) + "</span>");
    if (s.c && s.c !== countryName(s.cc)) meta.push("<span>" + esc(s.c) + " edition</span>");
    var useSlug = s.u ? s.u.split(" ")[0].toLowerCase().replace(/-+$/, "") : "";
    var tc = THEME_COLORS[s.th] || "#64748b";
    var href = /^https?:\/\//i.test(s.l || "") ? s.l : "#";
    // the developing story it belongs to, as on the story cards of the digest and issue pages
    var chip = s.sl && s.st ? "<a class='sl-chip' href='" + root + "developing.html#" + esc(encodeURIComponent(s.sl)) + "' title='" + esc(s.st) + "'>" +
      "Developing story · " + esc(s.sz || 2) + " reports" + (s.sg && s.sg !== "Event" ? " · " + esc(s.sg) : "") + "</a>" : "";
    // only what identifies the article (headline, source, link) and what Claude wrote: never the publisher's text
    return "<article class='story' style='--tc:" + tc + "'><div class='story-top'><a class='story-title' dir='auto' href='" + esc(href) + "' target='_blank' rel='noopener'>" +
      esc(title) + "</a>" + rel + "</div>" +
      (s.te ? "<div class='orig'><span class='tr-tag'>English headline translated by Claude</span> · Original: <span dir='auto'>" + esc(s.t) + "</span></div>" : "") +
      (paper && s.au ? "<div class='orig' dir='auto'>" + esc(s.au) + "</div>" : "") +
      (s.a ? "<p class='angle'><span>" + (paper ? "Why it matters in practice" : "Magazine angle") + "</span>" + esc(s.a) + "</p>" : "") +
      (s.ps ? "<p class='check-with'>" + CHECK + "<span><b>Check with:</b> " + esc(s.ps) + "</span></p>" : "") +
      "<div class='story-meta'>" + (paper ? "<span class='badge'>Research paper</span>" : "") + chip +
      (s.u ? "<span class='use use-" + esc(useSlug) + "'>" + esc(s.u) + "</span>" : "") +
      "<span class='theme-tag'>" + esc(s.th) + "</span>" + meta.join(" · ") + "</div>" +
      (s.k && s.k.length ? "<div class='kw'>" + s.k.slice(0, 5).map(function (k) { return "<span>" + esc(k) + "</span>"; }).join("") + "</div>" : "") +
      "<div class='found'>Found in the <a href='" + root + "digests/" + esc(s.d) + ".html'>" + esc(fmt(s.d)) + " digest</a> · " +
      "<a href='" + root + "issues/" + esc(s.w) + ".html'>" + esc(windowLabel(s.w)) + " window</a></div></article>";
  }
  var THEME_COLORS = {
    "Sustainability & the Energy Transition": "#1f9d63", "Digital Geotechnics": "#6b4fd6", "Hazards & Resilience": "#e04f2c",
    "Ground Improvement & Innovation": "#d38b00", "Infrastructure & the Underground City": "#2563d6",
    "Offshore, Coasts & Water": "#0b97a5", "Characterisation & Modelling": "#c23d7b", "Geotechnics & Society": "#8a5a2b", "General": "#64748b"
  };

  /* ---------- archive search ---------- */
  var app = document.getElementById("search-app");
  if (app) (function () {
    var els = {};
    ["q", "q_window", "q_theme", "q_use", "q_rel", "q_sort"].forEach(function (id) { els[id] = document.getElementById(id); });
    var results = document.getElementById("results"), countEl = document.getElementById("result-count");
    var moreBtn = document.getElementById("more"), exportBtn = document.getElementById("export");
    var all = [], matches = [], limit = 50;
    var params = new URLSearchParams(location.search);
    Object.keys(els).forEach(function (id) { if (params.get(id)) els[id].value = params.get(id); });

    function run() {
      var words = els.q.value.trim().toLowerCase().split(/\s+/).filter(Boolean);
      var w = els.q_window.value, th = els.q_theme.value, u = els.q_use.value, min = +els.q_rel.value;
      matches = all.filter(function (s) {
        if (w && s.w !== w) return false;
        if (th && s.th !== th) return false;
        if (u && s.u !== u) return false;
        if (s.r < min) return false;
        if (!words.length) return true;
        return words.every(function (x) { return hay(s).indexOf(x) !== -1; });
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
    function n(k, one, many) { return k + " " + (k === 1 ? one : many); }
    function tally(list) {  // "3 stories", "2 research papers" or "3 stories and 2 research papers"
      var p = list.filter(isPaper).length, parts = [];
      if (list.length - p || !p) parts.push(n(list.length - p, "story", "stories"));
      if (p) parts.push(n(p, "research paper", "research papers"));
      return parts.join(" and ");
    }
    function draw() {
      var papers = all.some(isPaper);
      countEl.textContent = tally(matches) + " found in " + (papers ? "the archive's " + tally(all) : all.length + " archived");
      results.innerHTML = matches.length ? matches.slice(0, limit).map(card).join("")
        : "<p class='empty'>No " + (papers ? "stories or research papers" : "stories") + " match these filters.</p>";
      moreBtn.hidden = matches.length <= limit;
    }
    function csvCell(v) {
      v = String(v == null ? "" : v);
      if (/^[=+\-@]/.test(v)) v = "'" + v;  // spreadsheets would run it as a formula
      return /[",\n]/.test(v) ? '"' + v.replace(/"/g, '""') + '"' : v;
    }
    exportBtn.addEventListener("click", function () {
      // the columns of the issue pages' CSV files (site_builder.CSV_FIELDS)
      var head = ["Digest date", "Issue window", "Theme", "Relevance (1-5)", "Suggested use", "Headline (English or Claude's translation)",
        "Original headline", "Magazine angle", "Primary source to check", "Source", "Country", "Place", "Google News edition", "Published",
        "Developing story", "Link", "Keywords"];
      var rows = matches.map(function (s) {
        return [s.d, s.w, s.th, s.r || "", s.u, s.te || s.t, s.te ? s.t : "", s.a, s.ps, s.s, countryName(s.cc), s.pl, s.c, s.p,
          s.st ? s.st + (s.sg ? " · " + s.sg : "") : "", s.l, (s.k || []).join(", ")].map(csvCell).join(",");
      });
      var blob = new Blob(["﻿" + [head.join(",")].concat(rows).join("\r\n")], { type: "text/csv;charset=utf-8" });
      var a = document.createElement("a");
      a.href = URL.createObjectURL(blob);
      a.download = "geotech-news-search.csv";
      document.body.appendChild(a); a.click(); a.remove();
    });
    moreBtn.addEventListener("click", function () { limit += 50; draw(); });
    Object.keys(els).forEach(function (id) { els[id].addEventListener("input", run); });
    loadArchive().then(function (data) { all = data.stories; run(); }).catch(function () {
      countEl.textContent = "The archive could not be loaded. If you opened this file from disk, view it on the published website instead.";
    });
  })();

  function hay(s) {
    return s._hay || (s._hay = [s.t, s.te, s.a, s.ps, s.s, s.c, s.th, s.u, (s.k || []).join(" "), placeText(s), s.st].join(" ").toLowerCase());
  }

  /* ---------- AI assistant ---------- */
  var chat = document.getElementById("chat-app");
  if (chat) (function () {
    var log = document.getElementById("chat-log"), form = document.getElementById("chat-form");
    var input = document.getElementById("chat-text"), fileInput = document.getElementById("chat-file");
    var filesEl = document.getElementById("chat-files"), statusEl = document.getElementById("chat-status");
    var history = [], pendingFiles = [], reading = [], busy = false, archive = null, systemText = "", conversation = 0;
    var MAX_FILE_MB = 15, MAX_TOTAL_MB = 18;  // the connector accepts 25 MB per question and PDFs grow by a third when encoded
    var MODEL_NAMES = { "claude-opus-5-5": "Claude Opus 5.5", "claude-sonnet-5-5": "Claude Sonnet 5.5", "claude-haiku-5-5": "Claude Haiku 5.5" };
    var STOP = "the and for with from that this what which about are was were have has into over under than then them they their there these those who why how can could would should will may might any all some most more best find show give tell list stories story news latest recent please quarter issue window themes theme magazine suggest recommend article articles also just like make need want get our you your".split(" ");

    var endpoint = document.body.getAttribute("data-assistant") || "";
    var modelSel = document.getElementById("chat-model");
    var bridge = null;  // health report from the bridge
    if (modelSel) {
      modelSel.value = store.get(KEYS.model) || "claude-sonnet-5-5";
      modelSel.addEventListener("change", function () { store.set(KEYS.model, modelSel.value); refreshStatus(); });
    }
    function model() { return (modelSel && modelSel.value) || "claude-sonnet-5-5"; }
    function refreshStatus() {
      if (!endpoint) {
        statusEl.innerHTML = "<b>The assistant is not connected yet.</b>";
        return;
      }
      var parts = [];
      if (bridge && bridge.ok) parts.push("Connected");
      else if (bridge && bridge.problem) parts.push("<b>Connection problem:</b> " + esc(bridge.problem));
      else parts.push("Connecting…");
      if (bridge && bridge.dailyLimit) parts.push(Math.max(0, bridge.dailyLimit - bridge.usedToday) + " of " + bridge.dailyLimit + " questions left today");
      parts.push(archive ? archive.stories.length + " archived stories" : "loading archive…");
      statusEl.innerHTML = parts.join(" · ");
    }
    refreshStatus();

    if (!endpoint) {
      addMsg("bot", "<p><b>Almost ready.</b> The assistant uses your Anthropic key through a small connector in your own Google account, " +
        "so no key is ever typed into or stored on this website. Once the connector is set up (a one-time, 5-minute step described in the " +
        "repository's README under <i>AI assistant</i>), questions can be asked here.</p>");
      form.querySelector("textarea").disabled = true;
      form.querySelector(".send").disabled = true;
    } else {
      fetch(endpoint).then(function (r) { return r.json(); }).then(function (j) {
        bridge = j;
        refreshStatus();
        if (!j.ok) addMsg("bot", "<p><b>The connector answered, but reports a problem:</b></p><p>" + esc(j.problem || "unknown problem") + "</p>", "err");
      }).catch(function () {
        bridge = { ok: false, problem: "the connector did not answer." };
        refreshStatus();
        addMsg("bot", "<p><b>The connector did not answer.</b> In Google Apps Script open <b>Deploy → Manage deployments</b> and check that " +
          "the web app has <b>Execute as: Me</b> and <b>Who has access: Anyone</b> (not “Anyone with a Google account”), and that " +
          "the address in <code>config.yaml</code> is the one ending in <code>/exec</code>.</p>", "err");
      });
    }

    loadArchive().then(function (data) {
      archive = data;
      systemText = buildSystem(data);
      refreshStatus();
    }).catch(function () { statusEl.textContent = "The archive could not be loaded; the assistant can still read attached documents."; systemText = buildSystem({ windows: [], stories: [] }); });
    // the events calendar (docs/exports/events.json), for questions about conferences and deadlines
    var calendar = null;
    var calendarPromise = getJSON("exports/events.json").then(function (j) {
      calendar = j && Array.isArray(j.events) ? j : null;
      systemText = buildSystem(archive || { windows: [], stories: [] });
    }).catch(function () { /* the assistant works without it */ });

    function clip(text, n) { text = String(text == null ? "" : text); return text.length > n ? text.slice(0, n - 1) + "…" : text; }

    /* the magazine's copyright-safe way of using a story (the Method page's "Before you use a story"), as rules for Claude */
    var COPYRIGHT_RULES = "Copyright and sources: strict rules of the ISSMGE Magazine, which apply to every answer.\n" +
      "- Every story is a lead, not a source. You know each story only from its line below (headline, source, link and the news desk's " +
      "own notes: angle, place, primary source); you have not read the article. Never present anything else as what the article says, " +
      "and never invent quotations, figures or names.\n" +
      "- Answer and draft in your own words, from the facts. Never reproduce article text, abstracts or paywalled content, and do not " +
      "closely paraphrase them; the same holds for documents the editor attaches that others wrote (a call for papers, a report), " +
      "which you summarise in your own words.\n" +
      "- Quote at most one or two sentences from any source, in quotation marks, naming the publication and linking to it.\n" +
      "- Always list your sources, each with its link: the story's headline as a markdown link to its URL, with the publication and date.\n" +
      "- Name the primary source the editor should check the facts with before publishing: the story's \"check with\" when it has one, " +
      "otherwise the authority, project owner, company (its press release) or official report most likely to confirm them.\n" +
      "- When asked to draft a magazine piece (a news brief, a feature, an introduction or similar), end the draft with a short list headed " +
      "\"Check before publishing\": the facts and figures to confirm with the primary source, any quotes to verify against the original, " +
      "and the image rights to clear.\n" +
      "- Images: recommend the editor's own photos, the project's press-kit photos released for media use, or asking the rights holder " +
      "for permission. Never suggest reusing a source's photos, figures or drawings.";

    /* the developing stories in the archive (reports sharing a storyline id), most recently active first */
    function storylines() {
      if (!archive) return [];
      if (archive._lines) return archive._lines;
      var by = {}, out = [];
      archive.stories.forEach(function (s) {
        if (!s.sl || isPaper(s)) return;
        var g = by[s.sl];
        if (!g) { g = by[s.sl] = { id: s.sl, title: s.st || "", reports: [], seen: {} }; out.push(g); }
        var key = s.id || s.l;
        if (g.seen[key]) return;  // a story kept in two digests counts once
        g.seen[key] = 1;
        g.reports.push(s);
      });
      function day(s) { return s.p || s.d || ""; }
      archive._lines = out.filter(function (g) { return g.reports.length >= 2; }).map(function (g) {
        g.reports.sort(function (a, b) { return day(a) < day(b) ? -1 : day(a) > day(b) ? 1 : 0; });
        g.first = day(g.reports[0]);
        g.last = day(g.reports[g.reports.length - 1]);
        g.where = g.reports.map(placeText).filter(Boolean).pop() || "";
        return g;
      }).sort(function (a, b) { return a.last < b.last ? 1 : a.last > b.last ? -1 : 0; });
      return archive._lines;
    }
    function storylineHead(g) {
      return g.title + (g.where ? " | " + g.where : "") + " | " + g.reports.length + " reports, " + g.first + " to " + g.last +
        " | latest stage: " + (g.reports[g.reports.length - 1].sg || "Update");
    }
    function eventsText() {
      if (!calendar) return "Events calendar: not available.";
      var coming = calendar.events.filter(function (e) { return e && e.status !== "past"; }).slice(0, 40);
      var lines = coming.map(function (e) {
        var where = [e.city, e.country_name].filter(Boolean).join(", ");
        where = e.online ? (where ? where + " and online" : "Online") : where;
        var open = (e.deadlines || []).filter(function (d) { return d && !d.passed; })
          .map(function (d) { return d.label + " " + d.date; }).join("; ");
        return "- " + e.start + (e.end && e.end !== e.start ? " to " + e.end : "") + " | " + clip(e.name, 160) +
          (e.short && String(e.name).indexOf(e.short) === -1 ? " (" + e.short + ")" : "") + " | " + (where || "place to be announced") +
          " | " + e.kind + (e.status === "under way" ? " | under way" : "") + (e.organiser ? " | " + clip(e.organiser, 80) : "") +
          (open ? " | open deadlines: " + open : "") + (e.url ? " | " + e.url : "");
      });
      return "Events calendar (the website's Events page as built on " + calendar.built + (calendar.updated ? ", last refreshed " +
        String(calendar.updated).slice(0, 10) : "") + "), upcoming and current events, soonest first, with their open call-for-papers deadlines:\n" +
        (lines.join("\n") || "- (none)");
    }

    function buildSystem(data) {
      var lines = data.windows.map(function (w) {
        var themes = {};
        data.stories.forEach(function (s) { if (s.w === w.key) themes[s.th] = (themes[s.th] || 0) + 1; });
        return "- " + w.label + " (" + w.span + "): " + w.stories + " stories — " +
          Object.keys(themes).sort(function (a, b) { return themes[b] - themes[a]; }).map(function (t) { return t + " " + themes[t]; }).join(", ");
      });
      var developing = storylines().slice(0, 25).map(function (g) { return "- " + storylineHead(g); });
      return "You are the AI assistant of the Geotechnical News Desk, the news-monitoring website of the ISSMGE Magazine " +
        "(International Society for Soil Mechanics and Geotechnical Engineering). The person you are helping is an editor of the magazine, " +
        "which is published every three months and read by practising geotechnical engineers and academics worldwide.\n\n" +
        "You help the editor search the archive of news stories collected by the daily scans, spot trends, and recommend stories, themes " +
        "and angles for upcoming issues. The magazine's cross-cutting themes are: " + Object.keys(THEME_COLORS).filter(function (t) { return t !== "General"; }).join("; ") +
        ". Each story may carry a suggested use: News brief, Feature lead, Academia-to-Industry topic, Regional insight or Watch only, " +
        "and a geotechnical relevance rating from 1 to 5 (0 means it was ranked by keywords only and not reviewed by AI).\n\n" +
        "Archive overview by issue window:\n" + (lines.join("\n") || "- (archive empty)") + "\n\n" +
        "With each question you receive the archive stories most relevant to it, retrieved from the full archive. Base what you say about the " +
        "news on those stories. When you mention a story, give its headline as a markdown link to its URL, followed by the source and date. " +
        "If the retrieved stories do not cover what was asked, say so plainly and suggest a search term or filter for the Search page. " +
        "Each story line gives where it happened (place and country, as read from the story) when known, and the primary source to check " +
        "the facts with (\"check with\") when the news desk named one. A headline marked \"Claude's translation\" is the news desk's English " +
        "translation of a foreign headline: say so if you quote it.\n\n" +
        COPYRIGHT_RULES + "\n\n" +
        "Developing stories are events, projects or sites reported more than once (a failure, then the inquiry, then the repair). When asked " +
        "for the latest on one, give its reports in date order with the stage each reached, from the developing stories retrieved with the " +
        "question, and link the Developing stories page (developing.html). The most recently active:\n" +
        (developing.join("\n") || "- (none yet)") + "\n\n" +
        "For questions about conferences, events or call-for-papers deadlines, answer from the events calendar below: give the dates, the " +
        "place and the event's link, and remind the editor to check dates on the event's own website. Do not add events that are not listed.\n" +
        eventsText() + "\n\n" +
        "The editor may attach PDF or Word documents such as calls for papers, article drafts or reports. Read them and relate them to the " +
        "archive when that helps.\n\nWrite in clear British English, with short paragraphs and bullet lists where they help.";
    }

    /* pick the stories most relevant to a question */
    function retrieve(question) {
      var stories = archive ? archive.stories : [];
      var q = question.toLowerCase();
      var wkey = "";
      var m = q.match(/q\s*([1-4])\s*(20\d\d)/);
      if (m) wkey = m[2] + "-Q" + m[1];
      else if (/this quarter|current (issue|window|quarter)|this issue|next issue|upcoming issue/.test(q) && archive && archive.windows.length) wkey = archive.windows[0].key;
      var words = (q.match(/[\p{L}\p{N}][\p{L}\p{N}-]{2,}/gu) || []).filter(function (w) { return STOP.indexOf(w) === -1; });
      var pool = wkey ? stories.filter(function (s) { return s.w === wkey; }) : stories;
      if (!pool.length) pool = stories;
      var scored = pool.map(function (s) {
        var h = hay(s), hits = 0;
        words.forEach(function (w) { if (h.indexOf(w) !== -1) hits++; });
        return { s: s, hits: hits, score: hits * 100 + s.r * 10 + Math.min(s.rk, 99) / 10 };
      });
      var matched = scored.filter(function (x) { return x.hits; }).sort(function (a, b) { return b.score - a.score; }).slice(0, 120);
      var seen = {};
      matched.forEach(function (x) { seen[x.s.l] = 1; });
      var fill = scored.filter(function (x) { return !seen[x.s.l]; }).sort(function (a, b) { return b.score - a.score; })
        .slice(0, Math.max(30, 150 - matched.length));
      var chosen = matched.concat(fill);
      var text = chosen.map(function (x, i) {
        var s = x.s, where = placeText(s);
        return "[" + (i + 1) + "] " + (s.p || s.d) + " | " + windowLabel(s.w) + " | " + s.th + " | " + (s.r ? s.r + "/5" : "keyword-ranked") +
          (s.u ? " | " + s.u : "") + " | " + (s.te || s.t) + (s.te ? " (Claude's translation; original: " + s.t + ")" : "") +
          (s.a ? " | angle: " + s.a : "") + " | " + s.s + (where ? " | where: " + where : "") + (s.c ? " | " + s.c + " edition" : "") +
          (s.ps ? " | check with: " + s.ps : "") +
          (s.st ? " | developing story: " + s.st : "") + ((s.k && s.k.length) ? " | keywords: " + s.k.join(", ") : "") + " | " + s.l;
      }).join("\n");
      // the developing stories the question names (title words count most): their whole timeline, so
      // "What is the latest on …?" can be answered in order
      var named = words.length ? storylines().map(function (g) {
        var title = g.title.toLowerCase(), all = title + " " + g.reports.map(hay).join(" "), inTitle = 0, inAll = 0;
        words.forEach(function (w) { if (title.indexOf(w) !== -1) inTitle++; if (all.indexOf(w) !== -1) inAll++; });
        return { g: g, inTitle: inTitle, score: inTitle * 3 + inAll };
      }).filter(function (x) { return x.inTitle || x.score >= Math.max(2, Math.ceil(words.length / 2)); })
        .sort(function (a, b) { return b.score - a.score || (a.g.last < b.g.last ? 1 : -1); }).slice(0, 3) : [];
      var timelines = named.map(function (x) {
        var g = x.g;
        return "Developing story: " + storylineHead(g) + "\n" + g.reports.slice(-15).map(function (s) {
          return "  - " + (s.p || s.d) + " | " + (s.sg || "Update") + " | " + (s.te || s.t) + " | " + s.s + " | " + s.l;
        }).join("\n");
      }).join("\n");
      return "Archive stories retrieved for this question (" + chosen.length + " of " + stories.length + " archived" +
        (wkey ? ", limited to " + windowLabel(wkey) : "") + "; " + matched.length + " match its words):\n" + (text || "(none)") +
        (timelines ? "\n\nDeveloping stories that match the question, oldest report first:\n" + timelines : "");
    }

    /* minimal, safe markdown for answers */
    function md(src) {
      var out = [], list = null;
      function inline(t) {
        t = esc(t);
        t = t.replace(/`([^`]+)`/g, "<code>$1</code>");
        t = t.replace(/\*\*([^*]+)\*\*/g, "<b>$1</b>").replace(/(^|[^*])\*([^*\s][^*]*)\*/g, "$1<i>$2</i>");
        t = t.replace(/\[([^\]]+)\]\((https?:\/\/[^\s)]+)\)/g, "<a href='$2' target='_blank' rel='noopener'>$1</a>");
        return t;
      }
      function close() { if (list) { out.push("</" + list + ">"); list = null; } }
      src.split(/\n/).forEach(function (line) {
        var t = line.trim(), mm;
        if (!t) { close(); return; }
        if ((mm = t.match(/^#{1,4}\s+(.*)/))) { close(); out.push("<h3>" + inline(mm[1]) + "</h3>"); return; }
        if ((mm = t.match(/^[-*•]\s+(.*)/))) { if (list !== "ul") { close(); out.push("<ul>"); list = "ul"; } out.push("<li>" + inline(mm[1]) + "</li>"); return; }
        if ((mm = t.match(/^\d+[.)]\s+(.*)/))) { if (list !== "ol") { close(); out.push("<ol>"); list = "ol"; } out.push("<li>" + inline(mm[1]) + "</li>"); return; }
        close();
        out.push("<p>" + inline(t) + "</p>");
      });
      close();
      return out.join("");
    }

    function addMsg(role, html, cls) {
      var wrap = document.createElement("div");
      wrap.className = "msg " + role;
      wrap.innerHTML = "<div class='bubble" + (cls ? " " + cls : "") + "'>" + html + "</div>";
      log.appendChild(wrap);
      log.scrollTop = log.scrollHeight;
      return wrap.firstChild;
    }

    /* attachments */
    function readFile(file) {
      var name = file.name, lower = name.toLowerCase();
      if (file.size > MAX_FILE_MB * 1024 * 1024) return Promise.reject(new Error(name + " is larger than " + MAX_FILE_MB + " MB."));
      if (lower.endsWith(".pdf")) {
        return file.arrayBuffer().then(function (buf) {
          var bytes = new Uint8Array(buf), bin = "";
          for (var i = 0; i < bytes.length; i += 0x8000) bin += String.fromCharCode.apply(null, bytes.subarray(i, i + 0x8000));
          return { name: name, block: { type: "document", title: name, source: { type: "base64", media_type: "application/pdf", data: btoa(bin) } } };
        });
      }
      if (lower.endsWith(".docx")) {
        return loadMammoth().then(function () { return file.arrayBuffer(); })
          .then(function (buf) { return window.mammoth.extractRawText({ arrayBuffer: buf }); })
          .then(function (res) { return textBlock(name, "Word document", res.value); });
      }
      if (/\.(txt|md)$/.test(lower)) return file.text().then(function (t) { return textBlock(name, "text file", t); });
      return Promise.reject(new Error(name + ": only PDF, Word (.docx) and text files can be attached."));
    }
    function textBlock(name, kind, text) {
      var max = 300000, cut = text.length > max;
      return { name: name, block: { type: "text", text: "Attached " + kind + " “" + name + "”" + (cut ? " (first " + max + " characters)" : "") + ":\n\n" + text.slice(0, max) } };
    }
    var mammothPromise;
    function loadMammoth() {
      if (window.mammoth) return Promise.resolve();
      return mammothPromise || (mammothPromise = new Promise(function (ok, fail) {
        var s = document.createElement("script");
        s.src = "https://cdn.jsdelivr.net/npm/mammoth@1.8.0/mammoth.browser.min.js";
        s.integrity = "sha384-/cXAMbzovUIKbBERjPmR3SnPTh8siWr5lsvFYj1Uq4XP0yaJUZJmsh0YXyGv5P0y";
        s.crossOrigin = "anonymous";
        s.onload = ok;
        s.onerror = function () { mammothPromise = null; fail(new Error("Could not load the Word reader. Check your connection.")); };
        document.head.appendChild(s);
      }));
    }
    function drawFiles() {
      filesEl.innerHTML = pendingFiles.map(function (f, i) {
        return "<span class='file-pill'>📎 " + esc(f.name) + "<button type='button' data-i='" + i + "' aria-label='Remove'>×</button></span>";
      }).join("");
    }
    filesEl.addEventListener("click", function (e) {
      if (e.target.dataset.i) { pendingFiles.splice(+e.target.dataset.i, 1); drawFiles(); }
    });
    function attachedMB() {
      return pendingFiles.reduce(function (n, f) { return n + JSON.stringify(f.block).length; }, 0) / (1024 * 1024);
    }
    fileInput.addEventListener("change", function () {
      var mine = conversation;
      Array.prototype.forEach.call(fileInput.files, function (file) {
        var job = readFile(file).then(function (f) {
          if (mine !== conversation) return;
          if (attachedMB() + JSON.stringify(f.block).length / (1024 * 1024) > MAX_TOTAL_MB) {
            throw new Error(f.name + " was not attached: the files for one question must stay under " + MAX_TOTAL_MB + " MB in total.");
          }
          pendingFiles.push(f);
          drawFiles();
        }).catch(function (err) { addMsg("bot", esc(err.message), "err"); });
        reading.push(job);
        job.then(function () { reading.splice(reading.indexOf(job), 1); });
      });
      fileInput.value = "";
    });

    /* questions go to the connector in the editor's Google account, which adds the key */
    function askBridge(passcode) {
      var payload = { model: model(), system: systemText, messages: history, passcode: passcode || store.get(KEYS.passcode) };
      // sent as text/plain so the browser makes a simple request that Google's servers accept
      return fetch(endpoint, { method: "POST", body: JSON.stringify(payload) }).then(function (r) {
        if (!r.ok) throw new Error("The connector answered with error " + r.status + ".");
        return r.json();
      });
    }

    function send(question) {
      if (busy || !endpoint) return false;
      if (!question && !pendingFiles.length && !reading.length) return false;
      busy = true;
      var mine = conversation;
      // wait for attachments still being read, the archive and the events calendar, so none is left out
      Promise.all(reading.concat([loadArchive().catch(function () { return null; }), calendarPromise])).then(function () {
        if (mine === conversation) ask(question, mine);
      });
      return true;
    }

    function ask(question, mine) {
      question = question || "Please read the attached document(s) and summarise what matters for the magazine.";
      var files = pendingFiles.splice(0);
      drawFiles();
      addMsg("user", esc(question).replace(/\n/g, "<br>") + (files.length ? "<div class='files'>📎 " + files.map(function (f) { return esc(f.name); }).join(", ") + "</div>" : ""));
      // only the newest question carries the retrieved stories, to keep each request small
      history.forEach(function (turn) {
        if (turn.role === "user" && Array.isArray(turn.content)) {
          turn.content = turn.content.filter(function (b) { return !(b.type === "text" && b._ctx); });
        }
      });
      var content = files.map(function (f) { return f.block; });
      var ctx = { type: "text", text: retrieve(question) };
      Object.defineProperty(ctx, "_ctx", { value: true, enumerable: false });
      content.push(ctx, { type: "text", text: question });
      history.push({ role: "user", content: content });
      var bubble = addMsg("bot", "<span class='typing'><span></span><span></span><span></span></span> <span class='wait'></span>");
      var t0 = Date.now();
      var timer = setInterval(function () {
        var w = bubble.querySelector(".wait");
        if (w) w.textContent = "Thinking… " + Math.round((Date.now() - t0) / 1000) + " s";
      }, 1000);

      function finish(j) {
        if (mine !== conversation) return;  // the editor started a new conversation meanwhile
        if (j.error === "passcode") {
          var code = window.prompt("This assistant is protected by a passcode. Please enter it:");
          if (!code) throw new Error("A passcode is needed to use the assistant.");
          store.set(KEYS.passcode, code);
          return askBridge(code).then(finish);
        }
        if (j.error) throw new Error(j.error);
        var answer = j.text || "";
        if (j.stop_reason === "refusal") answer += (answer ? "\n\n" : "") + "*The model declined to answer this request.*";
        if (j.stop_reason === "max_tokens") answer += "\n\n*(The answer was cut short. Ask me to continue.)*";
        bubble.innerHTML = md(answer) || "<p>(no answer)</p>";
        history.push({ role: "assistant", content: answer || "(no answer)" });
        if (bridge && typeof j.left === "number") { bridge.usedToday = bridge.dailyLimit - j.left; refreshStatus(); }
      }

      askBridge().then(finish).catch(function (err) {
        if (mine !== conversation) return;
        bubble.classList.add("err");
        bubble.innerHTML = esc(err.message || String(err));
        history.pop();  // let the editor retry the same question
      }).then(function () { clearInterval(timer); busy = false; input.focus(); log.scrollTop = log.scrollHeight; });
    }

    form.addEventListener("submit", function (e) {
      e.preventDefault();
      if (send(input.value.trim())) {  // keep the typed question if it could not be sent yet
        input.value = "";
        input.style.height = "";
      }
    });
    input.addEventListener("keydown", function (e) {
      if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); form.requestSubmit(); }
    });
    input.addEventListener("input", function () { input.style.height = "auto"; input.style.height = Math.min(input.scrollHeight, 180) + "px"; });
    log.addEventListener("click", function (e) {
      var q = e.target.closest && e.target.closest(".chip-btn");
      if (q) send(q.dataset.q);
    });
    document.getElementById("chat-new").addEventListener("click", function () {
      conversation++;
      busy = false;
      history = [];
      pendingFiles = [];
      drawFiles();
      Array.prototype.slice.call(log.querySelectorAll(".msg:not(.welcome)")).forEach(function (n) { n.remove(); });
    });
  })();
})();
