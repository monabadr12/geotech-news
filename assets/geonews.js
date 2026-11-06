/* Geo-News Weekly, the editor's preview page: Copy buttons (story codes, the LinkedIn text) and
   "Download the picture", which turns the LinkedIn card (SVG) into a PNG of 1200 × 627. */
(function () {
  function flash(btn, text) {
    var old = btn.textContent;
    btn.textContent = text;
    setTimeout(function () { btn.textContent = old; }, 1500);
  }
  function copy(text, btn) {
    function fallback() {
      var t = document.createElement("textarea");
      t.value = text; document.body.appendChild(t); t.select();
      try { document.execCommand("copy"); flash(btn, "Copied"); } catch (e) { flash(btn, "Select and copy"); }
      document.body.removeChild(t);
    }
    if (navigator.clipboard && window.isSecureContext) {
      navigator.clipboard.writeText(text).then(function () { flash(btn, "Copied"); }, fallback);
    } else { fallback(); }
  }
  document.addEventListener("click", function (e) {
    var btn = e.target.closest ? e.target.closest("button") : null;
    if (!btn) return;
    if (btn.hasAttribute("data-copy")) copy(btn.getAttribute("data-copy"), btn);
    else if (btn.hasAttribute("data-copy-from")) copy(document.getElementById(btn.getAttribute("data-copy-from")).value, btn);
  });
  var save = document.getElementById("li-save");
  var card = document.querySelector(".li-card");
  if (!save || !card) return;
  save.addEventListener("click", function () {
    var clone = card.cloneNode(true);
    clone.querySelectorAll("a").forEach(function (a) {  // links mean nothing in a picture
      while (a.firstChild) a.parentNode.insertBefore(a.firstChild, a);
      a.parentNode.removeChild(a);
    });
    var xml = new XMLSerializer().serializeToString(clone);
    var img = new Image();
    img.onload = function () {
      var c = document.createElement("canvas");
      c.width = 1200; c.height = 627;
      c.getContext("2d").drawImage(img, 0, 0, 1200, 627);
      c.toBlob(function (blob) {
        var a = document.createElement("a");
        a.href = URL.createObjectURL(blob);
        a.download = "geo-news-" + (save.getAttribute("data-week") || "week") + "-linkedin.png";
        document.body.appendChild(a); a.click(); a.remove();
        flash(save, "Saved");
      }, "image/png");
    };
    img.onerror = function () { flash(save, "Could not make the picture"); };
    img.src = "data:image/svg+xml;charset=utf-8," + encodeURIComponent(xml);
  });
})();

/* The story editor on the preview page: change, reorder, remove or add stories, edit headlines, texts and key
   numbers, then save. Saving opens GitHub with a new file ready (data/geonews/edits/<week>--<time>.json); the editor
   presses Commit changes there and the page is rebuilt within a few minutes. The newest save of a week wins. */
