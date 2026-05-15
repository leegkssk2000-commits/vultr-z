(() => {
  "use strict";
  const VERSION = "ZEL_BTC_MAIN_ORDERBOOK_V8_SAFE";
  const SYMBOL = "BTCUSDT";
  let host = null;
  let ws = null;
  let fallbackTimer = null;
  let lastClaimAt = 0;
  const state = { symbol: SYMBOL, asks: [], bids: [], last: null, spread: null, source: "loading", ts: 0, live: false };

  const all = (sel, root = document) => Array.from(root.querySelectorAll(sel));
  const finite = v => { const n = Number(v); return Number.isFinite(n) ? n : null; };
  const fmt = (n, d) => Number.isFinite(Number(n)) ? Number(n).toLocaleString("en-US", { minimumFractionDigits: d, maximumFractionDigits: d }) : "—";
  const fmtP = n => fmt(n, 1);
  const fmtA = n => fmt(n, 3);

  function isOwned(el){ return !!(el && el.dataset && el.dataset.zelBtcMainV8Host === "1"); }
  function visibleRect(el){ try { return el.getBoundingClientRect(); } catch (_) { return { width:0, height:0, top:99999, bottom:99999 }; } }

  function candidateScore(el){
    const txt = (el.textContent || "").toUpperCase();
    if (!txt.includes(SYMBOL)) return null;
    if (!txt.includes("UNBOUND")) return null;
    if (!(txt.includes("RISK-HOLD") || txt.includes("PROOF-MISSING") || txt.includes("SOURCE-REQUIRED") || txt.includes("XAI:"))) return null;
    if (txt.includes("ADVANCED ZEL STACK") || txt.includes("ZEL DECISION STACK") || txt.includes("LIVE / REAL")) return null;
    if (el.closest && (el.closest(".zel-btc-v8-card") || el.closest(".zel-v6-book"))) return null;
    const r = visibleRect(el);
    if (r.width < 260 || r.height < 120) return null;
    if (txt.length > 1500) return null;
    const area = r.width * r.height;
    const shapePenalty = Math.abs(r.width - 500) * 1.5 + Math.abs(r.height - 230);
    const topPenalty = Math.max(0, r.top) * 0.02;
    return area + shapePenalty + topPenalty;
  }

  function findMainBtcCard(){
    if (host && document.contains(host)) return host;
    const nodes = all("section,article,div,li");
    const scored = [];
    for (const el of nodes){
      if (isOwned(el)) return el;
      const s = candidateScore(el);
      if (s != null) scored.push([s, el]);
    }
    scored.sort((a,b) => a[0] - b[0]);
    return scored.length ? scored[0][1] : null;
  }

  function parseBook(asksRaw, bidsRaw, source){
    const asks = (asksRaw || []).map(x => [finite(x[0]), finite(x[1])]).filter(x => x[0] != null && x[1] != null).slice(0, 5);
    const bids = (bidsRaw || []).map(x => [finite(x[0]), finite(x[1])]).filter(x => x[0] != null && x[1] != null).slice(0, 5);
    state.asks = asks;
    state.bids = bids;
    state.last = bids[0] && asks[0] ? (bids[0][0] + asks[0][0]) / 2 : state.last;
    state.spread = bids[0] && asks[0] && state.last ? ((asks[0][0] - bids[0][0]) / state.last) * 100 : state.spread;
    state.source = source;
    state.ts = Date.now();
    state.live = true;
  }

  async function fetchBook(){
    try{
      const r = await fetch("https://fapi.binance.com/fapi/v1/depth?symbol=BTCUSDT&limit=10", { cache:"no-store", mode:"cors" });
      if (!r.ok) throw new Error("http " + r.status);
      const j = await r.json();
      parseBook(j.asks, j.bids, "binance:rest");
      render();
    }catch(e){
      if (!state.live) state.source = "rest-blocked";
      render();
    }
  }

  function connectWs(){
    try{
      if (ws && (ws.readyState === WebSocket.OPEN || ws.readyState === WebSocket.CONNECTING)) return;
      ws = new WebSocket("wss://fstream.binance.com/ws/btcusdt@depth10@100ms");
      window.__ZEL_BTC_MAIN_V8_WS__ = "connecting";
      ws.onopen = () => { window.__ZEL_BTC_MAIN_V8_WS__ = "open"; stopFallback(); };
      ws.onmessage = ev => {
        try{
          const data = JSON.parse(ev.data || "{}");
          parseBook(data.a || data.asks, data.b || data.bids, "binance:wss");
          render();
        }catch(_){}
      };
      ws.onerror = () => { window.__ZEL_BTC_MAIN_V8_WS__ = "error"; startFallback(); };
      ws.onclose = () => { window.__ZEL_BTC_MAIN_V8_WS__ = "closed"; startFallback(); setTimeout(connectWs, 3000); };
    }catch(e){
      window.__ZEL_BTC_MAIN_V8_WS__ = "blocked";
      startFallback();
    }
  }

  function startFallback(){ if (!fallbackTimer) fallbackTimer = setInterval(fetchBook, 2000); }
  function stopFallback(){ if (fallbackTimer) { clearInterval(fallbackTimer); fallbackTimer = null; } }

  function maxAmt(){ return Math.max(1, ...state.asks.map(x => x[1] || 0), ...state.bids.map(x => x[1] || 0)); }
  function el(tag, cls, text){ const n = document.createElement(tag); if (cls) n.className = cls; if (text != null) n.textContent = text; return n; }
  function row(side, price, amount, max){
    const r = el("div", "zel-btc-v8-row " + side);
    const w = Math.max(4, Math.min(100, ((amount || 0) / max) * 100));
    r.style.setProperty("--w", w + "%");
    r.appendChild(el("div", "zel-btc-v8-price", price == null ? "—" : fmtP(price)));
    r.appendChild(el("div", "zel-btc-v8-amt", amount == null ? "—" : fmtA(amount)));
    return r;
  }
  function metric(label, value){
    const m = el("div", "zel-btc-v8-metric");
    m.appendChild(el("div", "zel-btc-v8-label", label));
    m.appendChild(el("div", "zel-btc-v8-value", value));
    return m;
  }
  function acct(kind, value){
    const a = el("div", "zel-btc-v8-acct" + (kind === "VIRTUAL" ? " v" : ""));
    a.appendChild(el("b", "", kind));
    a.appendChild(el("span", "", value || "flat"));
    return a;
  }

  function buildView(){
    const age = state.ts ? Date.now() - state.ts : 999999;
    const stale = age > 3500;
    const asks = state.asks.length ? state.asks.slice().reverse() : Array.from({length:5}, () => [null, null]);
    const bids = state.bids.length ? state.bids : Array.from({length:5}, () => [null, null]);
    const bidSum = state.bids.reduce((s,x) => s + (x[1] || 0), 0);
    const askSum = state.asks.reduce((s,x) => s + (x[1] || 0), 0);
    const total = Math.max(1, bidSum + askSum);
    const bidPct = Math.round((bidSum / total) * 100);
    const askPct = 100 - bidPct;
    const max = maxAmt();

    const root = el("div", "zel-btc-v8-card" + (stale ? " zel-btc-v8-stale" : ""));
    root.dataset.zelBtcMainV8Book = "1";

    const head = el("div", "zel-btc-v8-head");
    const title = el("div", "");
    title.appendChild(el("div", "zel-btc-v8-symbol", SYMBOL));
    const src = el("div", "zel-btc-v8-src");
    src.appendChild(el("span", "zel-btc-v8-live-dot"));
    src.appendChild(document.createTextNode(state.source || "loading"));
    title.appendChild(src);
    head.appendChild(title);
    head.appendChild(el("div", "zel-btc-v8-pill", "FOCUS"));
    root.appendChild(head);

    const top = el("div", "zel-btc-v8-top");
    top.appendChild(metric("last", fmtP(state.last)));
    top.appendChild(metric("spread", state.spread == null ? "—" : fmt(state.spread, 2) + "%"));
    root.appendChild(top);

    const bar = el("div", "zel-btc-v8-depthbar");
    const bi = document.createElement("i"); bi.style.width = bidPct + "%";
    const ai = document.createElement("i"); ai.style.width = askPct + "%";
    bar.appendChild(bi); bar.appendChild(ai); root.appendChild(bar);

    const ladder = el("div", "zel-btc-v8-ladder");
    const grid = el("div", "zel-btc-v8-grid");
    grid.appendChild(el("div", "zel-btc-v8-colh", "Price"));
    const ch = el("div", "zel-btc-v8-colh", "Amount"); ch.style.textAlign = "right"; grid.appendChild(ch);
    ladder.appendChild(grid);
    asks.forEach(x => ladder.appendChild(row("ask", x[0], x[1], max)));
    const mid = el("div", "zel-btc-v8-mid");
    mid.appendChild(el("div", "zel-btc-v8-last", fmtP(state.last)));
    mid.appendChild(el("div", "zel-btc-v8-lasttag", "LAST"));
    ladder.appendChild(mid);
    bids.forEach(x => ladder.appendChild(row("bid", x[0], x[1], max)));
    root.appendChild(ladder);

    const accounts = el("div", "zel-btc-v8-accounts");
    accounts.appendChild(acct("LIVE", "flat"));
    accounts.appendChild(acct("VIRTUAL", "flat"));
    root.appendChild(accounts);

    const foot = el("div", "zel-btc-v8-foot");
    foot.appendChild(el("span", "zel-btc-v8-mini-pill", "action hold"));
    foot.appendChild(el("span", "zel-btc-v8-mini-pill", state.live ? "market-live" : "market-loading"));
    root.appendChild(foot);
    return root;
  }

  function claim(){
    const now = Date.now();
    if (host && document.contains(host)) return true;
    if (now - lastClaimAt < 250) return false;
    lastClaimAt = now;
    const found = findMainBtcCard();
    if (!found) return false;
    host = found;
    host.dataset.zelBtcMainV8Host = "1";
    host.dataset.zelV6Host = "1";
    host.style.setProperty("min-height", "228px");
    render();
    return true;
  }

  function render(){
    if (!claim() || !host) return;
    const view = buildView();
    while (host.firstChild) host.removeChild(host.firstChild);
    host.appendChild(view);
    expose();
  }

  function expose(){
    window.__ZEL_BTC_MAIN_V8__ = {
      version: VERSION,
      installed: true,
      targetFound: !!(host && document.contains(host)),
      symbol: SYMBOL,
      source: state.source,
      ws: window.__ZEL_BTC_MAIN_V8_WS__ || "init",
      live: !!state.live,
      last: state.last,
      spread: state.spread,
      ts: Date.now()
    };
  }

  function boot(){
    claim();
    connectWs();
    startFallback();
    fetchBook();
    const mo = new MutationObserver(() => {
      if (!host || !document.contains(host) || !host.querySelector(".zel-btc-v8-card")) claim();
    });
    try { mo.observe(document.documentElement, { childList:true, subtree:true }); } catch (_) {}
    setInterval(() => { claim(); render(); }, 1500);
    expose();
    console.info("[ZEL]", VERSION, "boot");
  }

  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", boot, { once:true });
  else boot();
})();
