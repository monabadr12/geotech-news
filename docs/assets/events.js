/* Geotechnical News Desk — events page: filters (text, kind, region, ISSMGE only), the days left to each
   deadline counted from the reader's today (the page itself is rebuilt once a day), and the feed address. */
(function () {
  "use strict";

  /* ---------- days left ---------- */
  var now = new Date();
  var today = Date.UTC(now.getFullYear(), now.getMonth(), now.getDate());
  function leftText(n) {
    return n === 0 ? "today" : n === 1 ? "tomorrow" : n > 1 ? n + " days left" : "passed";
  }
  document.querySelectorAll("[data-left]").forEach(function (el) {
    var day = Date.parse(el.getAttribute("data-left") + "T00:00:00Z");
    if (isNaN(day)) return;
    var n = Math.round((day - today) / 864e5);
    el.textContent = leftText(n);
    var box = el.closest(".ev-dl, .ev-calls-list li");
    if (!box) return;
    ["open", "soon", "urgent", "passed"].forEach(function (c) { box.classList.remove(c); });
    box.classList.add(n < 0 ? "passed" : n <= 14 ? "urgent" : n <= 30 ? "soon" : "open");
  });

  /* ---------- filters ---------- */
  var bar = document.getElementById("ev-filters");
  if (bar) {
    var app = document.getElementById("ev-app");
    var text = bar.querySelector(".ev-f-text"), kind = bar.querySelector(".ev-f-kind");
    var region = bar.querySelector(".ev-f-region"), issmge = bar.querySelector(".ev-f-issmge");
    var count = bar.querySelector(".ev-count"), none = app.querySelector(".ev-none");
    var cards = Array.prototype.slice.call(app.querySelectorAll(".ev-list .ev-card"));
    var apply = function () {
      var q = text.value.trim().toLowerCase(), k = kind.value, r = region ? region.value : "", only = issmge.checked;
      var shown = 0;
      cards.forEach(function (c) {
        var ok = (!q || c.getAttribute("data-text").indexOf(q) !== -1) && (!k || c.getAttribute("data-kind") === k) &&
          (!r || c.getAttribute("data-region") === r) && (!only || c.getAttribute("data-issmge") === "1");
        c.hidden = !ok;
        if (ok) shown++;
      });
      app.querySelectorAll(".ev-month").forEach(function (sec) {
        var n = sec.querySelectorAll(".ev-card:not([hidden])").length;
        sec.hidden = n === 0;
        var badge = sec.querySelector(".count");
        if (badge) badge.textContent = n;
      });
      count.textContent = shown === cards.length ? cards.length + (cards.length === 1 ? " event" : " events")
        : "Showing " + shown + " of " + cards.length;
      if (none) none.hidden = shown !== 0;
    };
    [text, kind, region, issmge].forEach(function (el) {
      if (el) { el.addEventListener("input", apply); el.addEventListener("change", apply); }
    });
    bar.hidden = false;
    apply();
  }

  /* ---------- subscription: the feed's address where this page is served, and a copy button ---------- */
  var feed = document.getElementById("ev-feed");
  if (feed) {
    var url;
    try { url = new URL("events.ics", location.href).href; } catch (e) { url = ""; }
    if (/^https?:/.test(url)) {
      feed.value = url;
      var webcal = url.replace(/^https?:/, "webcal:");
      var app1 = document.getElementById("ev-webcal"), google = document.getElementById("ev-google");
      if (app1) app1.href = webcal;
      if (google) google.href = "https://calendar.google.com/calendar/r?cid=" + encodeURIComponent(webcal);
    }
    var copy = document.getElementById("ev-copy");
    if (copy) copy.addEventListener("click", function () {
      var label = copy.querySelector("span");
      var done = function (ok) {
        label.textContent = ok ? "Copied" : "Press Ctrl+C";
        setTimeout(function () { label.textContent = "Copy"; }, 2200);
      };
      feed.select();
      if (navigator.clipboard && window.isSecureContext) {
        navigator.clipboard.writeText(feed.value).then(function () { done(true); }, function () { done(false); });
      } else {
        var ok = false;
        try { ok = document.execCommand("copy"); } catch (e) { ok = false; }
        done(ok);
      }
    });
  }
})();
