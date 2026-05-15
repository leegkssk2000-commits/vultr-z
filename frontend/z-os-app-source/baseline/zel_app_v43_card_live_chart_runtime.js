/* ZEL APP V43 native card live chart
 * App-only browser runtime. No nginx/caddy/systemd mutation.
 * Purpose: make the existing BTCUSDT market card itself render a rolling live chart.
 * No floating badge. No injected mini-chart panels. No recursive nested cards.
 */
(function () {
  'use strict';
  var VER = 'V43';
  var CF_URL = 'https://lico-canonical-signed-snapshot.tv-sign-proxy.workers.dev/snapshot';
  var POLL_MS = 1000;
  var MAX_TICKS = 90;
  var state = {
    ticks: [],
    lastHash: '',
    lastOk: false,
    lastReason: 'boot',
    lastData: null,
    card: null,
    canvas: null,
    label: null,
    warned: false
  };

  function nowMs() { return Date.now(); }
  function isObj(x) { return x && typeof x === 'object' && !Array.isArray(x); }
  function num(v) {
    if (v === null || v === undefined || v === '') return null;
    if (typeof v === 'number' && isFinite(v)) return v;
    if (typeof v === 'string') {
      var s = v.trim().replace(/,/g, '').replace(/%$/, '');
      if (!s || /^(null|undefined|nan|unbound|missing|none|-)$/i.test(s)) return null;
      var n = Number(s);
      return isFinite(n) ? n : null;
    }
    return null;
  }
  function str(v) { return v === null || v === undefined ? '' : String(v); }
  function hash(s) {
    var h = 2166136261;
    s = String(s || '');
    for (var i = 0; i < s.length; i++) {
      h ^= s.charCodeAt(i);
      h += (h << 1) + (h << 4) + (h << 7) + (h << 8) + (h << 24);
    }
    return (h >>> 0).toString(16);
  }
  function pickFirst() {
    for (var i = 0; i < arguments.length; i++) {
      var v = num(arguments[i]);
      if (v !== null) return v;
    }
    return null;
  }
  function pickString() {
    for (var i = 0; i < arguments.length; i++) {
      var v = arguments[i];
      if (v !== null && v !== undefined && String(v).trim() !== '') return String(v).trim();
    }
    return '';
  }
  function walk(obj, fn, depth) {
    depth = depth || 0;
    if (depth > 8 || !obj) return;
    if (Array.isArray(obj)) {
      for (var i = 0; i < obj.length; i++) walk(obj[i], fn, depth + 1);
      return;
    }
    if (!isObj(obj)) return;
    fn(obj);
    Object.keys(obj).forEach(function (k) { walk(obj[k], fn, depth + 1); });
  }
  function scoreCandidate(o) {
    if (!isObj(o)) return -999;
    var sym = pickString(o.symbol, o.sym, o.ticker, o.market, o.pair);
    var score = 0;
    if (/BTCUSDT/i.test(sym)) score += 60;
    if (num(o.price) !== null || num(o.last) !== null || num(o.mark_price) !== null || num(o.lastPrice) !== null) score += 30;
    if (num(o.pos_pct) !== null || num(o.posPct) !== null || num(o.position_pct) !== null || num(o.position_percent) !== null) score += 15;
    if (num(o.lev) !== null || num(o.leverage) !== null) score += 15;
    if (num(o.liq_buffer_pct) !== null || num(o.liq_buffer) !== null || num(o.liq_buffer_percent) !== null) score += 10;
    if (num(o.funding_8h_pct) !== null || num(o.funding_8h) !== null || num(o.fundingRate) !== null) score += 10;
    if (num(o.DD_day_pct) !== null || num(o.dd_day_pct) !== null || num(o.DD_day) !== null) score += 5;
    if (isObj(o.payload)) score += 20;
    return score;
  }
  function normalize(raw, src) {
    var best = null;
    var bestScore = -999;
    if (isObj(raw) && isObj(raw.payload)) {
      best = raw.payload;
      bestScore = 200;
    }
    walk(raw, function (o) {
      var s = scoreCandidate(o);
      if (s > bestScore) { bestScore = s; best = o; }
    });
    var p = best || {};
    var price = pickFirst(p.price, p.last, p.lastPrice, p.mark_price, p.markPrice, p.close, raw && raw.price);
    var pos = pickFirst(p.pos_pct, p.posPct, p.position_pct, p.positionPercent, p.pos_percent, p.position_percent, p.pos, raw && raw.pos_pct);
    var lev = pickFirst(p.lev, p.leverage, raw && raw.lev);
    var liqBuffer = pickFirst(p.liq_buffer_pct, p.liq_buffer_percent, p.liq_buffer, p.liqBufferPct, raw && raw.liq_buffer_pct);
    var funding = pickFirst(p.funding_8h_pct, p.funding_8h, p.fundingRate, p.funding_rate, raw && raw.funding_8h_pct);
    var ddDay = pickFirst(p.DD_day_pct, p.dd_day_pct, p.DD_day, p.ddDayPct, raw && raw.DD_day_pct);
    var ddTotal = pickFirst(p.DD_total_pct, p.dd_total_pct, p.DD_total, p.ddTotalPct, raw && raw.DD_total_pct);
    var ts = pickFirst(p.source_ts_ms, p.ts_ms, p.timestamp_ms, p.updated_ts_ms, raw && raw.source_ts_ms, raw && raw.ts_ms, raw && raw.updated_ts);
    var symbol = pickString(p.symbol, p.sym, p.ticker, raw && raw.symbol, 'BTCUSDT').toUpperCase();
    if (!/BTCUSDT/.test(symbol)) symbol = 'BTCUSDT';
    var missing = [];
    if (price === null) missing.push('price');
    if (pos === null) missing.push('pos');
    if (lev === null) missing.push('lev');
    var ok = price !== null && pos !== null && lev !== null;
    return {
      ok: ok,
      source: src || 'cf',
      symbol: symbol,
      price: price,
      pos_pct: pos,
      lev: lev,
      liq_buffer_pct: liqBuffer,
      funding_8h_pct: funding,
      DD_day_pct: ddDay,
      DD_total_pct: ddTotal,
      source_ts_ms: ts || nowMs(),
      received_ts_ms: nowMs(),
      missing: missing,
      raw_hash: hash(JSON.stringify(raw || {}).slice(0, 4000))
    };
  }
  function fmt(v, dec, suffix) {
    var n = num(v);
    if (n === null) return '—';
    var d = dec === undefined ? 2 : dec;
    var out = n.toLocaleString('en-US', { maximumFractionDigits: d, minimumFractionDigits: (d && Math.abs(n) < 10 ? Math.min(d, 2) : 0) });
    return out + (suffix || '');
  }
  function pct(v) { return fmt(v, Math.abs(num(v) || 0) < 1 ? 2 : 1, '%'); }
  function escapeHtml(s) { return String(s).replace(/[&<>"']/g, function (c) { return {'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]; }); }

  function removeLegacy() {
    var sel = [
      '.zel-v36-live-panel', '.zel-v37-live-panel', '.zel-v38-live-panel', '.zel-v39-live-panel',
      '.zel-v41-live-card', '.zel-v42-tick-chart', '[data-zel-live-panel]', '[data-zel-v42]'
    ].join(',');
    document.querySelectorAll(sel).forEach(function (el) { if (el && el.parentNode) el.parentNode.removeChild(el); });
    document.querySelectorAll('.zel-v41-lines, .zel-v42-nest-lines').forEach(function (el) { el.classList.remove('zel-v41-lines', 'zel-v42-nest-lines'); });
  }
  function textOf(el) { return (el && el.textContent || '').replace(/\s+/g, ' ').trim(); }
  function candidateScore(el) {
    if (!el || el.nodeType !== 1 || el.matches('script,style,html,body')) return -999;
    if (el.closest('.zel-v43-ignore,[data-zel-v43]')) return -999;
    var t = textOf(el);
    if (!/BTCUSDT/i.test(t)) return -999;
    var r = el.getBoundingClientRect();
    var score = 0;
    if (r.width >= 240 && r.width <= 900) score += 30;
    if (r.height >= 90 && r.height <= 520) score += 30;
    if (/unbound|source-bound|source bound|sig=read/i.test(t)) score += 40;
    if (/risk|proof|hold|liq|receipt|price|pos|lev/i.test(t)) score += 20;
    if (/ETHUSDT|SOLUSDT|XRPUSDT|LINKUSDT/i.test(t)) score -= 80;
    if (/CURRENT ZEL OPERATING|Operational Console|SOURCE HOLD|orders blocked/i.test(t)) score -= 50;
    if (el.querySelector('canvas.zel-v43-native-chart')) score += 100;
    score -= Math.min(80, t.length / 80);
    return score;
  }
  function findBtcCard() {
    var best = null, bestScore = -999;
    var nodes = Array.prototype.slice.call(document.querySelectorAll('div,section,article,li'));
    nodes.forEach(function (el) {
      var s = candidateScore(el);
      if (s > bestScore) { bestScore = s; best = el; }
    });
    return bestScore > 0 ? best : null;
  }
  function replaceStatusText(card, data) {
    if (!card || !data) return;
    var walker = document.createTreeWalker(card, NodeFilter.SHOW_TEXT, {
      acceptNode: function (node) {
        if (!node || !node.nodeValue) return NodeFilter.FILTER_REJECT;
        var p = node.parentElement;
        if (!p || p.closest('[data-zel-v43]')) return NodeFilter.FILTER_REJECT;
        return NodeFilter.FILTER_ACCEPT;
      }
    });
    var changed = 0;
    while (walker.nextNode()) {
      var n = walker.currentNode;
      var s = n.nodeValue;
      var ns = s;
      if (data.ok) ns = ns.replace(/\bunbound\b/gi, 'source-bound').replace(/source-required/gi, 'source-bound');
      if (changed < 6 && ns !== s) { n.nodeValue = ns; changed++; }
    }
  }
  function ensureOverlay(card) {
    if (!card) return null;
    if (state.card !== card) {
      if (state.canvas && state.canvas.parentNode) state.canvas.parentNode.removeChild(state.canvas);
      if (state.label && state.label.parentNode) state.label.parentNode.removeChild(state.label);
      state.card = card;
      state.canvas = null;
      state.label = null;
    }
    card.classList.add('zel-v43-native-live-card');
    card.setAttribute('data-zel-v43-live-card', 'BTCUSDT');
    if (getComputedStyle(card).position === 'static') card.style.position = 'relative';
    Array.prototype.forEach.call(card.children, function (ch) {
      if (!ch.matches('[data-zel-v43]')) {
        ch.style.position = ch.style.position || 'relative';
        ch.style.zIndex = ch.style.zIndex || '2';
      }
    });
    if (!state.canvas || !card.contains(state.canvas)) {
      var cv = document.createElement('canvas');
      cv.className = 'zel-v43-native-chart';
      cv.setAttribute('data-zel-v43', 'canvas');
      cv.setAttribute('aria-hidden', 'true');
      card.insertBefore(cv, card.firstChild);
      state.canvas = cv;
    }
    if (!state.label || !card.contains(state.label)) {
      var lb = document.createElement('div');
      lb.className = 'zel-v43-native-label';
      lb.setAttribute('data-zel-v43', 'label');
      lb.textContent = 'LIVE CF';
      card.appendChild(lb);
      state.label = lb;
    }
    return state.canvas;
  }
  function draw() {
    if (!state.canvas) return;
    var c = state.canvas;
    var card = state.card;
    if (!card || !document.body.contains(card)) return;
    var r = c.getBoundingClientRect();
    var dpr = Math.max(1, window.devicePixelRatio || 1);
    var w = Math.max(220, Math.floor(r.width));
    var h = Math.max(80, Math.floor(r.height));
    if (c.width !== Math.floor(w * dpr) || c.height !== Math.floor(h * dpr)) {
      c.width = Math.floor(w * dpr); c.height = Math.floor(h * dpr);
    }
    var ctx = c.getContext('2d');
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    ctx.clearRect(0, 0, w, h);
    ctx.globalAlpha = 1;
    var ticks = state.ticks.slice(-MAX_TICKS);
    var padL = 10, padR = 10, padT = 10, padB = 18;
    var innerW = w - padL - padR;
    var innerH = h - padT - padB;
    ctx.fillStyle = 'rgba(0,0,0,0.10)';
    ctx.fillRect(0, 0, w, h);
    ctx.strokeStyle = 'rgba(92, 224, 255, .16)';
    ctx.lineWidth = 1;
    for (var gy = 0; gy < 4; gy++) {
      var y = padT + (innerH * gy / 3);
      ctx.beginPath(); ctx.moveTo(padL, y); ctx.lineTo(w - padR, y); ctx.stroke();
    }
    if (!ticks.length) return;
    var vals = ticks.map(function (t) { return t.price; }).filter(function (v) { return v !== null; });
    if (!vals.length) return;
    var min = Math.min.apply(Math, vals), max = Math.max.apply(Math, vals);
    if (min === max) { min -= Math.max(1, min * 0.0005); max += Math.max(1, max * 0.0005); }
    var yOf = function (p) { return padT + (max - p) / (max - min) * innerH; };
    var xOf = function (i) { return padL + (ticks.length <= 1 ? innerW : i * innerW / (ticks.length - 1)); };
    ctx.beginPath();
    ticks.forEach(function (t, i) {
      var x = xOf(i), y = yOf(t.price);
      if (i === 0) ctx.moveTo(x, y); else ctx.lineTo(x, y);
    });
    ctx.strokeStyle = 'rgba(96, 232, 255, .95)';
    ctx.lineWidth = 2;
    ctx.stroke();
    var last = ticks[ticks.length - 1];
    var lx = xOf(ticks.length - 1), ly = yOf(last.price);
    ctx.fillStyle = state.lastOk ? 'rgba(0, 255, 183, .95)' : 'rgba(255, 211, 0, .95)';
    ctx.beginPath(); ctx.arc(lx, ly, 4, 0, Math.PI * 2); ctx.fill();
    ctx.font = '11px ui-monospace, SFMono-Regular, Menlo, Consolas, monospace';
    ctx.fillStyle = 'rgba(220,245,255,.85)';
    ctx.fillText(fmt(last.price, 2), padL + 2, Math.max(13, ly - 8));
  }
  function pushTick(data) {
    if (!data) return;
    var price = num(data.price);
    if (price === null) return;
    var t = { t: nowMs(), price: price, data: data };
    state.ticks.push(t);
    if (state.ticks.length > MAX_TICKS) state.ticks = state.ticks.slice(-MAX_TICKS);
  }
  function updateCard(data) {
    removeLegacy();
    var card = findBtcCard();
    if (!card) return;
    ensureOverlay(card);
    if (data && data.ok) replaceStatusText(card, data);
    if (state.label) {
      var age = data ? Math.max(0, nowMs() - (num(data.source_ts_ms) || nowMs())) : 0;
      state.label.textContent = (data && data.ok ? 'SOURCE BOUND' : 'SOURCE HOLD') + ' · ' + (data && data.price !== null ? fmt(data.price, 2) : 'missing') + ' · age ' + Math.round(age) + 'ms';
      state.label.classList.toggle('is-hold', !(data && data.ok));
    }
    card.setAttribute('data-zel-v43-status', data && data.ok ? 'source-bound' : 'source-hold');
    card.setAttribute('data-zel-v43-price', data && data.price !== null ? String(data.price) : '');
    draw();
  }
  function fetchJson(url, timeoutMs) {
    timeoutMs = timeoutMs || 2500;
    var ctrl = typeof AbortController !== 'undefined' ? new AbortController() : null;
    var to = ctrl ? setTimeout(function () { ctrl.abort(); }, timeoutMs) : null;
    return fetch(url + (url.indexOf('?') >= 0 ? '&' : '?') + 'v=' + Date.now(), {
      cache: 'no-store',
      credentials: 'omit',
      mode: 'cors',
      signal: ctrl && ctrl.signal
    }).then(function (r) {
      if (to) clearTimeout(to);
      if (!r.ok) throw new Error('http_' + r.status);
      var ct = (r.headers.get('content-type') || '').toLowerCase();
      return r.text().then(function (txt) {
        if (/^\s*</.test(txt)) throw new Error('html_route');
        try { return JSON.parse(txt); } catch (e) { throw new Error('json_parse'); }
      });
    });
  }
  function sourceCandidates() {
    var arr = [];
    // CF direct first: avoids app route returning HTML.
    arr.push({ name: 'cf', url: CF_URL });
    // Local routes are fallback only. If they return HTML, they are ignored.
    arr.push({ name: 'app_source', url: '/zel_source_envelope_live.json' });
    arr.push({ name: 'app_norm', url: '/zel_live_normalized.json' });
    arr.push({ name: 'alimi_static', url: '/static/alimi_today_state_latest.json' });
    return arr;
  }
  function poll() {
    var list = sourceCandidates();
    var chain = Promise.reject(new Error('start'));
    list.forEach(function (cand) {
      chain = chain.catch(function () {
        return fetchJson(cand.url, 2200).then(function (raw) {
          var d = normalize(raw, cand.name);
          if (!d.ok && cand.name === 'cf') throw new Error('cf_missing_' + d.missing.join(','));
          return d;
        });
      });
    });
    chain.then(function (d) {
      state.lastData = d;
      state.lastOk = !!d.ok;
      state.lastReason = d.ok ? 'ok' : ('missing:' + d.missing.join(','));
      pushTick(d);
      updateCard(d);
    }).catch(function (e) {
      state.lastOk = false;
      state.lastReason = String(e && e.message || e || 'fetch_fail');
      updateCard(state.lastData || { ok: false, symbol: 'BTCUSDT', price: null, pos_pct: null, lev: null, missing: ['cf_fetch'], source_ts_ms: nowMs() });
    });
  }
  function boot() {
    removeLegacy();
    updateCard(state.lastData);
    poll();
    setInterval(poll, POLL_MS);
    setInterval(function () { updateCard(state.lastData); }, 1200);
    window.addEventListener('resize', function () { draw(); });
    window.ZEL_APP_V43_CARD_NATIVE_LIVE = {
      version: VER,
      state: state,
      poll: poll,
      normalize: normalize,
      findCard: findBtcCard
    };
  }
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', boot, { once: true }); else boot();
})();
