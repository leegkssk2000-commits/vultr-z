(function () {
  "use strict";
  var VERSION = "zops_code_opt_guard_v2";
  var TEXT_RX = /(ledger\s+offline|replay\s+offline|web\s+audit\s+replay|GATE\s+advisory_only|exec:blocked|OS\s+final\s+Zbot|zbot\s+recomm)/i;
  var KEEP_RX = /(HARNESS\s+active|Z-OS\s+Harness\s+Visual\s+Gate|status-pass|fail=0)/i;
  var hidden = [];
  var maxHidden = 50;

  function textOf(el) {
    try { return (el.innerText || el.textContent || "").replace(/\s+/g, " ").trim(); }
    catch (_) { return ""; }
  }

  function shouldHide(el) {
    if (!el || el.nodeType !== 1) return false;
    if (el.id === "root") return false;
    var text = textOf(el);
    if (!text || !TEXT_RX.test(text) || KEEP_RX.test(text)) return false;
    var cs = window.getComputedStyle ? getComputedStyle(el) : null;
    if (!cs) return false;
    if (cs.display === "none" || cs.visibility === "hidden") return false;
    if (!(cs.position === "fixed" || cs.position === "sticky" || cs.position === "absolute")) return false;
    var r = el.getBoundingClientRect();
    var vw = Math.max(window.innerWidth || 0, document.documentElement.clientWidth || 0);
    var vh = Math.max(window.innerHeight || 0, document.documentElement.clientHeight || 0);
    if (!vw || !vh) return false;
    var area = Math.max(1, r.width * r.height);
    var screenArea = Math.max(1, vw * vh);
    var bottomLeft = r.left <= Math.max(36, vw * 0.22) && r.top >= vh * 0.58;
    var smallOverlay = r.width <= Math.min(560, vw * 0.45) && r.height <= Math.min(170, vh * 0.22) && area <= screenArea * 0.12;
    return bottomLeft && smallOverlay;
  }

  function hideEl(el) {
    try {
      var rec = { tag: el.tagName, id: el.id || "", cls: el.className || "", text: textOf(el).slice(0, 140), ts: Date.now() };
      el.setAttribute("data-zops-hidden-by", VERSION);
      el.style.setProperty("display", "none", "important");
      el.style.setProperty("visibility", "hidden", "important");
      el.style.setProperty("pointer-events", "none", "important");
      hidden.push(rec);
      if (hidden.length > maxHidden) hidden.shift();
    } catch (_) {}
  }

  function scan() {
    try {
      var nodes = document.body ? document.body.querySelectorAll("body *") : [];
      for (var i = 0; i < nodes.length; i++) {
        if (shouldHide(nodes[i])) hideEl(nodes[i]);
      }
    } catch (_) {}
  }

  function install() {
    scan();
    try {
      var mo = new MutationObserver(function () { scan(); });
      if (document.body) mo.observe(document.body, { childList: true, subtree: true, attributes: true, attributeFilter: ["style", "class"] });
      window.__ZOPS_CODE_OPT_GUARD_V2__ = {
        version: VERSION,
        report: function () { return { version: VERSION, hidden: hidden.slice(), hidden_count: hidden.length }; },
        scan: scan
      };
    } catch (_) {
      window.__ZOPS_CODE_OPT_GUARD_V2__ = { version: VERSION, report: function () { return { version: VERSION, hidden: hidden.slice(), hidden_count: hidden.length, observer: "unavailable" }; }, scan: scan };
    }
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", install, { once: true });
    setTimeout(scan, 0);
  } else {
    install();
  }
  setTimeout(scan, 50);
  setTimeout(scan, 250);
  setTimeout(scan, 1000);
})();
