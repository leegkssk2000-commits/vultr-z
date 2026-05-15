/* ZEL APP V54 - V47 minimal live feed fix
 * App-only. No nginx/caddy/systemd mutation.
 * Keeps native V47 card shape. Removes legacy static strip. Replaces unbound/source-bound title with exchange live mark price after real tick.
 */
(function () {
  'use strict';

  var VER = 'V54_MIN_V47_LIVE';
  var SYMBOLS = ['BTCUSDT', 'ETHUSDT', 'SOLUSDT', 'XRPUSDT', 'LINKUSDT'];
  var MAX_POINTS = 64;
  var STALE_MS = 12000;
  var MOUNT_MS = 900;
  var REDRAW_MS = 500;
  var REST_MS = 3000;

  var state = {};
  var ws = null;
  var wsRetry = 0;
  var mountedOnce = false;

  SYMBOLS.forEach(function (s) {
    state[s] = { symbol: s, price: null, prev: null, first: null, ts: 0, ticks: 0, source: 'waiting', hist: [] };
  });

  function now() { return Date.now(); }
  function finite(n) { return typeof n === 'number' && isFinite(n); }
  function num(v) { var n = Number(v); return finite(n) ? n : null; }
  function txt(el) { return (el && el.textContent || '').replace(/\s+/g, ' ').trim(); }
  function css(el) { try { return getComputedStyle(el); } catch (e) { return null; } }
  function rect(el) { try { return el.getBoundingClientRect(); } catch (e) { return { width: 0, height: 0, top: 0, left: 0, bottom: 0, right: 0 }; } }
  function visible(el) {
    if (!el || !el.isConnected) return false;
    var r = rect(el); if (r.width < 2 || r.height < 2) return false;
    var c = css(el); return !c || (c.display !== 'none' && c.visibility !== 'hidden' && Number(c.opacity || 1) !== 0);
  }

  function fmtPrice(sym, p) {
    if (!finite(p)) return '';
    var d = 4;
    if (sym === 'BTCUSDT') d = 1;
    else if (sym === 'ETHUSDT') d = 2;
    else if (sym === 'SOLUSDT' || sym === 'LINKUSDT') d = 4;
    else if (sym === 'XRPUSDT') d = 4;
    return p.toLocaleString('en-US', { minimumFractionDigits: d, maximumFractionDigits: d });
  }
  function fmtDelta(s) {
    if (!s || !finite(s.price) || !finite(s.prev) || s.prev <= 0) return '0.000%';
    var pct = ((s.price - s.prev) / s.prev) * 100;
    var sign = pct > 0 ? '+' : '';
    return sign + pct.toFixed(3) + '%';
  }

  function ingest(sym, price, source, eventTs) {
    if (SYMBOLS.indexOf(sym) < 0) return;
    price = num(price);
    if (!finite(price) || price <= 0) return;
    var s = state[sym];
    if (!finite(s.first)) s.first = price;
    if (finite(s.price)) s.prev = s.price;
    else s.prev = price;
    s.price = price;
    s.ts = finite(eventTs) && eventTs > 1000000000000 ? eventTs : now();
    s.source = source || 'exchange';
    s.ticks += 1;
    s.hist.push({ t: s.ts, p: price });
    if (s.hist.length > MAX_POINTS) s.hist.splice(0, s.hist.length - MAX_POINTS);
    updateSymbol(sym);
  }

  function startWs() {
    var streams = SYMBOLS.map(function (s) { return s.toLowerCase() + '@markPrice@1s'; }).join('/');
    var url = 'wss://fstream.binance.com/stream?streams=' + streams;
    try {
      if (ws && (ws.readyState === 0 || ws.readyState === 1)) return;
      ws = new WebSocket(url);
      ws.onopen = function () { wsRetry = 0; };
      ws.onmessage = function (ev) {
        try {
          var m = JSON.parse(ev.data);
          var d = m && (m.data || m);
          var sym = d && d.s;
          var price = d && (d.p || d.markPrice || d.c || d.lastPrice);
          var ets = num(d && (d.E || d.eventTime));
          ingest(sym, price, 'binance-futures-mark-ws', ets);
        } catch (e) {}
      };
      ws.onerror = function () { try { ws.close(); } catch (e) {} };
      ws.onclose = function () {
        wsRetry += 1;
        setTimeout(startWs, Math.min(15000, 1000 + wsRetry * 1500));
      };
    } catch (e) {
      setTimeout(startWs, 5000);
    }
  }

  function restFallback() {
    var url = 'https://fapi.binance.com/fapi/v1/premiumIndex?_=' + now();
    try {
      fetch(url, { cache: 'no-store', mode: 'cors', credentials: 'omit' })
        .then(function (r) { return r.ok ? r.json() : null; })
        .then(function (arr) {
          if (!Array.isArray(arr)) arr = arr ? [arr] : [];
          var map = {};
          arr.forEach(function (d) { if (d && d.symbol) map[d.symbol] = d; });
          SYMBOLS.forEach(function (sym) {
            var d = map[sym];
            if (!d) return;
            var s = state[sym];
            if (s.ts && now() - s.ts < 2500) return;
            ingest(sym, d.markPrice || d.indexPrice || d.lastFundingRate, 'binance-futures-mark-rest', num(d.time));
          });
        }).catch(function () {});
    } catch (e) {}
  }

  function cleanOldArtifacts(card) {
    if (!card) return;
    var kill = [
      '.zel-v36-live-panel','.zel-v37-live-panel','.zel-v38-live-panel','.zel-v39-live-panel','.zel-v40-live-panel',
      '.zel-v41-live-graph','.zel-v41-graph','.zel-v42-live-tick-chart','.zel-v42-tick-chart',
      '.zel-v43-live-layer','.zel-v44-live-layer','.zel-v45-live-layer','.zel-v45-live-canvas-wrap',
      '[data-zel-live-core]','.zel-v53-live-core','.zel-v52-live-core','.zel-v51-live-core',
      '.zel-v45-live-meta','.zel-v45-live-head','.zel-v46-live-layer','.zel-v46-feed-chip',
      '#zel-v41-live-graph','#zel-v42-live-tick-chart','#zel-v43-live-chart','#zel-v44-live-chart','#zel-v45-live-chart'
    ];
    kill.forEach(function (q) {
      Array.prototype.slice.call(card.querySelectorAll(q)).forEach(function (el) {
        if (!el.closest('.zel-v54-spark-wrap')) el.remove();
      });
    });
  }

  function looksLikeCard(el, sym) {
    if (!visible(el)) return false;
    var t = txt(el);
    if (t.indexOf(sym) < 0) return false;
    if (!/(unbound|source-bound|sig=read_only|risk=hold|proof=missing|receipt_hash)/i.test(t)) return false;
    var r = rect(el);
    if (r.width < 150 || r.height < 110) return false;
    if (r.width > 900 || r.height > 900) return false;
    return true;
  }

  function findCard(sym) {
    var all = Array.prototype.slice.call(document.querySelectorAll('article,section,main div,body div'));
    var cands = [];
    all.forEach(function (el) {
      if (el.closest('.zel-v54-spark-wrap')) return;
      if (looksLikeCard(el, sym)) {
        var r = rect(el);
        cands.push({ el: el, area: r.width * r.height, h: r.height, w: r.width });
      }
    });
    cands.sort(function (a, b) { return a.area - b.area; });
    return cands.length ? cands[0].el : null;
  }

  function titleCandidate(card, sym) {
    var cr = rect(card);
    var nodes = Array.prototype.slice.call(card.querySelectorAll('h1,h2,h3,h4,p,div,span,strong,b'));
    var cand = [];
    nodes.forEach(function (el) {
      if (!visible(el) || el.closest('.zel-v54-spark-wrap')) return;
      var t = txt(el);
      if (!t || t === sym || t.length > 40) return;
      var r = rect(el);
      if (r.top < cr.top || r.top > cr.top + Math.min(115, cr.height * 0.45)) return;
      if (r.left < cr.left - 4 || r.left > cr.right - 30) return;
      var c = css(el); var fs = c ? parseFloat(c.fontSize || '0') : 0;
      if (/^(unbound|source-bound|WAIT)$/i.test(t) || /^[0-9][0-9,]*(\.[0-9]+)?$/.test(t)) {
        cand.push({ el: el, score: fs * 10 - (r.top - cr.top) });
      }
    });
    cand.sort(function (a, b) { return b.score - a.score; });
    return cand.length ? cand[0].el : null;
  }

  function symbolLabel(card, sym) {
    var nodes = Array.prototype.slice.call(card.querySelectorAll('div,span,p,b,strong,small'));
    var cr = rect(card);
    var best = null;
    nodes.forEach(function (el) {
      if (!visible(el) || el.closest('.zel-v54-spark-wrap')) return;
      if (txt(el) !== sym) return;
      var r = rect(el);
      if (r.top < cr.top || r.top > cr.top + 75) return;
      if (!best || r.top < rect(best).top) best = el;
    });
    return best;
  }

  function ensureTitle(card, sym) {
    var title = card.querySelector('[data-zel-v54-price-title="' + sym + '"]') || titleCandidate(card, sym);
    if (!title) {
      var label = symbolLabel(card, sym);
      title = document.createElement('div');
      title.className = 'zel-v54-price-title';
      title.setAttribute('data-zel-v54-price-title', sym);
      title.textContent = 'unbound';
      if (label && label.parentNode) label.parentNode.insertBefore(title, label.nextSibling);
      else card.insertBefore(title, card.firstChild);
    }
    title.setAttribute('data-zel-v54-price-title', sym);
    title.classList.add('zel-v54-price-title');
    return title;
  }

  function ensureStatus(card, sym, title) {
    var st = card.querySelector('[data-zel-v54-feed-status="' + sym + '"]');
    if (!st) {
      st = document.createElement('div');
      st.className = 'zel-v54-feed-status';
      st.setAttribute('data-zel-v54-feed-status', sym);
      if (title && title.parentNode) title.parentNode.insertBefore(st, title.nextSibling);
      else card.insertBefore(st, card.firstChild);
    }
    return st;
  }

  function ensureSpark(card, sym, title, status) {
    var wrap = card.querySelector('.zel-v54-spark-wrap[data-symbol="' + sym + '"]');
    if (!wrap) {
      wrap = document.createElement('div');
      wrap.className = 'zel-v54-spark-wrap';
      wrap.setAttribute('data-symbol', sym);
      var canvas = document.createElement('canvas');
      canvas.className = 'zel-v54-spark-canvas';
      wrap.appendChild(canvas);
      var after = status || title || symbolLabel(card, sym);
      if (after && after.parentNode) after.parentNode.insertBefore(wrap, after.nextSibling);
      else card.insertBefore(wrap, card.firstChild);
    }
    return wrap.querySelector('canvas');
  }

  function hideLegacyStrips(card) {
    if (!card) return;
    var cr = rect(card);
    Array.prototype.slice.call(card.querySelectorAll('div,span,i,b')).forEach(function (el) {
      if (!visible(el)) return;
      if (el.closest('.zel-v54-spark-wrap')) return;
      if (el.closest('button,[role="button"],a,input,select,textarea')) return;
      if (el.hasAttribute('data-zel-v54-price-title') || el.hasAttribute('data-zel-v54-feed-status')) return;
      var t = txt(el);
      if (t.length > 0) return;
      var r = rect(el);
      if (r.width < Math.max(70, cr.width * 0.32)) return;
      if (r.height < 1 || r.height > 14) return;
      if (r.top < cr.top + 55 || r.top > cr.bottom - 38) return;
      var c = css(el);
      var bg = c ? c.backgroundColor : '';
      var border = c ? [c.borderTopColor, c.borderBottomColor, c.borderLeftColor, c.borderRightColor].join(' ') : '';
      if ((bg && bg !== 'rgba(0, 0, 0, 0)' && bg !== 'transparent') || /rgb\(/.test(border)) {
        el.setAttribute('data-zel-v54-hidden-strip', '1');
        el.setAttribute('aria-hidden', 'true');
      }
    });
    Array.prototype.slice.call(card.querySelectorAll('[data-zel-v47-hidden-static-bar], [data-zel-v53-hidden-static-strip]')).forEach(function (el) {
      if (!el.closest('.zel-v54-spark-wrap')) el.setAttribute('data-zel-v54-hidden-strip', '1');
    });
  }

  function draw(canvas, sym) {
    if (!canvas) return;
    var s = state[sym];
    var parent = canvas.parentNode;
    var r = rect(parent);
    var w = Math.max(160, Math.floor(r.width || parent.clientWidth || 260));
    var h = Math.max(58, Math.floor(r.height || parent.clientHeight || 72));
    var dpr = Math.min(2, window.devicePixelRatio || 1);
    if (canvas.width !== Math.floor(w * dpr) || canvas.height !== Math.floor(h * dpr)) {
      canvas.width = Math.floor(w * dpr);
      canvas.height = Math.floor(h * dpr);
      canvas.style.width = w + 'px';
      canvas.style.height = h + 'px';
    }
    var ctx = canvas.getContext('2d');
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    ctx.clearRect(0, 0, w, h);

    var grad = ctx.createLinearGradient(0, 0, 0, h);
    grad.addColorStop(0, 'rgba(0,255,214,0.15)');
    grad.addColorStop(1, 'rgba(0,255,214,0.02)');
    ctx.fillStyle = grad;
    ctx.fillRect(0, 0, w, h);

    ctx.strokeStyle = 'rgba(95,234,255,0.13)';
    ctx.lineWidth = 1;
    for (var gy = 1; gy <= 3; gy++) {
      var y = Math.round((h * gy) / 4) + 0.5;
      ctx.beginPath(); ctx.moveTo(0, y); ctx.lineTo(w, y); ctx.stroke();
    }

    var hist = s.hist.slice(-MAX_POINTS);
    if (!hist.length) return;
    var vals = hist.map(function (x) { return x.p; }).filter(finite);
    if (!vals.length) return;
    var min = Math.min.apply(null, vals), max = Math.max.apply(null, vals);
    var pad = Math.max((max - min) * 0.18, max * 0.00003);
    min -= pad; max += pad;
    if (max <= min) { max = vals[0] * 1.0001; min = vals[0] * 0.9999; }
    var xStep = hist.length > 1 ? w / (hist.length - 1) : w;
    function yOf(p) { return h - ((p - min) / (max - min)) * (h - 8) - 4; }

    ctx.beginPath();
    hist.forEach(function (pt, i) {
      var x = hist.length > 1 ? i * xStep : w - 2;
      var y = yOf(pt.p);
      if (i === 0) ctx.moveTo(x, y); else ctx.lineTo(x, y);
    });
    ctx.strokeStyle = 'rgba(96,245,255,0.98)';
    ctx.lineWidth = 2;
    ctx.stroke();

    if (hist.length > 1) {
      ctx.lineTo(w, h); ctx.lineTo(0, h); ctx.closePath();
      var fill = ctx.createLinearGradient(0, 0, 0, h);
      fill.addColorStop(0, 'rgba(0,255,190,0.16)');
      fill.addColorStop(1, 'rgba(0,255,190,0.00)');
      ctx.fillStyle = fill;
      ctx.fill();
    }

    var last = hist[hist.length - 1];
    var lx = hist.length > 1 ? (hist.length - 1) * xStep : w - 2;
    var ly = yOf(last.p);
    ctx.fillStyle = 'rgba(0,255,180,0.95)';
    ctx.beginPath(); ctx.arc(lx, ly, 3.2, 0, Math.PI * 2); ctx.fill();
  }

  function render(card, sym) {
    if (!card || !card.isConnected) return;
    cleanOldArtifacts(card);
    card.classList.add('zel-v54-live-card');
    card.setAttribute('data-zel-v54-symbol', sym);
    var s = state[sym];
    var title = ensureTitle(card, sym);
    var status = ensureStatus(card, sym, title);
    var canvas = ensureSpark(card, sym, title, status);
    var live = finite(s.price) && s.ts && now() - s.ts < STALE_MS;
    if (finite(s.price)) {
      title.textContent = fmtPrice(sym, s.price);
      title.classList.add('zel-v54-has-live-price');
    }
    var age = s.ts ? Math.max(0, now() - s.ts) : null;
    status.textContent = live
      ? ('LIVE ' + (s.source.indexOf('ws') >= 0 ? 'WS' : 'REST') + ' · Δ ' + fmtDelta(s) + ' · ticks ' + s.ticks + ' · age ' + Math.round(age / 1000) + 's')
      : (s.ticks ? 'LIVE stale · ticks ' + s.ticks : 'LIVE waiting');
    card.classList.toggle('zel-v54-feed-live', !!live);
    card.classList.toggle('zel-v54-feed-wait', !live);
    hideLegacyStrips(card);
    draw(canvas, sym);
  }

  function updateSymbol(sym) {
    var card = findCard(sym);
    if (card) render(card, sym);
  }

  function mountAll() {
    SYMBOLS.forEach(function (sym) { updateSymbol(sym); });
    mountedOnce = true;
  }

  function boot() {
    if (document.documentElement.classList.contains('zel-v54-live-core-loaded')) return;
    document.documentElement.classList.add('zel-v54-live-core-loaded');
    window.ZEL_APP_V54_LIVE_FEED = { version: VER, state: state, mount: mountAll, ingest: ingest };
    startWs();
    restFallback();
    mountAll();
    setInterval(mountAll, MOUNT_MS);
    setInterval(function () { SYMBOLS.forEach(updateSymbol); }, REDRAW_MS);
    setInterval(restFallback, REST_MS);
    try {
      var mo = new MutationObserver(function () { if (mountedOnce) setTimeout(mountAll, 50); });
      mo.observe(document.body || document.documentElement, { childList: true, subtree: true });
    } catch (e) {}
  }

  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', boot, { once: true });
  else boot();
})();
