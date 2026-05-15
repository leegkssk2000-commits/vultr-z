/* ZEL APP V49 native market live feed
 * App-only browser runtime. No nginx/caddy/systemd/server mutation.
 * Purpose: exchange live feed -> existing market cards render real price + native sparkline.
 * No nested visible panels. No floating badges. Order/proof/source truth remains RO/HOLD.
 */
(function () {
  'use strict';
  var VERSION = 'V49_NATIVE_MARKET_LIVE_FEED_APP_ONLY';
  if (window.ZEL_APP_V49_LIVE && window.ZEL_APP_V49_LIVE.version === VERSION) return;

  var SYMBOLS = ['BTCUSDT', 'ETHUSDT', 'SOLUSDT', 'XRPUSDT', 'LINKUSDT'];
  var MAX_POINTS = 120;
  var RENDER_MS = 500;
  var SCAN_MS = 1600;
  var REST_MS = 2500;
  var STALE_MS = 12000;

  var state = {};
  SYMBOLS.forEach(function (sym) {
    state[sym] = { symbol: sym, price: null, prev: null, delta: null, ts: 0, ticks: 0, source: 'none', ok: false, history: [] };
  });

  var timers = [];
  var ws = null;
  var reconnectTimer = null;
  var reconnectDelay = 1200;
  var endpointIndex = 0;

  window.ZEL_APP_V49_LIVE = { version: VERSION, state: state, stop: stop, connect: connect, poll: pollRest, render: renderAll };

  function now() { return Date.now(); }
  function txt(el) { return (el && el.textContent || '').replace(/\s+/g, ' ').trim(); }
  function rect(el) { try { return el.getBoundingClientRect(); } catch (e) { return { width: 0, height: 0, top: 0, left: 0 }; } }
  function visible(el) { var r = rect(el); return r.width > 18 && r.height > 8; }
  function clamp(n, a, b) { return Math.max(a, Math.min(b, n)); }

  function fmtPrice(n) {
    if (!isFinite(n)) return 'LIVE WAIT';
    if (n >= 10000) return Math.round(n).toLocaleString('en-US');
    if (n >= 1000) return n.toLocaleString('en-US', { maximumFractionDigits: 1 });
    if (n >= 100) return n.toFixed(2);
    if (n >= 10) return n.toFixed(3);
    if (n >= 1) return n.toFixed(4);
    return n.toPrecision(5);
  }
  function fmtDelta(n) {
    if (!isFinite(n)) return 'Δ --';
    return 'Δ ' + (n >= 0 ? '+' : '') + n.toFixed(3) + '%';
  }

  function cleanupOldRuntimeArtifacts() {
    var selectors = [
      '.zel-v37-live-strip', '.zel-v38-live-strip', '.zel-v39-live-strip',
      '.zel-v40-live-strip', '.zel-v41-live-graph', '.zel-v42-live-tick-chart',
      '.zel-v43-live-layer', '.zel-v44-live-layer', '.zel-v45-live-layer',
      '.zel-v46-native-line', '.zel-v47-native-spark-wrap', '.zel-v48-live-plot',
      '.zel-v48-meta-line', '#zel-v41-live-graph', '#zel-v42-live-tick-chart',
      '#zel-v43-live-chart', '#zel-v44-live-chart', '#zel-v45-live-chart',
      '[data-zel-v41]', '[data-zel-v42]', '[data-zel-v43]', '[data-zel-v44]',
      '[data-zel-v45-live-card="child"]', '[data-zel-v48-plot="1"]', '[data-zel-v48-meta-line="1"]'
    ];
    document.querySelectorAll(selectors.join(',')).forEach(function (n) { try { n.remove(); } catch (e) {} });
    document.querySelectorAll('[class*="float"],[id*="float"],[class*="badge"],[id*="badge"]').forEach(function (n) {
      var t = txt(n);
      if (/SOURCE\s+(BOUND|HOLD)|missing:|age_ms|V3[4-9]|V4[0-8]/i.test(t)) {
        try { n.remove(); } catch (e) {}
      }
    });
  }

  function scoreCandidate(el, sym) {
    if (!el || !visible(el)) return -9999;
    if (el.closest('.zel-v49-market-card')) return -9999;
    var t = txt(el);
    if (t.indexOf(sym) < 0) return -9999;
    if (/Operational Console|CURRENT ZEL OPERATING CONCLUSION|Decision proof|Advanced ZEL stack|Advisor|Evidence Summary/i.test(t)) return -9999;
    var r = rect(el);
    if (r.width < 145 || r.height < 105) return -9999;
    if (r.height > Math.max(520, window.innerHeight * 0.80) && r.width > window.innerWidth * 0.55) return -9999;
    var sc = 0;
    if (t.slice(0, 100).indexOf(sym) >= 0) sc += 18;
    if (/sig=read_only|sig-read|read_only/i.test(t)) sc += 10;
    if (/risk-hold|proof=missing|source-required|liq=unbound|receipt_hash/i.test(t)) sc += 10;
    if (/unbound|source-bound|source bound/i.test(t)) sc += 6;
    sc += clamp(22 - Math.floor(t.length / 125), -14, 22);
    sc -= Math.floor(el.querySelectorAll('*').length / 70);
    return sc;
  }

  function findCard(sym) {
    var list = Array.prototype.slice.call(document.querySelectorAll('article,section,main div,div'));
    var best = null;
    var bestScore = -9999;
    list.forEach(function (el) {
      var s = scoreCandidate(el, sym);
      if (s > bestScore) { bestScore = s; best = el; }
    });
    return bestScore > 0 ? best : null;
  }

  function findTruthValueNode(card) {
    var already = card.querySelector('[data-zel-v49-price-node="1"]');
    if (already) return already;
    var top = rect(card).top;
    var nodes = Array.prototype.slice.call(card.querySelectorAll('h1,h2,h3,h4,strong,b,span,div,p')).filter(function (n) {
      if (!visible(n) || n.closest('.zel-v49-native-chart') || n.closest('.zel-v49-live-meta')) return false;
      var t = txt(n);
      if (!/^(unbound|source-bound|source bound|WAIT|LIVE WAIT)$/i.test(t)) return false;
      if (/risk-hold|proof=missing|source-required|liq=unbound|receipt_hash/i.test(t)) return false;
      var nr = rect(n);
      if (nr.top > top + Math.max(115, rect(card).height * 0.38)) return false;
      return true;
    });
    nodes.sort(function (a, b) {
      var as = parseFloat(getComputedStyle(a).fontSize || '0') + (rect(a).top < top + 90 ? 8 : 0);
      var bs = parseFloat(getComputedStyle(b).fontSize || '0') + (rect(b).top < top + 90 ? 8 : 0);
      return bs - as;
    });
    var n = nodes[0] || null;
    if (n) {
      n.setAttribute('data-zel-v49-price-node', '1');
      n.setAttribute('data-zel-v49-original-truth', txt(n));
      n.classList.add('zel-v49-price-node');
    }
    return n;
  }

  function ensureMeta(card, priceNode) {
    var m = card.querySelector('[data-zel-v49-live-meta="1"]');
    if (m) return m;
    m = document.createElement('div');
    m.className = 'zel-v49-live-meta';
    m.setAttribute('data-zel-v49-live-meta', '1');
    m.textContent = 'LIVE FEED initializing · truth source-unbound · RO';
    if (priceNode && priceNode.parentNode) priceNode.insertAdjacentElement('afterend', m);
    else card.insertBefore(m, card.firstChild);
    return m;
  }

  function ensureCanvas(card, meta) {
    var c = card.querySelector('canvas[data-zel-v49-native-chart="1"]');
    if (c) return c;
    c = document.createElement('canvas');
    c.className = 'zel-v49-native-chart';
    c.setAttribute('data-zel-v49-native-chart', '1');
    if (meta && meta.parentNode) meta.insertAdjacentElement('afterend', c);
    else card.insertBefore(c, card.firstChild);
    return c;
  }

  function hideLegacyStaticRails(card) {
    if (!card) return;
    var cr = rect(card);
    Array.prototype.slice.call(card.querySelectorAll('div,span,i')).forEach(function (n) {
      if (n.closest('.zel-v49-live-meta') || n.closest('canvas')) return;
      if (n.children.length > 2) return;
      if (txt(n)) return;
      var r = rect(n);
      if (r.width < Math.max(100, cr.width * 0.35)) return;
      if (r.width > cr.width + 12) return;
      if (r.height < 1 || r.height > 11) return;
      var cs = getComputedStyle(n);
      var paint = [cs.backgroundColor, cs.borderTopColor, cs.borderBottomColor, cs.boxShadow].join(' ');
      if (/rgb\(\s*(0|1[0-9]|2[0-9]|3[0-9]|4[0-9]|5[0-9]|6[0-9])\s*,\s*(160|17[0-9]|18[0-9]|19[0-9]|20[0-9]|21[0-9]|22[0-9]|23[0-9]|24[0-9]|25[0-5])|cyan|0,\s*255|82,\s*242|94,\s*221/i.test(paint)) {
        n.setAttribute('data-zel-v49-hidden-rail', '1');
        n.style.setProperty('display', 'none', 'important');
        n.style.setProperty('height', '0', 'important');
        n.style.setProperty('margin', '0', 'important');
        n.style.setProperty('padding', '0', 'important');
      }
    });
  }

  function mount(sym) {
    var card = findCard(sym);
    if (!card) return null;
    card.classList.add('zel-v49-market-card');
    card.setAttribute('data-zel-v49-symbol', sym);
    var priceNode = findTruthValueNode(card);
    var meta = ensureMeta(card, priceNode);
    ensureCanvas(card, meta);
    hideLegacyStaticRails(card);
    return card;
  }

  function ingest(tick) {
    if (!tick || SYMBOLS.indexOf(tick.symbol) < 0 || !isFinite(tick.price) || tick.price <= 0) return;
    var s = state[tick.symbol];
    var old = s.price;
    s.prev = old;
    s.price = tick.price;
    s.ts = Number(tick.ts || now());
    s.ticks += 1;
    s.source = tick.source || 'exchange';
    s.ok = true;
    if (isFinite(old) && old > 0 && old !== tick.price) s.delta = ((tick.price - old) / old) * 100;
    if (!s.history.length || s.history[s.history.length - 1].p !== tick.price || now() - s.history[s.history.length - 1].local_t > 1400) {
      s.history.push({ p: tick.price, t: s.ts, local_t: now() });
      if (s.history.length > MAX_POINTS) s.history.splice(0, s.history.length - MAX_POINTS);
    }
    window.dispatchEvent(new CustomEvent('zel:market-live', { detail: { version: VERSION, symbol: tick.symbol, price: tick.price, ts: s.ts, source: s.source } }));
  }

  async function seedFromCfBtc() {
    try {
      var r = await fetch('/zel_source_envelope_live.json?v=' + now(), { cache: 'no-store' });
      if (!r.ok) return;
      var j = await r.json();
      var p = j.payload || j;
      var price = Number(p.price || p.mark_price || p.last_price || p.price_usdt);
      var ts = Number(p.source_ts_ms || p.ts_ms || p.updated_ts || now());
      if (isFinite(price) && price > 0) ingest({ symbol: 'BTCUSDT', price: price, ts: ts, source: 'cf-seed' });
    } catch (e) {}
  }

  async function pollRest() {
    await seedFromCfBtc();
    var urls = [
      { source: 'binance-futures-rest', url: 'https://fapi.binance.com/fapi/v1/ticker/price' },
      { source: 'binance-spot-rest', url: 'https://api.binance.com/api/v3/ticker/price' }
    ];
    for (var i = 0; i < urls.length; i++) {
      try {
        var ep = urls[i];
        var r = await fetch(ep.url + '?v=' + now(), { cache: 'no-store', mode: 'cors' });
        if (!r.ok) continue;
        var j = await r.json();
        if (!Array.isArray(j)) continue;
        j.forEach(function (x) {
          var sym = x && x.symbol;
          if (SYMBOLS.indexOf(sym) >= 0) ingest({ symbol: sym, price: Number(x.price), ts: Number(x.time || now()), source: ep.source });
        });
        return true;
      } catch (e) {}
    }
    return false;
  }

  var endpoints = [
    {
      name: 'binance-futures-mark',
      url: function () { return 'wss://fstream.binance.com/stream?streams=' + SYMBOLS.map(function (s) { return s.toLowerCase() + '@markPrice@1s'; }).join('/'); },
      parse: function (d) { d = d && d.data ? d.data : d; return d && d.s ? { symbol: d.s, price: Number(d.p || d.markPrice), ts: Number(d.E || d.T || now()), source: 'binance-futures-ws' } : null; }
    },
    {
      name: 'binance-spot-ticker',
      url: function () { return 'wss://stream.binance.com:9443/stream?streams=' + SYMBOLS.map(function (s) { return s.toLowerCase() + '@ticker'; }).join('/'); },
      parse: function (d) { d = d && d.data ? d.data : d; return d && d.s ? { symbol: d.s, price: Number(d.c || d.w), ts: Number(d.E || now()), source: 'binance-spot-ws' } : null; }
    }
  ];

  function connect() {
    clearTimeout(reconnectTimer);
    try { if (ws) ws.close(); } catch (e) {}
    var ep = endpoints[endpointIndex % endpoints.length];
    endpointIndex += 1;
    try { ws = new WebSocket(ep.url()); } catch (e) { scheduleReconnect(); return; }
    ws.onopen = function () { reconnectDelay = 1200; };
    ws.onmessage = function (ev) { try { ingest(ep.parse(JSON.parse(ev.data))); } catch (e) {} };
    ws.onerror = function () {};
    ws.onclose = function () { scheduleReconnect(); };
  }
  function scheduleReconnect() {
    clearTimeout(reconnectTimer);
    reconnectTimer = setTimeout(connect, reconnectDelay);
    reconnectDelay = Math.min(16000, Math.floor(reconnectDelay * 1.55));
  }

  function drawChart(canvas, sym) {
    var s = state[sym];
    var dpr = Math.max(1, Math.min(2, window.devicePixelRatio || 1));
    var box = rect(canvas);
    var w = Math.max(160, Math.floor(box.width || 220));
    var h = Math.max(54, Math.floor(box.height || 72));
    if (canvas.width !== Math.floor(w * dpr) || canvas.height !== Math.floor(h * dpr)) {
      canvas.width = Math.floor(w * dpr);
      canvas.height = Math.floor(h * dpr);
      canvas.style.width = w + 'px';
      canvas.style.height = h + 'px';
    }
    var ctx = canvas.getContext('2d');
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    ctx.clearRect(0, 0, w, h);

    var grid = 'rgba(94,221,255,0.13)';
    var line = 'rgba(82,242,255,0.95)';
    var fill = 'rgba(0,255,196,0.13)';
    var muted = 'rgba(166,209,255,0.25)';
    for (var gy = 0; gy < 4; gy++) {
      var y = 6 + gy * (h - 13) / 3;
      ctx.strokeStyle = grid;
      ctx.lineWidth = 1;
      ctx.beginPath(); ctx.moveTo(0, y); ctx.lineTo(w, y); ctx.stroke();
    }

    var hist = s.history.slice(-MAX_POINTS);
    if (!hist.length) {
      ctx.fillStyle = muted;
      ctx.font = '11px ui-monospace, Menlo, Consolas, monospace';
      ctx.fillText('waiting exchange feed', 9, Math.floor(h / 2));
      return;
    }
    if (hist.length === 1) hist = [hist[0], hist[0]];
    var vals = hist.map(function (x) { return x.p; }).filter(isFinite);
    var min = Math.min.apply(null, vals);
    var max = Math.max.apply(null, vals);
    var pad = (max - min) * 0.18;
    if (!isFinite(pad) || pad <= 0) pad = Math.max(Math.abs(max) * 0.00015, 0.0001);
    min -= pad; max += pad;
    function xAt(i) { return hist.length <= 1 ? w - 3 : i * (w - 4) / (hist.length - 1); }
    function yAt(p) { return h - 7 - ((p - min) / (max - min)) * (h - 16); }

    ctx.beginPath();
    hist.forEach(function (pt, i) { var x = xAt(i), y = yAt(pt.p); if (i === 0) ctx.moveTo(x, y); else ctx.lineTo(x, y); });
    var lastX = xAt(hist.length - 1);
    var lastY = yAt(hist[hist.length - 1].p);
    ctx.lineTo(lastX, h - 5); ctx.lineTo(0, h - 5); ctx.closePath();
    ctx.fillStyle = fill; ctx.fill();

    ctx.beginPath();
    hist.forEach(function (pt, i) { var x = xAt(i), y = yAt(pt.p); if (i === 0) ctx.moveTo(x, y); else ctx.lineTo(x, y); });
    ctx.strokeStyle = line; ctx.lineWidth = 2; ctx.stroke();
    ctx.fillStyle = line; ctx.beginPath(); ctx.arc(lastX, lastY, 3, 0, Math.PI * 2); ctx.fill();
  }

  function renderCard(sym) {
    var card = mount(sym);
    if (!card) return;
    var s = state[sym];
    var age = s.ts ? now() - s.ts : null;
    var live = !!(s.price && age !== null && age < STALE_MS);
    var priceNode = findTruthValueNode(card);
    var meta = ensureMeta(card, priceNode);
    var canvas = ensureCanvas(card, meta);
    hideLegacyStaticRails(card);

    if (priceNode) {
      priceNode.textContent = s.price ? fmtPrice(s.price) : 'LIVE WAIT';
      priceNode.classList.toggle('zel-v49-live-ok', live);
      priceNode.classList.toggle('zel-v49-live-wait', !live);
    }
    if (meta) {
      meta.textContent = (live ? 'LIVE ' : 'WAIT ') + (s.source || 'exchange') + ' · ' + fmtDelta(s.delta) + ' · ticks ' + (s.ticks || 0) + (age === null ? '' : ' · age ' + Math.max(0, age) + 'ms') + ' · truth source-unbound · RO';
      meta.classList.toggle('zel-v49-live-ok', live);
      meta.classList.toggle('zel-v49-live-wait', !live);
    }
    card.setAttribute('data-zel-v49-live', live ? '1' : '0');
    card.setAttribute('data-zel-v49-price', s.price || '');
    drawChart(canvas, sym);
  }

  function renderAll() {
    cleanupOldRuntimeArtifacts();
    SYMBOLS.forEach(renderCard);
  }

  function boot() {
    cleanupOldRuntimeArtifacts();
    renderAll();
    pollRest();
    connect();
    timers.push(setInterval(renderAll, RENDER_MS));
    timers.push(setInterval(function () { cleanupOldRuntimeArtifacts(); SYMBOLS.forEach(mount); }, SCAN_MS));
    timers.push(setInterval(pollRest, REST_MS));
    window.addEventListener('resize', renderAll);
  }

  function stop() {
    timers.forEach(function (t) { clearInterval(t); });
    timers = [];
    clearTimeout(reconnectTimer);
    try { if (ws) ws.close(); } catch (e) {}
    window.removeEventListener('resize', renderAll);
  }

  try {
    ['ZEL_APP_V41_LIVE', 'ZEL_APP_V42_LIVE', 'ZEL_APP_V43_LIVE', 'ZEL_APP_V44_LIVE', 'ZEL_APP_V45_LIVE', 'ZEL_APP_V46_LIVE', 'ZEL_APP_V47_LIVE', 'ZEL_APP_V48_LIVE'].forEach(function (k) {
      try { if (window[k] && typeof window[k].stop === 'function') window[k].stop(); } catch (e) {}
    });
  } catch (e) {}

  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', boot, { once: true });
  else boot();
})();
