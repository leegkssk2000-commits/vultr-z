/* Z-OS UI residue cleanup v1
 * 목적: floating debug/status residue(ledger/replay offline, WEB audit replay, GATE advisory strip)를 DOM 레벨에서 제거.
 * 원칙: 핵심 앱 패널/하단 탭/Log 내부 콘텐츠는 건드리지 않고, 화면 좌하단/좌측 fixed/absolute 잔상만 제거.
 */
(function () {
  if (typeof window === 'undefined' || window.__ZOPS_UI_RESIDUE_CLEANUP_V1__) return;
  window.__ZOPS_UI_RESIDUE_CLEANUP_V1__ = true;

  var TOKENS = [
    /\bledger\s+offline\b/i,
    /\breplay\s+offline\b/i,
    /\bWEB\s+audit\s+replay\b/i,
    /\bGATE\s+advisory_only\b/i,
    /\bexec:blocked\b/i,
    /\bOS\s+final\s+Zbot\b/i,
    /\bZbot\s+recomm/i
  ];

  function textOf(el) {
    return String((el && el.textContent) || '').replace(/\s+/g, ' ').trim();
  }

  function hasToken(el) {
    var t = textOf(el);
    if (!t) return false;
    return TOKENS.some(function (re) { return re.test(t); });
  }

  function isProtected(el) {
    if (!el || !el.closest) return false;
    // Protect main application shell and actual tab panels except their floating leftovers.
    if (el.closest('[data-zops-protected="true"]')) return true;
    if (el.closest('nav, header, main, section, article, form')) {
      var s = window.getComputedStyle(el);
      var r = el.getBoundingClientRect();
      // A fixed/absolute element near screen edge is still considered residue even if nested under main.
      var edgeFloat = (s.position === 'fixed' || s.position === 'absolute' || s.position === 'sticky') &&
        (r.left < 80 || r.bottom > window.innerHeight - 96 || r.top > window.innerHeight * 0.72);
      return !edgeFloat;
    }
    return false;
  }

  function isFloatingResidue(el) {
    if (!el || !el.getBoundingClientRect || !hasToken(el)) return false;
    if (isProtected(el)) return false;
    var s = window.getComputedStyle(el);
    var r = el.getBoundingClientRect();
    var vw = Math.max(document.documentElement.clientWidth || 0, window.innerWidth || 0);
    var vh = Math.max(document.documentElement.clientHeight || 0, window.innerHeight || 0);
    var fixedish = /^(fixed|absolute|sticky)$/.test(s.position);
    var bottomish = r.top > vh * 0.62 || r.bottom > vh - 120;
    var leftish = r.left < Math.max(520, vw * 0.42);
    var smallish = r.width <= Math.min(720, vw * 0.62) && r.height <= 140;
    var lowZ = Number.isFinite(parseInt(s.zIndex, 10)) ? parseInt(s.zIndex, 10) < 100000 : true;
    return fixedish && bottomish && leftish && smallish && lowZ;
  }

  function findResidueRoot(el) {
    var cur = el;
    for (var i = 0; i < 5 && cur && cur.parentElement && cur.parentElement !== document.body; i++) {
      var p = cur.parentElement;
      var ps = window.getComputedStyle(p);
      var pr = p.getBoundingClientRect();
      if (/^(fixed|absolute|sticky)$/.test(ps.position) && pr.height <= 170 && pr.width <= Math.max(760, window.innerWidth * 0.7)) {
        cur = p;
        continue;
      }
      break;
    }
    return cur || el;
  }

  function removeNode(el) {
    try {
      var root = findResidueRoot(el);
      if (root && root.parentNode) {
        root.setAttribute('data-zops-residue-removed', 'true');
        root.parentNode.removeChild(root);
      }
    } catch (_) {}
  }

  function prune() {
    try {
      var nodes = document.querySelectorAll('body *');
      for (var i = 0; i < nodes.length; i++) {
        var el = nodes[i];
        if (isFloatingResidue(el)) removeNode(el);
      }
      document.documentElement.classList.add('zops-ui-residue-cleanup-v1-ready');
    } catch (_) {}
  }

  function start() {
    prune();
    var n = 0;
    var timer = window.setInterval(function () {
      prune();
      n += 1;
      if (n > 24) window.clearInterval(timer);
    }, 250);
    try {
      var mo = new MutationObserver(function () { window.requestAnimationFrame(prune); });
      mo.observe(document.body || document.documentElement, { childList: true, subtree: true, characterData: true });
    } catch (_) {}
    window.zopsPruneUiResidue = prune;
  }

  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', start, { once: true });
  else start();
})();
