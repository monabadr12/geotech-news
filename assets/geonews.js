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
