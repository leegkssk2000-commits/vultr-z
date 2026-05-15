/* ZEL APP V48 NATIVE CARD LIVE FEED CLEAN
 * App-only browser runtime. No nginx/caddy/systemd/server-route mutation.
 * Purpose: market-card native live feed: exchange tick -> card price + in-card sparkline.
 * Truth/proof/source-bound state remains separate; this layer does not authorize orders.
 */
(function () {
  'use strict';
  var VERSION = 'V48_NATIVE_CARD_LIVE_FEED_CLEAN';
  if (window.ZEL_APP_V48_LIVE && window.ZEL_APP_V48_LIVE.version === VERSION) return;

  var SYMBOLS = ['BTCUSDT', 'ETHUSDT', 'SOLUSDT', 'XRPUSDT', 'LINKUSDT'];
  var MAX_POINTS = 90;
  var CARD_SCAN_MS = 1500;
  var RENDER_MS = 650;
  var REST_MS = 4000;
  var STALE_MS = 15000;

  var state = {};
  SYMBOLS.forEach(function (sym) {
    state[sym] = {
      symbol: sym, price: null, prev: null, delta: null, ts: 0, age_ms: null,
      ticks: 0, source: 'boot', ok: false, history: []
    };
  });

  var timers = [];
  var ws = null;
  var wsMode = 0;
  var reconnectDelay = 1200;
  var reconnectTimer = null;

  var WS_ENDPOINTS = [
    {
      name: 'binance-futures-mark',
      url: function () {
        return 'wss://fstream.binance.com/stream?streams=' + SYMBOLS.map(function (s) {
          return s.toLowerCase() + '@markPrice@1s';
        }).join('/');
      },
      parse: function (raw) {
        var d = raw && raw.data ? raw.data : raw;
        var sym = d && d.s;
        var p = d && (d.p || d.markPrice);
        var ts = d && (d.E || d.T || Date.now());
        return sym && p ? { symbol: sym, price: Number(p), ts: Number(ts), source: 'binance-futures-mark' } : null;
      }
    },
    {
      name: 'binance-spot-ticker',
      url: function () {
        return 'wss://stream.binance.com:9443/stream?streams=' + SYMBOLS.map(function (s) {
          return s.toLowerCase() + '@ticker';
        }).join('/');
      },
      parse: function (raw) {
        var d = raw && raw.data ? raw.data : raw;
        var sym = d && d.s;
        var p = d && (d.c || d.w);
        var ts = d && (d.E || Date.now());
        return sym && p ? { symbol: sym, price: Number(p), ts: Number(ts), source: 'binance-spot-ticker' } : null;
      }
    }
  ];

  var REST_ENDPOINTS = [
    {
      name: 'binance-futures-premiumIndex',
      url: 'https://fapi.binance.com/fapi/v1/premiumIndex',
      parse: function (j) {
        if (!Array.isArray(j)) return [];
        return j.map(function (x) {
          return { symbol: x.symbol, price: Number(x.markPrice), ts: Number(x.time || Date.now()), source: 'binance-futures-rest' };
        });
      }
    },
    {
      name: 'binance-futures-ticker',
      url: 'https://fapi.binance.com/fapi/v1/ticker/price',
      parse: function (j) {
        if (!Array.isArray(j)) return [];
        return j.map(function (x) {
          return { symbol: x.symbol, price: Number(x.price), ts: Number(x.time || Date.now()), source: 'binance-futures-rest' };
        });
      }
    }
  ];

  window.ZEL_APP_V48_LIVE = {
    version: VERSION,
    state: state,
    symbols: SYMBOLS.slice(),
    stop: stop,
    connect: connect,
    poll: restPoll,
    render: renderAll
  };

  function now() { return Date.now(); }
  function txt(el) { return (el && el.textContent || '').replace(/\s+/g, ' ').trim(); }
  function rect(el) { try { return el.getBoundingClientRect(); } catch (e) { return { width: 0, height: 0, top: 0, left: 0 }; } }
  function visible(el) { var r = rect(el); return !!(r.width > 20 && r.height > 10); }
  function clamp(n, a, b) { return Math.max(a, Math.min(b, n)); }

  function fmtPrice(n) {
    if (!isFinite(n)) return 'WAIT';
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

  function cleanupOldPatchUI() {
    var selectors = [
      '.zel-v41-live-graph', '.zel-v41-graph', '.zel-v42-live-tick-chart', '.zel-v42-tick-chart',
      '.zel-v43-live-layer', '.zel-v43-card-live-pill', '.zel-v44-live-layer', '.zel-v44-card-live-pill',
      '.zel-v45-live-layer', '.zel-v45-live-canvas-wrap', '.zel-v45-live-meta', '.zel-v45-live-head',
      '.zel-v46-native-line', '.zel-v47-native-spark-wrap', '.zel-v47-native-spark',
      '[data-zel-v41]', '[data-zel-v42]', '[data-zel-v43]', '[data-zel-v44]', '[data-zel-v45-live-card="child"]',
      '#zel-v41-live-graph', '#zel-v42-live-tick-chart', '#zel-v43-live-chart', '#zel-v44-live-chart', '#zel-v45-live-chart'
    ];
    document.querySelectorAll(selectors.join(',')).forEach(function (n) { try { n.remove(); } catch (e) {} });
    document.querySelectorAll('[class*="float"],[class*="badge"],[id*="float"],[id*="badge"]').forEach(function (n) {
      var t = txt(n);
      if (/SOURCE\s+(BOUND|HOLD)|missing:|age_ms|V3[4-9]|V4[0-7]/i.test(t)) {
        try { n.remove(); } catch (e) {}
      }
    });
  }

  function scoreCard(el, sym) {
    if (!el || !visible(el)) return -9999;
    if (el.closest('.zel-v48-live-card')) return -9999;
    var t = txt(el);
    if (t.indexOf(sym) < 0) return -9999;
    if (/Operational Console|CURRENT ZEL OPERATING CONCLUSION|Decision proof|Advanced ZEL stack|Advisor|Evidence Summary/i.test(t)) return -9999;
    var r = rect(el);
    if (r.width < 145 || r.height < 90) return -9999;
    if (r.height > window.innerHeight * 0.92 && r.width > window.innerWidth * 0.65) return -9999;
    var sc = 0;
    if (t.slice(0, 100).indexOf(sym) >= 0) sc += 10;
    if (/sig=read_only|sig-read|read_only/i.test(t)) sc += 8;
    if (/risk-hold|proof=missing|source-required|liq=unbound|receipt_hash/i.test(t)) sc += 8;
    if (/unbound|source-bound/i.test(t)) sc += 5;
    sc += clamp(18 - Math.floor(t.length / 120), -18, 18);
    sc -= Math.floor(el.querySelectorAll('*').length / 55);
    return sc;
  }

  function findCard(sym) {
    var nodes = Array.prototype.slice.call(document.querySelectorAll('article,section,main div,div'));
    var best = null, bestScore = -9999;
    nodes.forEach(function (el) {
      var s = scoreCard(el, sym);
      if (s > bestScore) { bestScore = s; best = el; }
    });
    return bestScore > 0 ? best : null;
  }

  function findPrimaryValueNode(card) {
    var old = card.querySelector('[data-zel-v48-price-node="1"]');
    if (old) return old;
    var top = rect(card).top;
    var arr = Array.prototype.slice.call(card.querySelectorAll('h1,h2,h3,h4,strong,b,span,div,p')).filter(function (n) {
      if (!visible(n) || n.closest('.zel-v48-live-plot') || n.closest('.zel-v48-meta-line')) return false;
      var t = txt(n);
      if (!/^(unbound|source-bound|source bound|DATA HOLD|SOURCE HOLD|SOURCE BOUND|WAIT)$/i.test(t)) return false;
      if (/risk-hold|proof=missing|source-required|liq=unbound|receipt_hash/i.test(t)) return false;
      if (rect(n).top > top + Math.max(105, rect(card).height * 0.35)) return false;
      return true;
    });
    arr.sort(function (a, b) {
      var fa = parseFloat(getComputedStyle(a).fontSize || '0') + (rect(a).top < top + 80 ? 8 : 0);
      var fb = parseFloat(getComputedStyle(b).fontSize || '0') + (rect(b).top < top + 80 ? 8 : 0);
      return fb - fa;
    });
    var n = arr[0];
    if (n) {
      n.setAttribute('data-zel-v48-price-node', '1');
      n.setAttribute('data-zel-v48-original-truth', txt(n));
      n.classList.add('zel-v48-price-node');
    }
    return n || null;
  }

  function ensureMetaLine(card, priceNode) {
    var line = card.querySelector('[data-zel-v48-meta-line="1"]');
    if (line) return line;
    line = document.createElement('div');
    line.className = 'zel-v48-meta-line';
    line.setAttribute('data-zel-v48-meta-line', '1');
    line.textContent = 'LIVE FEED waiting · truth source-unbound · RO';
    if (priceNode && priceNode.parentNode) priceNode.insertAdjacentElement('afterend', line);
    else card.insertBefore(line, card.firstChild);
    return line;
  }

  function ensurePlot(card, metaLine) {
    var plot = card.querySelector('[data-zel-v48-plot="1"]');
    if (plot) return plot;
    plot = document.createElement('div');
    plot.className = 'zel-v48-live-plot';
    plot.setAttribute('data-zel-v48-plot', '1');
    var canvas = document.createElement('canvas');
    canvas.className = 'zel-v48-live-canvas';
    plot.appendChild(canvas);
    if (metaLine && metaLine.parentNode) metaLine.insertAdjacentElement('afterend', plot);
    else card.insertBefore(plot, card.firstChild);
    return plot;
  }

  function hideOldHorizontalRails(card) {
    if (!card || card.getAttribute('data-zel-v48-rails-clean') === '1') return;
    var cr = rect(card);
    Array.prototype.slice.call(card.querySelectorAll('div,span,i')).forEach(function (n) {
      if (n.closest('.zel-v48-live-plot') || n.closest('.zel-v48-meta-line')) return;
      if (n.children.length > 2) return;
      if (txt(n)) return;
      var r = rect(n);
      if (r.width < Math.min(110, cr.width * 0.45) || r.width > cr.width + 8) return;
      if (r.height < 1 || r.height > 10) return;
      var cs = getComputedStyle(n);
      var bg = (cs.backgroundColor || '') + ' ' + (cs.borderTopColor || '') + ' ' + (cs.boxShadow || '');
      if (/rgb\(.*(0|6|7|8|9|1[0-9]|2[0-9]).*,.*(180|190|200|210|220|230|240|250|255)|cyan|0, 255|79, 220|96, 239/i.test(bg) || r.width > cr.width * 0.58) {
        n.setAttribute('data-zel-v48-hidden-rail', '1');
        n.style.setProperty('display', 'none', 'important');
        n.style.setProperty('visibility', 'hidden', 'important');
        n.style.setProperty('height', '0', 'important');
        n.style.setProperty('margin', '0', 'important');
        n.style.setProperty('padding', '0', 'important');
      }
    });
    card.setAttribute('data-zel-v48-rails-clean', '1');
  }

  function mountCard(sym) {
    var card = findCard(sym);
    if (!card) return null;
    card.classList.add('zel-v48-live-card');
    card.setAttribute('data-zel-v48-symbol', sym);
    var priceNode = findPrimaryValueNode(card);
    var metaLine = ensureMetaLine(card, priceNode);
    ensurePlot(card, metaLine);
    hideOldHorizontalRails(card);
    return card;
  }

  function ingest(tick) {
    if (!tick || SYMBOLS.indexOf(tick.symbol) < 0 || !isFinite(tick.price) || tick.price <= 0) return;
    var s = state[tick.symbol];
    var old = s.price;
    s.prev = old;
    s.price = tick.price;
    s.ts = Number(tick.ts || now());
    s.age_ms = Math.max(0, now() - s.ts);
    s.ticks += 1;
    s.source = tick.source || s.source || 'feed';
    s.ok = true;
    if (isFinite(old) && old > 0) s.delta = ((tick.price - old) / old) * 100;
    s.history.push({ p: tick.price, t: s.ts });
    if (s.history.length > MAX_POINTS) s.history.splice(0, s.history.length - MAX_POINTS);
    window.dispatchEvent(new CustomEvent('zel:exchange-live-tick', { detail: { version: VERSION, symbol: tick.symbol, state: Object.assign({}, s, { history: s.history.slice(-10) }) } }));
  }

  async function seedCfBtc() {
    try {
      var r = await fetch('/zel_source_envelope_live.json?v=' + now(), { cache: 'no-store' });
      if (!r.ok) return false;
      var j = await r.json();
      var p = j.payload || j;
      var sym = p.symbol || 'BTCUSDT';
      var price = Number(p.price || p.mark_price || p.last_price || p.price_usdt);
      var ts = Number(p.source_ts_ms || p.ts_ms || p.updated_ts || now());
      if (sym === 'BTCUSDT' && isFinite(price)) ingest({ symbol: sym, price: price, ts: ts, source: 'cf-seed' });
      return true;
    } catch (e) { return false; }
  }

  async function restPoll() {
    await seedCfBtc();
    for (var i = 0; i < REST_ENDPOINTS.length; i++) {
      try {
        var ep = REST_ENDPOINTS[i];
        var r = await fetch(ep.url + '?v=' + now(), { cache: 'no-store', mode: 'cors' });
        if (!r.ok) continue;
        ep.parse(await r.json()).forEach(function (x) {
          if (SYMBOLS.indexOf(x.symbol) >= 0 && isFinite(x.price)) ingest(x);
        });
        return true;
      } catch (e) {}
    }
    return false;
  }

  function connect() {
    try { if (ws) ws.close(); } catch (e) {}
    clearTimeout(reconnectTimer);
    var ep = WS_ENDPOINTS[wsMode % WS_ENDPOINTS.length];
    wsMode += 1;
    try { ws = new WebSocket(ep.url()); } catch (e) { scheduleReconnect(); return; }
    ws.onopen = function () { reconnectDelay = 1200; };
    ws.onmessage = function (ev) {
      try { ingest(ep.parse(JSON.parse(ev.data))); } catch (e) {}
    };
    ws.onerror = function () {};
    ws.onclose = function () { scheduleReconnect(); };
  }
  function scheduleReconnect() {
    clearTimeout(reconnectTimer);
    reconnectTimer = setTimeout(connect, reconnectDelay);
    reconnectDelay = Math.min(16000, Math.floor(reconnectDelay * 1.6));
  }

  function drawPlot(card, sym) {
    var plot = card.querySelector('[data-zel-v48-plot="1"]');
    if (!plot) return;
    var canvas = plot.querySelector('canvas');
    if (!canvas) return;
    var s = state[sym];
    var dpr = Math.max(1, Math.min(2, window.devicePixelRatio || 1));
    var box = rect(plot);
    var w = Math.max(160, Math.floor(box.width));
    var h = Math.max(42, Math.floor(box.height));
    if (canvas.width !== Math.floor(w * dpr) || canvas.height !== Math.floor(h * dpr)) {
      canvas.width = Math.floor(w * dpr);
      canvas.height = Math.floor(h * dpr);
      canvas.style.width = w + 'px';
      canvas.style.height = h + 'px';
    }
    var ctx = canvas.getContext('2d');
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    ctx.clearRect(0, 0, w, h);

    var grid = 'rgba(94, 221, 255, 0.16)';
    var line = 'rgba(82, 242, 255, 0.96)';
    var fill = 'rgba(0, 255, 196, 0.16)';
    var dim = 'rgba(166, 209, 255, 0.30)';
    for (var gy = 0; gy < 4; gy++) {
      var y = 7 + gy * (h - 15) / 3;
      ctx.strokeStyle = grid;
      ctx.lineWidth = 1;
      ctx.beginPath();
      ctx.moveTo(0, y);
      ctx.lineTo(w, y);
      ctx.stroke();
    }

    var hist = s.history.slice(-MAX_POINTS);
    if (!hist.length) {
      ctx.fillStyle = dim;
      ctx.font = '11px ui-monospace, Menlo, Consolas, monospace';
      ctx.fillText('waiting live feed', 12, Math.floor(h / 2));
      return;
    }
    if (hist.length === 1) hist = [hist[0], hist[0]];
    var prices = hist.map(function (x) { return x.p; }).filter(isFinite);
    var min = Math.min.apply(null, prices), max = Math.max.apply(null, prices);
    var pad = (max - min) * 0.18;
    if (!isFinite(pad) || pad === 0) { pad = Math.max(Math.abs(max) * 0.0002, 0.0001); }
    min -= pad; max += pad;
    function xAt(i) { return hist.length === 1 ? w - 2 : i * (w - 3) / (hist.length - 1); }
    function yAt(p) { return h - 8 - ((p - min) / (max - min)) * (h - 18); }

    ctx.beginPath();
    hist.forEach(function (pt, i) {
      var x = xAt(i), y = yAt(pt.p);
      if (i === 0) ctx.moveTo(x, y); else ctx.lineTo(x, y);
    });
    var lastX = xAt(hist.length - 1), lastY = yAt(hist[hist.length - 1].p);
    ctx.lineTo(lastX, h - 6);
    ctx.lineTo(0, h - 6);
    ctx.closePath();
    ctx.fillStyle = fill;
    ctx.fill();

    ctx.beginPath();
    hist.forEach(function (pt, i) {
      var x = xAt(i), y = yAt(pt.p);
      if (i === 0) ctx.moveTo(x, y); else ctx.lineTo(x, y);
    });
    ctx.strokeStyle = line;
    ctx.lineWidth = 2;
    ctx.stroke();

    ctx.fillStyle = line;
    ctx.beginPath();
    ctx.arc(lastX, lastY, 3, 0, Math.PI * 2);
    ctx.fill();
  }

  function renderCard(sym) {
    var card = mountCard(sym);
    if (!card) return;
    var s = state[sym];
    var age = s.ts ? Math.max(0, now() - s.ts) : null;
    s.age_ms = age;
    var live = !!(s.price && age !== null && age < STALE_MS);
    var priceNode = findPrimaryValueNode(card);
    var metaLine = ensureMetaLine(card, priceNode);
    if (priceNode) {
      priceNode.textContent = live ? fmtPrice(s.price) : (s.price ? fmtPrice(s.price) : 'WAIT');
      priceNode.classList.toggle('zel-v48-live-ok', live);
      priceNode.classList.toggle('zel-v48-live-wait', !live);
    }
    if (metaLine) {
      metaLine.textContent = (live ? 'LIVE ' : 'WAIT ') + (s.source || 'feed') + ' · ' + fmtDelta(s.delta) + ' · ticks ' + (s.ticks || 0) + (age !== null ? ' · age ' + age + 'ms' : '') + ' · truth source-unbound · RO';
      metaLine.classList.toggle('zel-v48-live-ok', live);
      metaLine.classList.toggle('zel-v48-live-wait', !live);
    }
    card.setAttribute('data-zel-v48-live', live ? '1' : '0');
    card.setAttribute('data-zel-v48-price', s.price || '');
    card.setAttribute('data-zel-v48-age-ms', age === null ? '' : String(age));
    card.setAttribute('data-zel-v48-ticks', String(s.ticks || 0));
    drawPlot(card, sym);
  }

  function renderAll() {
    cleanupOldPatchUI();
    SYMBOLS.forEach(renderCard);
  }

  function boot() {
    cleanupOldPatchUI();
    renderAll();
    restPoll();
    connect();
    timers.push(setInterval(renderAll, RENDER_MS));
    timers.push(setInterval(function () { cleanupOldPatchUI(); SYMBOLS.forEach(mountCard); }, CARD_SCAN_MS));
    timers.push(setInterval(restPoll, REST_MS));
    window.addEventListener('resize', renderAll);
  }

  function stop() {
    timers.forEach(clearInterval); timers = [];
    clearTimeout(reconnectTimer);
    try { if (ws) ws.close(); } catch (e) {}
    window.removeEventListener('resize', renderAll);
  }

  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', boot, { once: true });
  else boot();
})();
