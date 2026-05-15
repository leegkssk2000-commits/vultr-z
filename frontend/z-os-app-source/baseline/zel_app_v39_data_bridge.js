/* ZEL APP V39 data bridge: no visible UI. Removes legacy floating badges, exposes normalized live data only. */
(function () {
  'use strict';
  var VER = 'V39';
  var HISTORY_LIMIT = 160;
  var lastKey = '';
  var history = [];

  function number(v) {
    if (v === null || v === undefined || v === '' || v === '?' || v === 'unbound') return null;
    if (typeof v === 'number') return isFinite(v) ? v : null;
    var n = Number(String(v).replace(/,/g, '').replace(/%/g, ''));
    return isFinite(n) ? n : null;
  }

  function normalizeClient(obj) {
    obj = obj && typeof obj === 'object' ? obj : {};
    var src = obj.payload && typeof obj.payload === 'object' ? obj.payload : obj;
    var out = Object.assign({}, obj);
    out.symbol = out.symbol || src.symbol || src.ticker || 'BTCUSDT';
    out.price = number(out.price != null ? out.price : (out.price_usdt != null ? out.price_usdt : src.price || src.price_usdt || src.last_price));
    out.pos_pct = number(out.pos_pct != null ? out.pos_pct : (src.pos_pct != null ? src.pos_pct : src.pos));
    out.lev = number(out.lev != null ? out.lev : (src.lev != null ? src.lev : src.lev_x));
    out.source_ts_ms = number(out.source_ts_ms != null ? out.source_ts_ms : (src.source_ts_ms || src.ts_ms || src.updated_ts));
    out.entry_ts_ms = number(out.entry_ts_ms != null ? out.entry_ts_ms : (src.entry_ts_ms || src.entry_ts));
    if (!out.entry_ts_ms && out.source_ts_ms) {
      out.entry_ts_ms = out.source_ts_ms;
      out.entry_ts_source = 'source_ts_ms_fallback';
      out.entry_ts_verified = false;
    }
    out.age_ms = number(out.age_ms);
    if (out.source_ts_ms) out.age_ms = Math.max(0, Date.now() - out.source_ts_ms);
    out.missing = Array.isArray(out.missing) ? out.missing.filter(function (x) { return x !== 'entry_ts' || !out.entry_ts_ms; }) : [];
    out.min_data_complete = out.missing.length === 0;
    out.order_authority = 'blocked';
    out.read_only = true;
    return out;
  }

  function publish(obj, rawEnvelope) {
    var n = normalizeClient(obj);
    var key = [n.symbol, n.price, n.pos_pct, n.lev, n.source_ts_ms, n.entry_ts_ms].join('|');
    window.ZEL_APP_LIVE = n;
    window.ZEL_APP_LIVE_NORMALIZED = n;
    window.ZEL_APP_SOURCE_ENVELOPE = rawEnvelope || window.ZEL_APP_SOURCE_ENVELOPE || null;
    window.__ZEL_APP_V39_LIVE__ = n;
    window.__ZEL_APP_V39_HISTORY__ = history;
    if (key !== lastKey) {
      lastKey = key;
      history.push({ ts: Date.now(), price: n.price, source_ts_ms: n.source_ts_ms, age_ms: n.age_ms, symbol: n.symbol });
      if (history.length > HISTORY_LIMIT) history.shift();
      try { window.dispatchEvent(new CustomEvent('zel:live-data', { detail: n })); } catch (e) {}
    }
  }

  function fetchJson(url) {
    return fetch(url + (url.indexOf('?') >= 0 ? '&' : '?') + 'v=' + Date.now(), { cache: 'no-store' }).then(function (r) {
      if (!r.ok) throw new Error('HTTP ' + r.status);
      return r.json();
    });
  }

  function tick() {
    Promise.allSettled([
      fetchJson('/zel_live_normalized.json'),
      fetchJson('/zel_source_envelope_live.json')
    ]).then(function (res) {
      var norm = res[0].status === 'fulfilled' ? res[0].value : null;
      var env = res[1].status === 'fulfilled' ? res[1].value : null;
      publish(norm || env || {}, env);
    }).catch(function () {});
  }

  function isLegacySourceBadge(el) {
    if (!el || el === document.body || el === document.documentElement) return false;
    var cs;
    try { cs = getComputedStyle(el); } catch (e) { return false; }
    var pos = cs.position;
    if (pos !== 'fixed' && pos !== 'sticky') return false;
    var txt = (el.innerText || el.textContent || '').replace(/\s+/g, ' ').trim();
    if (!txt) return false;
    var bottom = parseFloat(cs.bottom || '9999');
    var right = parseFloat(cs.right || '9999');
    var nearBottom = isFinite(bottom) && bottom <= 140;
    var nearRight = isFinite(right) && right <= 160;
    var legacyText = /SOURCE\s+(BOUND|HOLD)\s+V(25|30|31|32|33|34|35|36|37|38)\b/i.test(txt) || /missing\s*:\s*entry_ts/i.test(txt);
    return legacyText && (nearBottom || nearRight);
  }

  function killLegacyBadges() {
    var nodes = document.querySelectorAll('body *');
    for (var i = 0; i < nodes.length; i++) {
      var el = nodes[i];
      if (isLegacySourceBadge(el)) {
        el.setAttribute('data-zel-v39-hidden', 'legacy-source-badge');
        el.style.setProperty('display', 'none', 'important');
        el.style.setProperty('visibility', 'hidden', 'important');
        el.style.setProperty('pointer-events', 'none', 'important');
      }
    }
  }

  function boot() {
    document.documentElement.setAttribute('data-zel-app-v39', 'data-only-no-float');
    tick();
    setInterval(tick, 2000);
    killLegacyBadges();
    setInterval(killLegacyBadges, 1000);
    try { new MutationObserver(killLegacyBadges).observe(document.body || document.documentElement, { childList: true, subtree: true, characterData: true }); } catch (e) {}
  }

  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', boot);
  else boot();
})();
