/* ZEL APP V42 live tick chart. One in-card canvas. Not a snapshot: polls server-generated JS feed and redraws rolling ticks. */
(function () {
  'use strict';
  var VER = 'V42';
  var FEED_URL = '/zel_app_v42_live_feed.js';
  var POLL_MS = 1000;
  var MAX_POINTS = 120;
  var mounted = false;
  var hostCard = null;
  var panel = null;
  var canvas = null;
  var ctx = null;
  var statusEl = null;
  var metricsEl = null;
  var pricePill = null;
  var localTicks = [];
  var lastFeedTs = 0;
  var lastDrawAt = 0;

  function now() { return Date.now(); }
  function qs(sel, root) { return (root || document).querySelector(sel); }
  function qsa(sel, root) { return Array.prototype.slice.call((root || document).querySelectorAll(sel)); }
  function txt(el) { return (el && (el.innerText || el.textContent) || '').trim(); }
  function n(v) { var x = Number(v); return Number.isFinite(x) ? x : null; }
  function fmt(v, d) { var x = n(v); if (x === null) return '—'; return x.toLocaleString(undefined, { maximumFractionDigits: d == null ? 2 : d }); }
  function pct(v) { var x = n(v); if (x === null) return '—'; return (Math.abs(x) < 1 && x !== 0 ? x * 100 : x).toLocaleString(undefined, { maximumFractionDigits: 2 }) + '%'; }
  function classify(el) { return ((el.className || '') + ' ' + (el.id || '')).toLowerCase(); }

  function addCleanClass() { document.documentElement.classList.add('zel-v42-clean'); }

  function removeBadgesAndOldGraphs() {
    qsa('.zel-v41-graph-wrap,.zel-v40-graph-wrap,.zel-v39-live-panel,.zel-v38-live-panel,.zel-v37-live-panel,[data-zel-v41],[data-zel-v40],[data-zel-v39]').forEach(function (el) { try { el.remove(); } catch(e){} });
    qsa('body *').forEach(function (el) {
      if (!el || el === panel || (panel && panel.contains(el))) return;
      var s = classify(el);
      var t = txt(el).slice(0, 220);
      var st = window.getComputedStyle ? getComputedStyle(el) : null;
      var isFixed = st && st.position === 'fixed';
      var looksSource = /SOURCE\s+(BOUND|HOLD)/i.test(t) && /BTCUSDT|missing|price|pos|lev|V3|V4/i.test(t);
      if ((isFixed && looksSource) || /source-badge|sourcebadge|floating-source|source-floating/.test(s)) {
        try { el.style.display = 'none'; el.setAttribute('data-zel-v42-hidden','1'); } catch(e){}
      }
    });
  }

  function scoreCard(el) {
    if (!el || el.id === 'zel-v42-tick-chart' || (panel && panel.contains(el))) return -999;
    var t = txt(el);
    if (!/BTCUSDT/i.test(t)) return -999;
    var s = classify(el);
    var rect = el.getBoundingClientRect ? el.getBoundingClientRect() : {width:0,height:0};
    var score = 0;
    if (/card|panel|tile|market|symbol|asset/.test(s)) score += 20;
    if (/unbound|source-bound|source bound|risk-hold|proof=missing|sig=read_only|source-required/i.test(t)) score += 18;
    if (/ETHUSDT|SOLUSDT|XRPUSDT|LINKUSDT/i.test(t)) score -= 20;
    if (rect.width > 220 && rect.width < 900) score += 10;
    if (rect.height > 120 && rect.height < 600) score += 8;
    if (rect.height > 700) score -= 25;
    if (el.querySelector && el.querySelector('#zel-v42-tick-chart')) score -= 999;
    return score;
  }

  function findBtcCard() {
    var nodes = qsa('section,article,div,li');
    var best = null, bestScore = -999;
    nodes.forEach(function (el) {
      var sc = scoreCard(el);
      if (sc > bestScore) { best = el; bestScore = sc; }
    });
    return bestScore > 0 ? best : null;
  }

  function makePanel() {
    var el = document.createElement('div');
    el.id = 'zel-v42-tick-chart';
    el.className = 'zel-v42-tick-chart';
    el.setAttribute('data-zel-v42', 'tick-chart');
    el.innerHTML = '' +
      '<div class="zel-v42-head">' +
        '<div><div class="zel-v42-title">BTCUSDT LIVE TICK CHART</div><div class="zel-v42-sub">CF → server JS feed → app canvas · read-only</div></div>' +
        '<div class="zel-v42-status">binding…</div>' +
      '</div>' +
      '<div class="zel-v42-canvas-wrap"><canvas class="zel-v42-canvas" width="720" height="160"></canvas><div class="zel-v42-price-pill">—</div></div>' +
      '<div class="zel-v42-metrics"></div>' +
      '<div class="zel-v42-note">Rolling live ticks. If CF price does not change, the line stays flat while tick count and source age update.</div>';
    return el;
  }

  function mount() {
    if (mounted && document.getElementById('zel-v42-tick-chart')) return true;
    removeBadgesAndOldGraphs();
    var card = findBtcCard();
    if (!card) return false;
    hostCard = card;
    hostCard.setAttribute('data-zel-v42-host','btc');
    var old = document.getElementById('zel-v42-tick-chart');
    if (old && old.parentNode !== hostCard) old.remove();
    panel = old || makePanel();
    // Remove accidental duplicates before insertion.
    qsa('#zel-v42-tick-chart').slice(1).forEach(function (x) { try { x.remove(); } catch(e){} });
    if (!panel.parentNode) hostCard.appendChild(panel);
    canvas = qs('.zel-v42-canvas', panel);
    ctx = canvas && canvas.getContext ? canvas.getContext('2d') : null;
    statusEl = qs('.zel-v42-status', panel);
    metricsEl = qs('.zel-v42-metrics', panel);
    pricePill = qs('.zel-v42-price-pill', panel);
    mounted = true;
    return true;
  }

  function parseFeed(text) {
    if (!text || /^\s*</.test(text)) throw new Error('feed_html');
    var m = text.match(/ZEL_APP_V42_LIVE_FEED\s*=\s*(\{[\s\S]*?\})\s*;?\s*$/);
    if (!m) throw new Error('feed_marker_missing');
    return JSON.parse(m[1]);
  }

  function mergeFeed(feed) {
    var sym = String((feed && feed.symbol) || '').toUpperCase();
    if (sym && sym !== 'BTCUSDT') return;
    var hist = Array.isArray(feed.history) ? feed.history : [];
    if (hist.length) {
      hist.forEach(function (p) {
        var ts = n(p.ts_ms || p.t || p.ts || p.time) || now();
        var price = n(p.price || p.p || p.value);
        if (price !== null && !localTicks.some(function (x) { return x.ts_ms === ts && x.price === price; })) {
          localTicks.push({ ts_ms: ts, price: price });
        }
      });
    } else {
      var price = n(feed.price);
      var ts = n(feed.source_ts_ms) || n(feed.updated_ts_ms) || now();
      if (price !== null) localTicks.push({ ts_ms: ts, price: price });
    }
    localTicks = localTicks.filter(function (p) { return n(p.price) !== null; }).sort(function (a,b) { return a.ts_ms - b.ts_ms; });
    if (localTicks.length > MAX_POINTS) localTicks = localTicks.slice(localTicks.length - MAX_POINTS);
  }

  function draw(feed) {
    if (!mount() || !ctx) return;
    var dpr = window.devicePixelRatio || 1;
    var rect = canvas.getBoundingClientRect();
    var w = Math.max(260, Math.floor(rect.width || 640));
    var h = Math.max(96, Math.floor(rect.height || 136));
    if (canvas.width !== Math.floor(w * dpr) || canvas.height !== Math.floor(h * dpr)) {
      canvas.width = Math.floor(w * dpr); canvas.height = Math.floor(h * dpr);
    }
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    ctx.clearRect(0, 0, w, h);
    var padL = 10, padR = 54, padT = 10, padB = 20;
    var cw = w - padL - padR, ch = h - padT - padB;
    ctx.fillStyle = 'rgba(2, 10, 18, .35)'; ctx.fillRect(0,0,w,h);
    ctx.strokeStyle = 'rgba(100, 220, 255, .13)'; ctx.lineWidth = 1;
    for (var i=0; i<5; i++) { var y = padT + ch * i / 4; ctx.beginPath(); ctx.moveTo(padL, y); ctx.lineTo(w - padR + 6, y); ctx.stroke(); }

    var pts = localTicks.slice(-MAX_POINTS);
    var priceNow = n(feed && feed.price) || (pts.length ? pts[pts.length-1].price : null);
    if (!pts.length || priceNow === null) {
      ctx.fillStyle = 'rgba(135, 221, 255, .72)'; ctx.font = '12px ui-monospace, monospace'; ctx.fillText('waiting for live ticks', padL + 8, padT + 26);
    } else {
      var prices = pts.map(function (p) { return p.price; });
      var min = Math.min.apply(null, prices), max = Math.max.apply(null, prices);
      if (min === max) { min = min * 0.9995; max = max * 1.0005; if (min === max) { min -= 1; max += 1; } }
      var range = max - min;
      function xAt(i) { return padL + (pts.length === 1 ? cw : cw * i / (pts.length - 1)); }
      function yAt(v) { return padT + ch - ((v - min) / range) * ch; }
      var grad = ctx.createLinearGradient(0, padT, 0, padT + ch);
      grad.addColorStop(0, 'rgba(0, 255, 185, .22)');
      grad.addColorStop(1, 'rgba(0, 255, 185, 0)');
      ctx.beginPath();
      pts.forEach(function (p, i) { var x=xAt(i), y=yAt(p.price); if(i===0) ctx.moveTo(x,y); else ctx.lineTo(x,y); });
      ctx.lineTo(xAt(pts.length-1), padT+ch); ctx.lineTo(xAt(0), padT+ch); ctx.closePath(); ctx.fillStyle = grad; ctx.fill();
      ctx.beginPath();
      pts.forEach(function (p, i) { var x=xAt(i), y=yAt(p.price); if(i===0) ctx.moveTo(x,y); else ctx.lineTo(x,y); });
      ctx.strokeStyle = '#57eaff'; ctx.lineWidth = 2; ctx.stroke();
      var lx = xAt(pts.length-1), ly = yAt(pts[pts.length-1].price);
      ctx.fillStyle = '#00ffba'; ctx.beginPath(); ctx.arc(lx, ly, 4, 0, Math.PI * 2); ctx.fill();
      ctx.fillStyle = 'rgba(234,255,255,.82)'; ctx.font = '10px ui-monospace, monospace'; ctx.textAlign = 'right';
      ctx.fillText(fmt(max, 2), w - 8, padT + 8);
      ctx.fillText(fmt((max+min)/2, 2), w - 8, padT + ch / 2 + 4);
      ctx.fillText(fmt(min, 2), w - 8, padT + ch + 3);
      ctx.textAlign = 'left';
    }

    var ageMs = n(feed && feed.age_ms);
    var tickCount = localTicks.length;
    var stale = ageMs !== null && ageMs > 10000;
    if (statusEl) {
      statusEl.textContent = (feed && feed.ok ? 'SOURCE BOUND' : 'SOURCE HOLD') + ' · ticks ' + tickCount + ' · age ' + (ageMs === null ? '—' : Math.round(ageMs) + 'ms') + ' · Δ ' + deltaText();
      statusEl.classList.toggle('zel-v42-warn', !!stale || !(feed && feed.ok));
    }
    if (pricePill) pricePill.textContent = priceNow === null ? 'price —' : 'price ' + fmt(priceNow, 2);
    if (metricsEl) {
      metricsEl.innerHTML = [
        ['price', fmt(feed && feed.price, 2)],
        ['pos', pct(feed && feed.pos_pct)],
        ['lev', feed && feed.lev != null ? fmt(feed.lev, 2) + 'x' : '—'],
        ['liq', pct(feed && feed.liq_buffer_pct)],
        ['funding8h', pct(feed && feed.funding_8h_pct)],
        ['DD_day', pct(feed && feed.DD_day_pct)],
        ['entry', feed && feed.entry_ts ? 'source_ts fallback' : '—']
      ].map(function (kv) { return '<span>' + kv[0] + ' <b>' + kv[1] + '</b></span>'; }).join('');
    }
    lastDrawAt = now();
  }

  function deltaText() {
    if (localTicks.length < 2) return '0';
    var a = localTicks[localTicks.length - 2].price, b = localTicks[localTicks.length - 1].price;
    var d = b - a;
    if (Math.abs(d) < 1e-9) return '0';
    return (d > 0 ? '+' : '') + d.toFixed(2);
  }

  function poll() {
    removeBadgesAndOldGraphs();
    mount();
    fetch(FEED_URL + '?v=' + now(), { cache: 'no-store' })
      .then(function (r) { if (!r.ok) throw new Error('feed_http_' + r.status); return r.text(); })
      .then(function (text) {
        var feed = parseFeed(text);
        lastFeedTs = now();
        mergeFeed(feed);
        draw(feed);
      })
      .catch(function (err) {
        var fallback = { ok:false, symbol:'BTCUSDT', reason:String(err && err.message || err), age_ms: lastFeedTs ? now() - lastFeedTs : null };
        draw(fallback);
      });
  }

  function boot() {
    addCleanClass();
    removeBadgesAndOldGraphs();
    mount();
    poll();
    setInterval(poll, POLL_MS);
    var obs = new MutationObserver(function () { mount(); removeBadgesAndOldGraphs(); });
    obs.observe(document.documentElement, { childList:true, subtree:true });
  }
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', boot); else boot();
})();
