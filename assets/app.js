/* Geotechnical News Desk — filters, archive search, settings, Scan now button and AI assistant. */
(function () {
  "use strict";
  var root = document.body.getAttribute("data-root") || "";
  var repo = document.body.getAttribute("data-repo") || "";

  function esc(s) {
    return String(s == null ? "" : s).replace(/[&<>"']/g, function (c) {
      return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c];
    });
  }
  /* settings live only in this browser; storage can be unavailable (private mode) */
  var store = {
    get: function (k) { try { return localStorage.getItem(k) || ""; } catch (e) { return ""; } },
    set: function (k, v) { try { v ? localStorage.setItem(k, v) : localStorage.removeItem(k); } catch (e) { /* ignore */ } }
  };
  var KEYS = { gh: "gnd_github_token", ak: "gnd_anthropic_key", model: "gnd_model", scan: "gnd_scan_started" };

  function fmt(iso) {
    if (!iso) return "";
    var d = new Date(iso.slice(0, 10) + "T00:00:00Z");
    return d.toLocaleDateString("en-GB", { day: "numeric", month: "short", year: "numeric", timeZone: "UTC" });
  }

  /* ---------- toast ---------- */
  var toastEl = document.getElementById("toast"), toastTimer;
  function toast(html, kind, sticky) {
    if (!toastEl) return;
    toastEl.className = "toast" + (kind ? " " + kind : "");
    toastEl.innerHTML = html;
    toastEl.hidden = false;
    clearTimeout(toastTimer);
    if (!sticky) toastTimer = setTimeout(function () { toastEl.hidden = true; }, 9000);
  }

  /* ---------- settings dialog ---------- */
  var dlg = document.getElementById("settings");
  function openSettings() {
    if (!dlg) return;
    document.getElementById("set-gh").value = store.get(KEYS.gh);
    document.getElementById("set-ak").value = store.get(KEYS.ak);
    document.getElementById("set-model").value = store.get(KEYS.model) || "claude-opus-5-5";
    if (dlg.showModal) dlg.showModal(); else dlg.setAttribute("open", "");
  }
  if (dlg) {
    document.getElementById("settings-btn").addEventListener("click", openSettings);
    dlg.addEventListener("close", function () {
      if (dlg.returnValue !== "save") return;
      store.set(KEYS.gh, document.getElementById("set-gh").value.trim());
      store.set(KEYS.ak, document.getElementById("set-ak").value.trim());
      store.set(KEYS.model, document.getElementById("set-model").value);
      toast("Settings saved in this browser.", "ok");
      document.dispatchEvent(new Event("gnd-settings"));
    });
    document.getElementById("set-clear").addEventListener("click", function () {
      ["set-gh", "set-ak"].forEach(function (id) { document.getElementById(id).value = ""; });
      [KEYS.gh, KEYS.ak, KEYS.model].forEach(function (k) { store.set(k, ""); });
    });
  }

  /* ---------- Scan now ---------- */
  var scanBtn = document.getElementById("scan-btn");
  var GH = "https://api.github.com/repos/" + repo + "/actions/workflows/scan.yml";
  var ghPage = "https://github.com/" + repo + "/actions/workflows/scan.yml";
  function ghHeaders() {
    return { Authorization: "Bearer " + store.get(KEYS.gh), Accept: "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28" };
  }
  function setRunning(on) { if (scanBtn) scanBtn.classList.toggle("running", on); }

  function pollScan(started) {
    setRunning(true);
    var tick = function () {
      fetch(GH + "/runs?per_page=5", { headers: ghHeaders() }).then(function (r) { return r.json(); }).then(function (j) {
        var run = (j.workflow_runs || []).filter(function (x) { return new Date(x.created_at).getTime() >= started - 90000; }).pop();
        var mins = Math.round((Date.now() - started) / 60000);
        if (!run) { toast("Scan requested — waiting for GitHub to start it…", "", true); }
        else if (run.status !== "completed") {
          toast("Scan " + (run.status === "queued" ? "queued" : "running") + " · " + mins + " min so far. It usually takes 3–4 minutes. " +
            "<a href='" + esc(run.html_url) + "' target='_blank' rel='noopener'>Watch on GitHub</a>", "", true);
        } else {
          store.set(KEYS.scan, "");
          setRunning(false);
          if (run.conclusion === "success") {
            toast("Scan finished. The website refreshes about a minute later — <a href='#' id='reload-link'>reload the page</a>.", "ok", true);
            var a = document.getElementById("reload-link");
            if (a) a.addEventListener("click", function (e) { e.preventDefault(); location.reload(); });
          } else {
            toast("The scan ended with “" + esc(run.conclusion) + "”. <a href='" + esc(run.html_url) + "' target='_blank' rel='noopener'>See the log on GitHub</a>.", "err", true);
          }
          return;
        }
        if (Date.now() - started < 20 * 60000) setTimeout(tick, 10000);
        else { setRunning(false); store.set(KEYS.scan, ""); }
      }).catch(function () { setTimeout(tick, 15000); });
    };
    tick();
  }

  if (scanBtn) {
    scanBtn.addEventListener("click", function () {
      if (!store.get(KEYS.gh)) {
        toast("To start scans from the website, add a GitHub token in Settings (one-time). " +
          "<a href='" + ghPage + "' target='_blank' rel='noopener'>Or run it on GitHub →</a>", "", true);
        openSettings();
        return;
      }
      if (scanBtn.classList.contains("running")) return;
      setRunning(true);
      toast("Starting a scan…", "", true);
      fetch(GH + "/dispatches", { method: "POST", headers: ghHeaders(), body: JSON.stringify({ ref: "main" }) }).then(function (r) {
        if (r.status === 204) {
          var started = Date.now();
          store.set(KEYS.scan, String(started));
          pollScan(started);
          return;
        }
        setRunning(false);
        var why = r.status === 401 ? "the GitHub token was not accepted (expired or mistyped)."
          : (r.status === 403 || r.status === 404) ? "the token cannot run workflows in " + esc(repo) + ". Give it access to this repository with Actions: Read and write."
          : "GitHub answered with error " + r.status + ".";
        toast("Could not start the scan: " + why + " <a href='" + ghPage + "' target='_blank' rel='noopener'>Run it on GitHub instead</a>.", "err", true);
      }).catch(function () {
        setRunning(false);
        toast("Could not reach GitHub. Check your connection and try again.", "err");
      });
    });
    var pending = +store.get(KEYS.scan);
    if (pending && Date.now() - pending < 20 * 60000 && store.get(KEYS.gh)) pollScan(pending);
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
  var archivePromise;
  function loadArchive() {
    if (!archivePromise) {
      archivePromise = fetch(root + "exports/index.json").then(function (r) { return r.json(); }).then(function (windows) {
        return Promise.all(windows.map(function (w) {
          return fetch(root + "exports/" + w.key + ".json").then(function (r) { return r.json(); });
        })).then(function (lists) { return { windows: windows, stories: [].concat.apply([], lists) }; });
      });
    }
    return archivePromise;
  }
  function windowLabel(key) { var p = key.split("-"); return p[1] + " " + p[0]; }

  function card(s) {
    var title = s.te || s.t, rel = s.r
      ? "<span class='rel rel-" + s.r + "' title='Geotechnical relevance: " + s.r + " of 5'><i></i><i></i><i></i><i></i><i></i><b>" + s.r + "/5</b></span>"
      : "<span class='rel rel-kw'>Keyword-ranked</span>";
    var meta = ["<span class='src'>" + esc(s.s) + "</span>"];
    if (s.p) meta.push("<time>" + esc(fmt(s.p)) + "</time>");
    if (s.c) meta.push("<span>" + esc(s.c) + " edition</span>");
    var useSlug = s.u ? s.u.split(" ")[0].toLowerCase().replace(/-+$/, "") : "";
    var tc = THEME_COLORS[s.th] || "#64748b";
    return "<article class='story' style='--tc:" + tc + "'><div class='story-top'><a class='story-title' dir='auto' href='" + esc(s.l) + "' target='_blank' rel='noopener'>" +
      esc(title) + "</a>" + rel + "</div>" +
      (s.te ? "<div class='orig' dir='auto'>Original: " + esc(s.t) + "</div>" : "") +
      (s.a ? "<p class='angle'><span>Magazine angle</span>" + esc(s.a) + "</p>" : (s.x ? "<p class='summary'>" + esc(s.x) + "…</p>" : "")) +
      "<div class='story-meta'>" + (s.u ? "<span class='use use-" + esc(useSlug) + "'>" + esc(s.u) + "</span>" : "") +
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
    loadArchive().then(function (data) { all = data.stories; run(); }).catch(function () {
      countEl.textContent = "The archive could not be loaded. If you opened this file from disk, view it on the published website instead.";
    });
  })();

  function hay(s) {
    return s._hay || (s._hay = [s.t, s.te, s.a, s.s, s.c, s.th, s.u, s.x, (s.k || []).join(" ")].join(" ").toLowerCase());
  }

  /* ---------- AI assistant ---------- */
  var chat = document.getElementById("chat-app");
  if (chat) (function () {
    var log = document.getElementById("chat-log"), form = document.getElementById("chat-form");
    var input = document.getElementById("chat-text"), fileInput = document.getElementById("chat-file");
    var filesEl = document.getElementById("chat-files"), statusEl = document.getElementById("chat-status");
    var history = [], pendingFiles = [], busy = false, archive = null, systemText = "";
    var MODEL_NAMES = { "claude-opus-5-5": "Claude Opus 5.5", "claude-sonnet-5-5": "Claude Sonnet 5.5", "claude-haiku-5-5": "Claude Haiku 5.5" };
    var STOP = "the and for with from that this what which about are was were have has into over under than then them they their there these those who why how can could would should will may might any all some most more best find show give tell list stories story news latest recent please quarter issue window themes theme magazine suggest recommend article articles also just like make need want get our you your".split(" ");

    function model() { return store.get(KEYS.model) || "claude-opus-5-5"; }
    function refreshStatus() {
      statusEl.innerHTML = store.get(KEYS.ak)
        ? "Model: " + esc(MODEL_NAMES[model()] || model()) + (archive ? " · " + archive.stories.length + " archived stories available" : " · loading archive…")
        : "<b>Add your Anthropic API key in Settings (gear icon) to start.</b>";
    }
    document.addEventListener("gnd-settings", refreshStatus);
    refreshStatus();

    loadArchive().then(function (data) {
      archive = data;
      systemText = buildSystem(data);
      refreshStatus();
    }).catch(function () { statusEl.textContent = "The archive could not be loaded; the assistant can still read attached documents."; systemText = buildSystem({ windows: [], stories: [] }); });

    function buildSystem(data) {
      var lines = data.windows.map(function (w) {
        var themes = {};
        data.stories.forEach(function (s) { if (s.w === w.key) themes[s.th] = (themes[s.th] || 0) + 1; });
        return "- " + w.label + " (" + w.span + "): " + w.stories + " stories — " +
          Object.keys(themes).sort(function (a, b) { return themes[b] - themes[a]; }).map(function (t) { return t + " " + themes[t]; }).join(", ");
      });
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
        "If the retrieved stories do not cover what was asked, say so plainly and suggest a search term or filter for the Search page.\n\n" +
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
        var s = x.s;
        return "[" + (i + 1) + "] " + (s.p || s.d) + " | " + windowLabel(s.w) + " | " + s.th + " | " + (s.r ? s.r + "/5" : "keyword-ranked") +
          (s.u ? " | " + s.u : "") + " | " + (s.te || s.t) + (s.te ? " (original: " + s.t + ")" : "") +
          (s.a ? " | angle: " + s.a : "") + " | " + s.s + (s.c ? " | " + s.c + " edition" : "") +
          ((s.k && s.k.length) ? " | keywords: " + s.k.join(", ") : "") + " | " + s.l;
      }).join("\n");
      return "Archive stories retrieved for this question (" + chosen.length + " of " + stories.length + " archived" +
        (wkey ? ", limited to " + windowLabel(wkey) : "") + "; " + matched.length + " match its words):\n" + (text || "(none)");
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
      if (file.size > 25 * 1024 * 1024) return Promise.reject(new Error(name + " is larger than 25 MB."));
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
    fileInput.addEventListener("change", function () {
      Array.prototype.forEach.call(fileInput.files, function (file) {
        readFile(file).then(function (f) { pendingFiles.push(f); drawFiles(); })
          .catch(function (err) { addMsg("bot", esc(err.message), "err"); });
      });
      fileInput.value = "";
    });

    /* talk to Claude directly from the browser, streaming the answer */
    function callClaude(useFallback) {
      var m = model();
      var body = {
        model: m, max_tokens: 8000, stream: true,
        system: [{ type: "text", text: systemText, cache_control: { type: "ephemeral" } }],
        messages: history
      };
      var headers = {
        "content-type": "application/json", "x-api-key": store.get(KEYS.ak), "anthropic-version": "2023-06-01",
        "anthropic-dangerous-direct-browser-access": "true"
      };
      if (useFallback && m !== "claude-haiku-5-5") {
        headers["anthropic-beta"] = "server-side-fallback-2026-07-01";
        body.fallbacks = "default";
      }
      return fetch("https://api.anthropic.com/v1/messages", { method: "POST", headers: headers, body: JSON.stringify(body) });
    }

    function send(question) {
      if (busy) return;
      if (!store.get(KEYS.ak)) { addMsg("bot", "Please add your Anthropic API key in <b>Settings</b> (the gear icon at the top right) first.", "err"); openSettings(); return; }
      if (!question && !pendingFiles.length) return;
      question = question || "Please read the attached document(s) and summarise what matters for the magazine.";
      busy = true;
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
      var bubble = addMsg("bot", "<span class='typing'><span></span><span></span><span></span></span>");
      var answer = "", stop = "", frame = 0;
      function paint() { frame = 0; bubble.innerHTML = md(answer) || "<span class='typing'><span></span><span></span><span></span></span>"; log.scrollTop = log.scrollHeight; }

      function attempt(useFallback) {
        return callClaude(useFallback).then(function (res) {
          if (!res.ok) {
            return res.json().catch(function () { return {}; }).then(function (j) {
              var msg = (j.error && j.error.message) || ("HTTP " + res.status);
              if (useFallback && res.status === 400 && /fallback/i.test(msg)) return attempt(false);
              if (res.status === 401) msg = "The Anthropic API key was not accepted. Check it in Settings.";
              throw new Error(msg);
            });
          }
          var reader = res.body.getReader(), decoder = new TextDecoder(), buf = "";
          function pump() {
            return reader.read().then(function (r) {
              if (r.done) return;
              buf += decoder.decode(r.value, { stream: true });
              var parts = buf.split("\n\n");
              buf = parts.pop();
              parts.forEach(function (evt) {
                var data = evt.split("\n").filter(function (l) { return l.indexOf("data:") === 0; }).map(function (l) { return l.slice(5).trim(); }).join("");
                if (!data) return;
                var j;
                try { j = JSON.parse(data); } catch (e) { return; }
                if (j.type === "content_block_delta" && j.delta && j.delta.type === "text_delta") {
                  answer += j.delta.text;
                  if (!frame) frame = requestAnimationFrame(paint);
                } else if (j.type === "message_delta" && j.delta) {
                  stop = j.delta.stop_reason || stop;
                } else if (j.type === "error") {
                  throw new Error((j.error && j.error.message) || "The answer was interrupted.");
                }
              });
              return pump();
            });
          }
          return pump();
        });
      }

      attempt(true).then(function () {
        if (stop === "refusal") answer += (answer ? "\n\n" : "") + "*The model declined to answer this request.*";
        if (stop === "max_tokens") answer += "\n\n*(The answer was cut short. Ask me to continue.)*";
        paint();
        history.push({ role: "assistant", content: answer || "(no answer)" });
      }).catch(function (err) {
        bubble.classList.add("err");
        bubble.innerHTML = esc(err.message || String(err));
        history.pop();  // let the editor retry the same question
      }).then(function () { busy = false; input.focus(); });
    }

    form.addEventListener("submit", function (e) {
      e.preventDefault();
      var q = input.value.trim();
      input.value = "";
      input.style.height = "";
      send(q);
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
      history = [];
      pendingFiles = [];
      drawFiles();
      Array.prototype.slice.call(log.querySelectorAll(".msg:not(.welcome)")).forEach(function (n) { n.remove(); });
    });
  })();
})();
