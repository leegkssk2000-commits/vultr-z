/* ZEL APP V55 UI-only strip guard
 * Keeps current live-feed JS. No feed/router/server mutation.
 * Only: hide live feed text, center existing sparkline, remove legacy static thin strip.
 */
(function () {
  'use strict';
  var VER = 'V55';
  var CARD_SEL = '.zel-v54-live-card,.zel-v47-live-card,[data-zel-live-card]';
  var WRAP_SEL = '.zel-v54-spark-wrap,.zel-v47-spark-wrap,[data-zel-live-spark-wrap]';

  function cls() {
    try { document.documentElement.classList.add('zel-v55-ui-tight'); } catch (_) {}
  }

  function txt(el) {
    try { return (el.textContent || '').replace(/\s+/g, ' ').trim(); } catch (_) { return ''; }
  }

  function hasLiveCanvas(el) {
    try { return !!(el && (el.matches && el.matches(WRAP_SEL) || el.closest && el.closest(WRAP_SEL) || el.querySelector && el.querySelector('canvas'))); } catch (_) { return false; }
  }

  function looksLikeLegacyStrip(el, card) {
    if (!el || !card || hasLiveCanvas(el)) return false;
    var name = (el.className || '').toString().toLowerCase();
    if (name.indexOf('chip') >= 0 || name.indexOf('pill') >= 0 || name.indexOf('badge') >= 0 || name.indexOf('tag') >= 0) return false;
    var t = txt(el);
    if (t.length > 0) return false;
    var r, cr, cs;
    try {
      r = el.getBoundingClientRect();
      cr = card.getBoundingClientRect();
      cs = getComputedStyle(el);
    } catch (_) { return false; }
    if (!r || !cr || !cs) return false;
    if (r.width < Math.min(92, Math.max(70, cr.width * 0.34))) return false;
    if (r.height < 2 || r.height > 9) return false;
    if (r.left < cr.left - 2 || r.right > cr.right + 2) return false;
    if (cs.display === 'none' || cs.visibility === 'hidden') return false;
    var bg = (cs.backgroundColor || '').replace(/\s+/g, '').toLowerCase();
    var hasBg = bg && bg !== 'transparent' && bg !== 'rgba(0,0,0,0)' && bg !== 'rgba(0,0,0,0.0)';
    var borderish = (parseFloat(cs.borderTopWidth) || 0) > 0 || (parseFloat(cs.borderBottomWidth) || 0) > 0;
    return hasBg || borderish;
  }

  function hideLegacyStrips(card) {
    if (!card) return;
    try {
      var nodes = card.querySelectorAll('div,span,i,b');
      for (var i = 0; i < nodes.length; i += 1) {
        if (looksLikeLegacyStrip(nodes[i], card)) {
          nodes[i].setAttribute('data-zel-v55-hidden-static-bar', '1');
        }
      }
    } catch (_) {}
  }

  function tagLiveStatus(card) {
    if (!card) return;
    try {
      var nodes = card.querySelectorAll('div,span,p,small,b');
      for (var i = 0; i < nodes.length; i += 1) {
        var s = txt(nodes[i]);
        if (/^LIVE\s+(REST|FEED|WS)\b/i.test(s) || /^LIVE\s+binance/i.test(s)) {
          nodes[i].setAttribute('data-zel-feed-status', '1');
        }
      }
    } catch (_) {}
  }

  function centerWraps(card) {
    if (!card) return;
    try {
      var wraps = card.querySelectorAll(WRAP_SEL);
      for (var i = 0; i < wraps.length; i += 1) wraps[i].setAttribute('data-zel-live-spark-wrap', '1');
    } catch (_) {}
  }

  function apply() {
    cls();
    try {
      var cards = document.querySelectorAll(CARD_SEL);
      for (var i = 0; i < cards.length; i += 1) {
        cards[i].setAttribute('data-zel-live-card', '1');
        tagLiveStatus(cards[i]);
        centerWraps(cards[i]);
        hideLegacyStrips(cards[i]);
      }
    } catch (_) {}
  }

  function boot() {
    apply();
    setInterval(apply, 900);
    try {
      new MutationObserver(function () { apply(); }).observe(document.documentElement, { childList: true, subtree: true, attributes: true });
    } catch (_) {}
    try { window.ZEL_APP_V55_UI_TIGHT = { ok: true, version: VER }; } catch (_) {}
  }

  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', boot, { once: true });
  else boot();
})();
