/* ZEL APP LIVE DATA BRIDGE V38
 * Scope: app.z-os.vip only. Data-only runtime. No visual DOM, no floating badge, no graph panel.
 * Exposes: window.ZEL_LIVE_NORMALIZED and dispatches Event('zel:live-data').
 */
(function(){
  'use strict';
  var MARK='ZEL_APP_V38_DATA_ONLY_CLEAN_UI_20260514';
  if (window.__ZEL_V38_DATA_BRIDGE__) return;
  window.__ZEL_V38_DATA_BRIDGE__ = true;

  function removeInjectedUi(){
    var selectors = [
      '#zel-v36-btc-panel',
      '#zel-v36-btc-live-panel',
      '#zel-v37-live-panel',
      '#zel-live-normalize-panel',
      '#zel-live-normalized-panel',
      '#zelSourceBoundBadge',
      '#zel-source-bound-badge',
      '.zel-source-bound-badge',
      '.zel-floating-source-badge',
      '.zel-v36-btc-live',
      '.zel-live-normalized-card',
      '[data-zel-overlay="source-bound"]',
      '[data-zel-panel="btc-live"]',
      '[data-zel-runtime="v36"]',
      '[data-zel-runtime="v37-ui"]'
    ];
    selectors.forEach(function(sel){
      document.querySelectorAll(sel).forEach(function(n){ try { n.remove(); } catch(e) {} });
    });
  }

  function compact(v){
    if (v === null || v === undefined || v === '') return null;
    var n = Number(v);
    return Number.isFinite(n) ? n : v;
  }

  function normalize(raw){
    raw = raw && typeof raw === 'object' ? raw : {};
    var payload = raw.payload && typeof raw.payload === 'object' ? raw.payload : raw;
    var risk = payload.risk || raw.risk || {};
    var decision = payload.decision || raw.decision || {};
    var out = {
      ok: raw.ok === true || payload.ok === true,
      source: raw.source || payload.source || 'cf',
      symbol: payload.symbol || raw.symbol || 'BTCUSDT',
      price: compact(payload.price || raw.price),
      pos_pct: compact(payload.pos_pct || payload.pos || raw.pos_pct || raw.pos),
      lev: compact(payload.lev || raw.lev),
      liq_buffer_pct: compact(payload.liq_buffer_pct || payload.liq_buffer || risk.liq_buffer_pct || risk.liq_buffer),
      funding_8h_pct: compact(payload.funding_8h_pct || payload.funding_8h || risk.funding_8h_pct || risk.funding_8h),
      DD_day_pct: compact(payload.DD_day_pct || payload.DD_day || risk.DD_day_pct || risk.DD_day),
      DD_total_pct: compact(payload.DD_total_pct || payload.DD_total || risk.DD_total_pct || risk.DD_total),
      action: payload.action || raw.action || decision.action || 'hold',
      source_ts_ms: compact(payload.source_ts_ms || raw.source_ts_ms || payload.ts_ms || raw.ts_ms),
      source_hash: raw.source_hash || payload.source_hash || raw.hash || payload.hash || null,
      marker: MARK,
      updated_client_ms: Date.now()
    };
    var ts = Number(out.source_ts_ms || 0);
    out.age_ms = ts > 0 ? Math.max(0, Date.now() - ts) : null;
    out.bound = out.ok === true && out.symbol === 'BTCUSDT' && Number.isFinite(Number(out.price)) && Number.isFinite(Number(out.pos_pct)) && Number.isFinite(Number(out.lev));
    return out;
  }

  function publish(data){
    window.ZEL_LIVE_NORMALIZED = data;
    try { window.dispatchEvent(new CustomEvent('zel:live-data', {detail:data})); } catch(e) {}
  }

  function fetchJson(url){
    return fetch(url + (url.indexOf('?') >= 0 ? '&' : '?') + 'v=' + Date.now(), {cache:'no-store'})
      .then(function(r){ if (!r.ok) throw new Error('HTTP '+r.status); return r.json(); });
  }

  function tick(){
    removeInjectedUi();
    fetchJson('/zel_live_normalized.json')
      .then(function(j){ publish(normalize(j)); })
      .catch(function(){
        return fetchJson('/zel_source_envelope_live.json').then(function(j){ publish(normalize(j)); });
      })
      .catch(function(){ /* keep last known data */ });
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', removeInjectedUi, {once:true});
  } else {
    removeInjectedUi();
  }
  tick();
  setInterval(tick, 2000);
})();
