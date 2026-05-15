/* ZEL APP V41 BTC LIVE BRIDGE
 * App-only/browser-only. No order mutation. No nginx/caddy/systemd mutation.
 * Purpose: remove legacy floating source badges, bind BTCUSDT card to CF source, render live sparkline in-card.
 */
(function () {
  'use strict';
  var VER = 'V41';
  var CF_URL = 'https://lico-canonical-signed-snapshot.tv-sign-proxy.workers.dev/snapshot';
  var POLL_MS = 1200;
  var MAX_SAMPLES = 90;
  var history = [];
  var lastNorm = null;
  var startTs = Date.now();

  function n(v) {
    if (v === null || v === undefined || v === '') return null;
    if (typeof v === 'number') return Number.isFinite(v) ? v : null;
    var s = String(v).replace(/,/g, '').replace(/%/g, '').trim();
    var x = Number(s);
    return Number.isFinite(x) ? x : null;
  }

  function pick(obj, keys) {
    if (!obj) return null;
    for (var i = 0; i < keys.length; i++) {
      var k = keys[i];
      if (Object.prototype.hasOwnProperty.call(obj, k) && obj[k] !== undefined && obj[k] !== null && obj[k] !== '') return obj[k];
    }
    return null;
  }

  function payloadOf(raw) {
    if (!raw || typeof raw !== 'object') return {};
    if (raw.payload && typeof raw.payload === 'object') return raw.payload;
    if (raw.data && typeof raw.data === 'object') return raw.data;
    return raw;
  }

  function normalize(raw) {
    var p = payloadOf(raw);
    var now = Date.now();
    var symbol = String(pick(p, ['symbol', 'ticker', 'pair']) || pick(raw, ['symbol']) || 'BTCUSDT').toUpperCase();
    var price = n(pick(p, ['price', 'mark_price', 'last', 'last_price', 'close']));
    var pos = n(pick(p, ['pos_pct', 'pos%', 'position_pct', 'position_percent', 'pos', 'position']));
    var lev = n(pick(p, ['lev', 'leverage']));
    var liqBuf = n(pick(p, ['liq_buffer_pct', 'liq_buffer%', 'liq_buffer', 'liqBufferPct']));
    var funding = n(pick(p, ['funding_8h_pct', 'funding_8h%', 'funding_8h', 'funding']));
    var ddDay = n(pick(p, ['DD_day_pct', 'DD_day%', 'dd_day_pct', 'ddDayPct', 'DD_day']));
    var ddTotal = n(pick(p, ['DD_total_pct', 'DD_total%', 'dd_total_pct', 'ddTotalPct', 'DD_total']));
    var sourceTs = n(pick(p, ['source_ts_ms', 'ts_ms', 'timestamp_ms', 'updated_ts_ms']) || pick(raw, ['source_ts_ms', 'ts_ms', 'updated_ts']));
    var entryTs = pick(p, ['entry_ts', 'entry_time', 'entry_ts_ms']);
    var entrySource = 'source';
    if (!entryTs || entryTs === 0 || entryTs === '0') {
      entryTs = sourceTs || now;
      entrySource = 'fallback_source_ts';
    }
    if (price === null && lastNorm && lastNorm.price !== null) price = lastNorm.price;
    if (pos === null && lastNorm && lastNorm.pos_pct !== null) pos = lastNorm.pos_pct;
    if (lev === null && lastNorm && lastNorm.lev !== null) lev = lastNorm.lev;
    if (liqBuf === null && lastNorm && lastNorm.liq_buffer_pct !== null) liqBuf = lastNorm.liq_buffer_pct;
    if (funding === null && lastNorm && lastNorm.funding_8h_pct !== null) funding = lastNorm.funding_8h_pct;
    if (ddDay === null && lastNorm && lastNorm.DD_day_pct !== null) ddDay = lastNorm.DD_day_pct;
    if (ddTotal === null && lastNorm && lastNorm.DD_total_pct !== null) ddTotal = lastNorm.DD_total_pct;
    var missing = [];
    if (price === null) missing.push('price');
    if (pos === null) missing.push('pos_pct');
    if (lev === null) missing.push('lev');
    if (liqBuf === null) missing.push('liq_buffer_pct');
    if (funding === null) missing.push('funding_8h_pct');
    if (ddDay === null) missing.push('DD_day_pct');
    if (ddTotal === null) missing.push('DD_total_pct');
    return {
      ok: raw && raw.ok !== false,
      source: String(raw.source || p.source || 'cf'),
      symbol: symbol,
      price: price,
      pos_pct: pos,
      lev: lev,
      liq_buffer_pct: liqBuf,
      funding_8h_pct: funding,
      DD_day_pct: ddDay,
      DD_total_pct: ddTotal,
      source_ts_ms: sourceTs || now,
      entry_ts: entryTs,
      entry_ts_source: entrySource,
      missing: missing,
      fetched_ts_ms: now,
      version: VER
    };
  }

  function fmt(v, suffix, decimals) {
    if (v === null || v === undefined || Number.isNaN(v)) return '—';
    var x = Number(v);
    if (!Number.isFinite(x)) return String(v);
    var d = decimals === undefined ? 2 : decimals;
    var s = x.toLocaleString(undefined, { maximumFractionDigits: d, minimumFractionDigits: 0 });
    return s + (suffix || '');
  }

  function isLegacyBadge(el) {
    if (!el || !el.textContent) return false;
    var t = el.textContent.replace(/\s+/g, ' ').trim();
    if (!/SOURCE\s+(BOUND|HOLD)/i.test(t)) return false;
    if (!/(V25|V34|missing:|BTCUSDT|age_ms|price)/i.test(t)) return false;
    var cs = window.getComputedStyle(el);
    var fixedish = cs.position === 'fixed' || cs.position === 'sticky' || cs.position === 'absolute';
    var low = parseFloat(cs.bottom || '9999') < 96 || parseFloat(cs.top || '9999') > window.innerHeight - 120;
    var small = el.getBoundingClientRect && (el.getBoundingClientRect().height <= 80);
    return fixedish && (low || small);
  }

  function cleanLegacyBadges() {
    try {
      var nodes = document.querySelectorAll('body *');
      nodes.forEach(function (el) {
        if (isLegacyBadge(el)) el.remove();
      });
      document.documentElement.classList.add('zel-v41-no-float-badge');
    } catch (e) {}
  }

  function findCards() {
    var candidates = Array.prototype.slice.call(document.querySelectorAll('section, article, div, li'));
    function cardFor(sym) {
      sym = sym.toUpperCase();
      var best = null, bestScore = -1;
      candidates.forEach(function (el) {
        var tx = (el.textContent || '').toUpperCase();
        if (tx.indexOf(sym) < 0) return;
        var r = el.getBoundingClientRect ? el.getBoundingClientRect() : { width: 0, height: 0 };
        if (r.width < 100 || r.height < 60 || r.width > 900 || r.height > 700) return;
        var score = 0;
        if (/SOURCE-BOUND|UNBOUND|RISK=HOLD|PROOF=MISSING|SIG=READ_ONLY/.test(tx)) score += 5;
        if (r.width < 600 && r.height < 360) score += 3;
        score -= Math.abs(r.width - 430) / 100 + Math.abs(r.height - 230) / 100;
        if (score > bestScore) { best = el; bestScore = score; }
      });
      return best;
    }
    return { btc: cardFor('BTCUSDT') };
  }

  function ensureGraph(card) {
    if (!card) return null;
    card.classList.add('zel-v41-live-card');
    var wrap = card.querySelector('.zel-v41-graph-wrap');
    if (!wrap) {
      wrap = document.createElement('div');
      wrap.className = 'zel-v41-graph-wrap';
      wrap.innerHTML = '<div class="zel-v41-graph-head"><b>BTCUSDT live CF</b><span class="zel-v41-status">binding…</span></div><canvas class="zel-v41-canvas" width="640" height="130"></canvas><div class="zel-v41-metrics"></div>';
      card.appendChild(wrap);
    }
    return wrap;
  }

  function draw(canvas, rows) {
    if (!canvas || !canvas.getContext) return;
    var dpr = window.devicePixelRatio || 1;
    var w = canvas.clientWidth || 640, h = canvas.clientHeight || 130;
    if (canvas.width !== Math.floor(w * dpr) || canvas.height !== Math.floor(h * dpr)) {
      canvas.width = Math.floor(w * dpr); canvas.height = Math.floor(h * dpr);
    }
    var ctx = canvas.getContext('2d');
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    ctx.clearRect(0, 0, w, h);
    ctx.globalAlpha = 1;
    ctx.lineWidth = 1;
    ctx.strokeStyle = 'rgba(120,235,255,.18)';
    for (var gy = 20; gy < h; gy += 28) { ctx.beginPath(); ctx.moveTo(0, gy); ctx.lineTo(w, gy); ctx.stroke(); }
    var vals = rows.map(function (r) { return r.price; }).filter(function (x) { return Number.isFinite(x); });
    if (!vals.length) return;
    var min = Math.min.apply(Math, vals), max = Math.max.apply(Math, vals);
    if (min === max) { min -= Math.max(1, min * 0.0001); max += Math.max(1, max * 0.0001); }
    var xstep = rows.length > 1 ? w / (rows.length - 1) : w;
    ctx.strokeStyle = 'rgba(105,230,255,.95)'; ctx.lineWidth = 2;
    ctx.beginPath();
    rows.forEach(function (r, i) {
      var x = i * xstep;
      var y = h - 16 - ((r.price - min) / (max - min)) * (h - 32);
      if (i === 0) ctx.moveTo(x, y); else ctx.lineTo(x, y);
    });
    ctx.stroke();
    var last = rows[rows.length - 1];
    var lx = (rows.length - 1) * xstep;
    var ly = h - 16 - ((last.price - min) / (max - min)) * (h - 32);
    ctx.fillStyle = 'rgba(0,255,170,.95)'; ctx.beginPath(); ctx.arc(lx, ly, 4.5, 0, Math.PI * 2); ctx.fill();
    ctx.fillStyle = 'rgba(220,245,255,.92)'; ctx.font = '12px ui-monospace, SFMono-Regular, Menlo, monospace';
    ctx.fillText('min ' + Math.round(min) + '  max ' + Math.round(max) + '  samples ' + rows.length, 8, 16);
  }

  function updateBTC(norm) {
    if (!norm || norm.symbol !== 'BTCUSDT') return;
    var cards = findCards();
    var card = cards.btc;
    var wrap = ensureGraph(card);
    if (!wrap) return;
    var oldText = (card.textContent || '').toLowerCase();
    // Safe text upgrade only for direct text nodes, avoid destroying existing app structure.
    try {
      if (oldText.indexOf('unbound') >= 0) card.classList.add('zel-v41-bound');
    } catch (e) {}
    var price = norm.price;
    if (price !== null) {
      history.push({ ts: norm.fetched_ts_ms, price: price });
      if (history.length > MAX_SAMPLES) history.shift();
    }
    var status = wrap.querySelector('.zel-v41-status');
    var age = Math.max(0, Date.now() - (norm.source_ts_ms || Date.now()));
    var delta = history.length > 1 ? history[history.length - 1].price - history[0].price : 0;
    if (status) status.textContent = (norm.missing.length ? 'SOURCE HOLD · missing ' + norm.missing.join(',') : 'SOURCE BOUND') + ' · age ' + age + 'ms · Δ ' + fmt(delta, '', 2);
    var metrics = wrap.querySelector('.zel-v41-metrics');
    if (metrics) metrics.innerHTML = '' +
      '<span>price <b>' + fmt(norm.price, '', 2) + '</b></span>' +
      '<span>pos <b>' + fmt(norm.pos_pct, '%', 2) + '</b></span>' +
      '<span>lev <b>' + fmt(norm.lev, 'x', 2) + '</b></span>' +
      '<span>liq <b>' + fmt(norm.liq_buffer_pct, '%', 2) + '</b></span>' +
      '<span>funding8h <b>' + fmt(norm.funding_8h_pct, '%', 4) + '</b></span>' +
      '<span>DD_day <b>' + fmt(norm.DD_day_pct, '%', 2) + '</b></span>' +
      '<span>entry <b>' + (norm.entry_ts_source === 'fallback_source_ts' ? 'source_ts fallback' : 'source') + '</b></span>';
    draw(wrap.querySelector('canvas'), history);
  }

  function updateLegacyTexts(norm) {
    // Minimal, conservative text-node update: converts visible BTCUSDT unbound label to source-bound without rebuilding cards.
    try {
      var walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT, null);
      var node, count = 0;
      while ((node = walker.nextNode()) && count < 20) {
        var txt = node.nodeValue;
        if (/unbound/i.test(txt) && node.parentElement && (node.parentElement.closest('section,article,div') || {}).textContent && /BTCUSDT/i.test((node.parentElement.closest('section,article,div') || {}).textContent)) {
          node.nodeValue = txt.replace(/unbound/ig, 'source-bound');
          count++;
        }
      }
    } catch (e) {}
  }

  function expose(norm) {
    window.ZEL_APP_LIVE_DATA = norm;
    window.ZEL_APP_LIVE_HISTORY = history.slice();
    try { localStorage.setItem('ZEL_APP_LIVE_DATA_V41', JSON.stringify(norm)); } catch (e) {}
  }

  async function poll() {
    cleanLegacyBadges();
    try {
      var res = await fetch(CF_URL + '?v=' + Date.now(), { cache: 'no-store', credentials: 'omit' });
      if (!res.ok) throw new Error('cf_http_' + res.status);
      var raw = await res.json();
      var norm = normalize(raw);
      lastNorm = norm;
      expose(norm);
      updateLegacyTexts(norm);
      updateBTC(norm);
    } catch (err) {
      var fallback = lastNorm || { symbol: 'BTCUSDT', price: null, pos_pct: null, lev: null, liq_buffer_pct: null, funding_8h_pct: null, DD_day_pct: null, DD_total_pct: null, source_ts_ms: Date.now(), entry_ts: Date.now(), entry_ts_source: 'fallback_source_ts', missing: ['cf_fetch'], error: String(err), version: VER };
      expose(fallback);
      updateBTC(fallback);
    }
  }

  function boot() {
    cleanLegacyBadges();
    poll();
    setInterval(poll, POLL_MS);
    setInterval(cleanLegacyBadges, 900);
    console.info('[ZEL_APP_V41] app-only BTC live bridge loaded', { since: startTs, source: CF_URL });
  }

  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', boot, { once: true });
  else boot();
})();
