/* Geotechnical News Desk — developing stories page: filters by period, theme and text; long timelines folded. */
(function () {
  "use strict";
  var cards = [].slice.call(document.querySelectorAll(".sl-card"));
  var groups = [].slice.call(document.querySelectorAll(".sl-group"));
  var app = document.getElementById("sl-app");

  /* long timelines show the first report and the latest four until opened (all of them without this script) */
  cards.forEach(function (card) {
    var folded = [].slice.call(card.querySelectorAll(".sl-item[data-fold]"));
    var more = card.querySelector(".sl-fold-btn");
    if (!folded.length || !more) return;
    folded.forEach(function (li) { li.hidden = true; });
    more.hidden = false;
    more.querySelector("button").addEventListener("click", function () {
      folded.forEach(function (li) { li.hidden = false; });
      more.parentNode.removeChild(more);
    });
  });

  var period = app && app.querySelector(".f-period");
  var theme = app && app.querySelector(".f-theme");
  var text = app && app.querySelector(".f-text");
  var count = app && app.querySelector(".f-count");

  function plural(n) { return n + " developing " + (n === 1 ? "story" : "stories"); }

  function apply() {
    if (!app) return;
    var p = period.value, t = theme.value;
    var words = text.value.toLowerCase().split(/\s+/).filter(Boolean);
    var shown = 0;
    cards.forEach(function (c) {
      var hay = c.getAttribute("data-text") || "";
      var ok = (!p || c.getAttribute("data-period") === p) && (!t || c.getAttribute("data-theme") === t) &&
        words.every(function (w) { return hay.indexOf(w) >= 0; });
      c.hidden = !ok;
      if (ok) shown++;
    });
    groups.forEach(function (g) {
      var all = g.querySelectorAll(".sl-card").length;
      var visible = g.querySelectorAll(".sl-card:not([hidden])").length;
      g.hidden = !!p && g.getAttribute("data-period") !== p;
      var none = g.querySelector(".sl-none");
      if (none) none.hidden = !all || visible > 0;
    });
    count.textContent = shown === cards.length ? plural(cards.length) : shown + " of " + plural(cards.length);
  }

  if (app) {
    [period, theme].forEach(function (el) { el.addEventListener("change", apply); });
    text.addEventListener("input", apply);
    apply();
  }

  /* a link to one developing story (developing.html#sl-…) shows it even when a filter hides it,
     and lands on it again once the folding above has changed the page's height */
  function reveal() {
    var id;
    try { id = decodeURIComponent(location.hash.slice(1)); } catch (e) { return; }  /* a malformed link: stay put */
    var card = id && document.getElementById(id);
    if (!card || !card.classList.contains("sl-card")) return;
    if (card.hidden && app) {
      period.value = ""; theme.value = ""; text.value = "";
      apply();
    }
    card.scrollIntoView();
  }
  window.addEventListener("hashchange", reveal);
  reveal();
})();