(function () {
  var dataEl = document.getElementById("gn-data"), box = document.getElementById("gn-editor"),
      openBtn = document.getElementById("ed-open");
  if (!dataEl || !box || !openBtn) return;
  var D = JSON.parse(dataEl.textContent);
  var S = { highlights: D.highlights.slice(), around_the_world: D.around_the_world.slice(), intro: D.intro };
  var changed = false;
  var LABEL = { highlights: "Highlights", around_the_world: "Around the world" };

  function el(tag, attrs, html) {
    var e = document.createElement(tag);
    for (var k in attrs || {}) { if (k === "class") e.className = attrs[k]; else e.setAttribute(k, attrs[k]); }
    if (html != null) e.innerHTML = html;
    return e;
  }
  function esc(t) { return String(t == null ? "" : t).replace(/[&<>"']/g, function (c) {
    return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]; }); }
  function info(id) { return D.stories[id] || { t: "(story " + id + ")", w: "", f: "", src: "", th: "", r: 0, a: "" }; }
  function inIssue(id) {
    return S.highlights.concat(S.around_the_world).some(function (e) { return e.story === id; });
  }
  function mark() { changed = true; var n = document.getElementById("ed-changed"); if (n) n.hidden = false; }

  function render() {
    box.innerHTML = "";
    var head = el("div", { "class": "ed-head" },
      "<div><b>✏️ Story editor</b> · week " + esc(D.week.slice(-2).replace(/^0/, "")) + " · " + esc(D.span) + "</div>");
    var close = el("button", { type: "button", "class": "ed-x", "aria-label": "Hide the editor" }, "✕");
    close.onclick = function () { box.hidden = true; };
    head.appendChild(close);
    box.appendChild(head);
    box.appendChild(el("p", { "class": "ed-help" },
      "Use the buttons to change, move or remove a story. Nothing changes on the page until you press <b>Save changes</b> " +
      "or <b>Approve and publish</b> at the bottom."));
    ["highlights", "around_the_world"].forEach(function (name) {
      var sec = el("section", { "class": "ed-sec" });
      sec.appendChild(el("h3", {}, esc(LABEL[name]) + (name === "highlights" ? " <small>(the first one is the story of the week)</small>" : "")));
      S[name].forEach(function (e, i) { sec.appendChild(row(name, e, i)); });
      var add = el("button", { type: "button", "class": "ed-add" }, "＋ Add a story");
      add.onclick = function () { pick(function (id) { S[name].push({ story: id, title: "", text: info(id).a || "", number: "", number_label: "" }); mark(); render(); }); };
      sec.appendChild(add);
      box.appendChild(sec);
    });
    var intro = el("details", { "class": "ed-sec" }, "<summary>Welcome text</summary>");
    var ta = el("textarea", { rows: "4" }); ta.value = S.intro;
    ta.oninput = function () { S.intro = ta.value; mark(); };
    intro.appendChild(ta);
    box.appendChild(intro);
    var foot = el("div", { "class": "ed-foot" });
    foot.appendChild(el("span", { id: "ed-changed", "class": "ed-changed" }, "You have unsaved changes"));
    var save = el("button", { type: "button", "class": "btn alt" }, "💾 Save changes");
    save.onclick = function () { publish(D.status === "approved" ? "approved" : "draft"); };
    var pub = el("button", { type: "button", "class": "btn red" }, D.status === "approved" ? "✔ Save (stays published)" : "✔ Approve and publish");
    pub.onclick = function () { publish("approved"); };
    foot.appendChild(save); foot.appendChild(pub);
    box.appendChild(foot);
    var c = box.querySelector("#ed-changed"); if (c) c.hidden = !changed;
  }

  function row(name, e, i) {
    var s = info(e.story), list = S[name];
    var r = el("div", { "class": "ed-row", "data-story": e.story });
    var n = name === "highlights" ? i + 1 : S.highlights.length + i + 1;
    r.appendChild(el("div", { "class": "ed-main" },
      "<b class='ed-n'>" + n + "</b><div><div class='ed-t'>" + esc(e.title || s.t) + "</div>" +
      "<div class='ed-m'>" + esc(s.f + " " + s.w) + " · " + esc(s.src) + (e.number ? " · <b>" + esc(e.number) + "</b>" : "") + "</div></div>"));
    var b = el("div", { "class": "ed-btns" });
    function btn(label, title, fn, off) {
      var x = el("button", { type: "button", title: title, "aria-label": title }, label);
      if (off) x.disabled = true; else x.onclick = fn; b.appendChild(x);
    }
    btn("↑ Up", "Move up", function () { list.splice(i - 1, 0, list.splice(i, 1)[0]); mark(); render(); }, i === 0);
    btn("↓ Down", "Move down", function () { list.splice(i + 1, 0, list.splice(i, 1)[0]); mark(); render(); }, i === list.length - 1);
    btn("⇄ Replace", "Replace with another story", function () {
      pick(function (id) { list[i] = { story: id, title: "", text: info(id).a || "", number: "", number_label: "" }; mark(); render(); });
    });
    btn("✎ Edit", "Edit headline, text and key number", function () { form.hidden = !form.hidden; });
    btn("✕ Remove", "Remove", function () { if (confirm("Remove this story from the issue?")) { list.splice(i, 1); mark(); render(); } });
    r.appendChild(b);
    var form = el("div", { "class": "ed-form" }); form.hidden = true;
    [["title", "Headline (leave empty to keep the original)", s.t], ["text", "Text under the headline", ""],
     ["number", "Key number (e.g. 96%)", ""], ["number_label", "What the number counts", ""]].forEach(function (f) {
      var lab = el("label", {}, "<span>" + esc(f[1]) + "</span>");
      var inp = el(f[0] === "text" ? "textarea" : "input", f[0] === "text" ? { rows: "3" } : { type: "text" });
      inp.value = e[f[0]] || ""; if (f[2] && f[0] === "title") inp.placeholder = f[2];
      inp.oninput = function () { e[f[0]] = inp.value; mark(); };
      lab.appendChild(inp); form.appendChild(lab);
    });
    r.appendChild(form);
    return r;
  }

  function pick(done) {
    var ov = el("div", { "class": "ed-overlay", role: "dialog", "aria-label": "Choose a story" });
    var panel = el("div", { "class": "ed-pick" });
    var top = el("div", { "class": "ed-head" }, "<div><b>Choose a story</b> · this week's stories, best first</div>");
    var x = el("button", { type: "button", "class": "ed-x", "aria-label": "Close" }, "✕");
    x.onclick = function () { ov.remove(); };
    top.appendChild(x); panel.appendChild(top);
    var q = el("input", { type: "search", placeholder: "Search: a word, a country, a source…", "class": "ed-q" });
    panel.appendChild(q);
    var ul = el("ul", { "class": "ed-list" });
    function fill() {
      var w = q.value.toLowerCase(); ul.innerHTML = "";
      D.order.forEach(function (id) {
        var s = info(id);
        if (inIssue(id)) return;
        if (w && (s.t + " " + s.w + " " + s.src + " " + s.th).toLowerCase().indexOf(w) < 0) return;
        var li = el("li", {}, "<div><div class='ed-t'>" + esc(s.t) + "</div><div class='ed-m'>" + esc(s.f + " " + s.w) +
          " · " + esc(s.src) + " · " + esc(s.th) + " · " + s.r + "/5</div>" +
          (s.a ? "<div class='ed-a'>" + esc(s.a) + "</div>" : "") + "</div>");
        var use = el("button", { type: "button", "class": "btn" }, "Choose");
        use.onclick = function () { ov.remove(); done(id); };
        li.appendChild(use); ul.appendChild(li);
      });
      if (!ul.children.length) ul.appendChild(el("li", {}, "No other story matches."));
    }
    q.oninput = fill; fill();
    panel.appendChild(ul); ov.appendChild(panel);
    ov.onclick = function (ev) { if (ev.target === ov) ov.remove(); };
    document.body.appendChild(ov); q.focus();
  }

  function publish(status) {
    var now = new Date(), p = function (n) { return (n < 10 ? "0" : "") + n; };
    var stamp = now.getUTCFullYear() + p(now.getUTCMonth() + 1) + p(now.getUTCDate()) + "-" + p(now.getUTCHours()) +
      p(now.getUTCMinutes()) + p(now.getUTCSeconds());
    function clean(list) { return list.map(function (e) {
      var o = { story: e.story };
      ["title", "text", "number", "number_label"].forEach(function (k) { if (e[k]) o[k] = e[k]; });
      return o; }); }
    var save = { week: D.week, status: status, intro: S.intro, highlights: clean(S.highlights),
                 around_the_world: clean(S.around_the_world), research: D.research };
    var json = JSON.stringify(save, null, 1);
    var url = "https://github.com/" + D.repo + "/new/main/data/geonews/edits?filename=" +
      encodeURIComponent(D.week + "--" + stamp + ".json") + "&value=" + encodeURIComponent(json);
    var ov = el("div", { "class": "ed-overlay", role: "dialog" });
    var panel = el("div", { "class": "ed-pick ed-done" },
      "<div class='ed-head'><div><b>" + (status === "approved" ? "Approve and publish" : "Save changes") + "</b></div></div>" +
      "<ol><li>Press <b>Open GitHub</b>. GitHub opens with your changes already written in a new file (sign in if asked).</li>" +
      "<li>Press the green <b>Commit changes…</b> button, then <b>Commit changes</b> again in the small window.</li>" +
      "<li>Come back here after about two minutes and refresh this page" +
      (status === "approved" ? ". The issue is then public, and the LinkedIn post is e-mailed to you." : " to see your changes.") +
      "</li></ol>");
    var go = el("a", { "class": "btn red", href: url, target: "_blank", rel: "noopener" }, "Open GitHub");
    var back = el("button", { type: "button", "class": "btn alt" }, "Back to the editor");
    back.onclick = function () { ov.remove(); };
    var bar = el("div", { "class": "toolbar" }); bar.appendChild(go); bar.appendChild(back);
    panel.appendChild(bar); ov.appendChild(panel); document.body.appendChild(ov);
  }

  openBtn.onclick = function () { render(); box.hidden = false; box.scrollIntoView({ behavior: "smooth" }); };
  // a draft opens with the editor showing; a published issue keeps it closed until ✏️ Change the stories is pressed.
  // Every story of the issue below gets a button that opens the editor at its row.
  render();
  if (D.status === "approved") box.hidden = true;
  var all = S.highlights.concat(S.around_the_world);
  all.forEach(function (e, i) {
    var card = document.getElementById("s" + (i + 1));
    if (!card) return;
    var go = el("button", { type: "button", "class": "ed-jump" }, "✏️ Change this story");
    go.onclick = function () {
      box.hidden = false;
      var rows = box.querySelectorAll(".ed-row");
      var idx = -1;
      for (var k = 0; k < rows.length; k++) if (rows[k].getAttribute("data-story") === e.story) idx = k;
      var r = rows[idx] || box;
      r.scrollIntoView({ behavior: "smooth", block: "center" });
      r.classList.add("ed-flash"); setTimeout(function () { r.classList.remove("ed-flash"); }, 1800);
    };
    var host = card.querySelector(".b2, .cv-text") || card.querySelector("div:last-child") || card;
    host.appendChild(go);
  });
})();
