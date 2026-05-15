(() => {
  "use strict";
  const VERSION = "ZEL_LIVE_ORDERBOOK_WS_V6_SAFE";
  const SYMBOLS = ["BTCUSDT","ETHUSDT","SOLUSDT","XRPUSDT","LINKUSDT"];
  const LOWER = SYMBOLS.map(s => s.toLowerCase());
  const PREC = {
    BTCUSDT:{p:1,a:3}, ETHUSDT:{p:2,a:3}, SOLUSDT:{p:2,a:2}, XRPUSDT:{p:4,a:0}, LINKUSDT:{p:3,a:2}
  };
  const state = new Map();
  const targets = new Map();
  let ws = null;
  let fallbackTimer = null;

  const all = (sel, root=document) => Array.from(root.querySelectorAll(sel));
  const num = v => {
    const n = Number(v);
    return Number.isFinite(n) ? n : null;
  };
  const fmt = (n,d=2) => Number.isFinite(Number(n)) ? Number(n).toLocaleString("en-US",{minimumFractionDigits:d,maximumFractionDigits:d}) : "—";
  const fmtP = (sym,n) => fmt(n, PREC[sym]?.p ?? 2);
  const fmtA = (sym,n) => fmt(n, PREC[sym]?.a ?? 2);

  function emptyBook(symbol, source="loading"){
    return {symbol, asks:[], bids:[], last:null, spread:null, source, ts:0, live:false};
  }

  function parseBook(symbol, asksRaw, bidsRaw, source){
    const asks = (asksRaw || []).map(x => [num(x[0]), num(x[1])]).filter(x => x[0] && x[1] != null).slice(0,5);
    const bids = (bidsRaw || []).map(x => [num(x[0]), num(x[1])]).filter(x => x[0] && x[1] != null).slice(0,5);
    const last = bids[0] && asks[0] ? (bids[0][0] + asks[0][0]) / 2 : (state.get(symbol)?.last || null);
    const spread = bids[0] && asks[0] && last ? ((asks[0][0] - bids[0][0]) / last) * 100 : null;
    return {symbol, asks, bids, last, spread, source, ts:Date.now(), live:true};
  }

  function endpoint(symbol){
    return `https://fapi.binance.com/fapi/v1/depth?symbol=${encodeURIComponent(symbol)}&limit=10`;
  }

  async function fetchBook(symbol){
    try{
      const r = await fetch(endpoint(symbol), { cache:"no-store", mode:"cors" });
      if(!r.ok) throw new Error(`http ${r.status}`);
      const j = await r.json();
      const book = parseBook(symbol, j.asks, j.bids, "binance:rest");
      state.set(symbol, book);
      renderOne(symbol);
    }catch(e){
      const prev = state.get(symbol);
      if(!prev || !prev.live) state.set(symbol, emptyBook(symbol, "rest-blocked"));
      renderOne(symbol);
    }
  }

  function connectWs(){
    try{
      if(ws && (ws.readyState === WebSocket.OPEN || ws.readyState === WebSocket.CONNECTING)) return;
      const streams = LOWER.map(s => `${s}@depth10@500ms`).join("/");
      ws = new WebSocket(`wss://fstream.binance.com/stream?streams=${streams}`);
      window.__ZEL_BOOK_V6_WS__ = "connecting";

      ws.onopen = () => {
        window.__ZEL_BOOK_V6_WS__ = "open";
        stopFallback();
      };
      ws.onmessage = ev => {
        try{
          const msg = JSON.parse(ev.data);
          const stream = String(msg.stream || "");
          const symbol = stream.split("@")[0].toUpperCase();
          if(!SYMBOLS.includes(symbol)) return;
          const data = msg.data || {};
          const book = parseBook(symbol, data.a || data.asks, data.b || data.bids, "binance:wss");
          state.set(symbol, book);
          renderOne(symbol);
        }catch(_){}
      };
      ws.onerror = () => {
        window.__ZEL_BOOK_V6_WS__ = "error";
        startFallback();
      };
      ws.onclose = () => {
        window.__ZEL_BOOK_V6_WS__ = "closed";
        startFallback();
        setTimeout(connectWs, 5000);
      };
    }catch(e){
      window.__ZEL_BOOK_V6_WS__ = "blocked";
      startFallback();
    }
  }

  function startFallback(){
    if(fallbackTimer) return;
    fallbackTimer = setInterval(() => SYMBOLS.forEach(fetchBook), 2000);
  }
  function stopFallback(){
    if(fallbackTimer){ clearInterval(fallbackTimer); fallbackTimer = null; }
  }

  function maxAmt(book){
    return Math.max(1, ...book.asks.map(x=>x[1]||0), ...book.bids.map(x=>x[1]||0));
  }
  function row(sym, side, price, amt, max){
    const w = Math.max(4, Math.min(100, ((amt || 0)/max)*100));
    return `<div class="zel-v6-row ${side}" style="--w:${w}%">
      <div class="zel-v6-price">${fmtP(sym, price)}</div>
      <div class="zel-v6-amt">${fmtA(sym, amt)}</div>
    </div>`;
  }
  function acctLine(kind){
    return `<div class="zel-v6-acct ${kind === "VIRTUAL" ? "v" : ""}">
      <b>${kind}</b><span>flat</span>
    </div>`;
  }
  function renderHtml(symbol, book, focus){
    const asks = book.asks.length ? book.asks.slice().reverse() : Array.from({length:5},()=>[null,null]);
    const bids = book.bids.length ? book.bids : Array.from({length:5},()=>[null,null]);
    const max = maxAmt(book);
    const bidSum = book.bids.reduce((s,x)=>s+(x[1]||0),0);
    const askSum = book.asks.reduce((s,x)=>s+(x[1]||0),0);
    const total = Math.max(1, bidSum + askSum);
    const bidPct = Math.round((bidSum/total)*100);
    const askPct = 100 - bidPct;
    const age = book.ts ? Date.now() - book.ts : 999999;
    const stale = age > 3500;
    const cls = `${focus ? "focus" : "mini"} ${stale ? "zel-v6-stale" : ""}`;
    const src = book.source === "binance:wss" ? "binance:wss live" : `${book.source || "loading"}`;

    return `<div class="zel-v6-book ${cls}" data-zel-v6="1" data-symbol="${symbol}">
      <div class="zel-v6-head">
        <div><div class="zel-v6-symbol">${symbol}</div><div class="zel-v6-src"><span class="zel-v6-live-dot"></span>${src}</div></div>
        <div class="zel-v6-pill">${focus ? "FOCUS" : "VIEW"}</div>
      </div>
      <div class="zel-v6-top">
        <div class="zel-v6-metric"><div class="zel-v6-label">last</div><div class="zel-v6-value">${fmtP(symbol, book.last)}</div></div>
        <div class="zel-v6-metric"><div class="zel-v6-label">spread</div><div class="zel-v6-value">${book.spread==null ? "—" : fmt(book.spread,2)+"%"}</div></div>
      </div>
      <div class="zel-v6-depthbar"><i style="width:${bidPct}%"></i><i style="width:${askPct}%"></i></div>
      <div class="zel-v6-ladder">
        <div class="zel-v6-grid"><div class="zel-v6-colh">Price</div><div class="zel-v6-colh" style="text-align:right">Amount</div></div>
        ${asks.map(x => row(symbol,"ask",x[0],x[1],max)).join("")}
        <div class="zel-v6-mid"><div class="zel-v6-last">${fmtP(symbol, book.last)}</div><div class="zel-v6-lasttag">LAST</div></div>
        ${bids.map(x => row(symbol,"bid",x[0],x[1],max)).join("")}
      </div>
      <div class="zel-v6-accounts">
        ${acctLine("LIVE")}
        ${acctLine("VIRTUAL")}
      </div>
      <div class="zel-v6-foot">
        <span class="zel-v6-mini-pill">action hold</span>
        <span class="zel-v6-mini-pill">${book.live ? "market-live" : "market-loading"}</span>
      </div>
    </div>`;
  }

  function bestCardCandidate(symbol){
    const nodes = all("section,article,div,li").filter(el => {
      if (el.dataset?.zelV6Host === "1") return false;
      if (el.closest?.(".zel-v6-book")) return false;
      if ((el.textContent || "").toUpperCase().indexOf(symbol) < 0) return false;
      const txtLen = (el.textContent || "").length;
      const rect = el.getBoundingClientRect();
      if (rect.width < 140 || rect.height < 60) return false;
      if (txtLen > 2600) return false;
      return true;
    });

    nodes.sort((a,b) => {
      const ar=a.getBoundingClientRect(), br=b.getBoundingClientRect();
      const scoreA = ar.width*ar.height + (a.dataset.zelV6Pre === "1" ? -999999 : 0);
      const scoreB = br.width*br.height + (b.dataset.zelV6Pre === "1" ? -999999 : 0);
      return scoreA - scoreB;
    });
    return nodes[0] || null;
  }

  function claimCards(){
    SYMBOLS.forEach((sym, idx) => {
      if(targets.has(sym)) return;
      const pre = document.querySelector(`[data-zel-v6-pre="${sym}"]`);
      const el = pre || bestCardCandidate(sym);
      if(!el) return;
      el.dataset.zelV6Host = "1";
      el.replaceChildren();
      targets.set(sym, el);
      state.set(sym, state.get(sym) || emptyBook(sym, "loading"));
      el.insertAdjacentHTML("afterbegin", renderHtml(sym, state.get(sym), idx===0));
    });
  }

  function renderOne(symbol){
    const el = targets.get(symbol);
    if(!el) return;
    const idx = SYMBOLS.indexOf(symbol);
    el.replaceChildren();
    el.insertAdjacentHTML("afterbegin", renderHtml(symbol, state.get(symbol) || emptyBook(symbol), idx===0));
  }

  function killBottomSourceHold(){
    const re = /SOURCE\s+HOLD\s+V34|missing:\s*price|missing:price|MinData\s+missing/i;
    all("body *").forEach(el => {
      if (el.closest?.(".zel-v6-book")) return;
      const txt = (el.textContent || "").trim();
      if (!txt || !re.test(txt)) return;

      let target = el;
      for(let i=0; i<8 && target && target !== document.body; i++){
        const cs = getComputedStyle(target);
        const rect = target.getBoundingClientRect();
        const fixedLike = cs.position === "fixed" || cs.position === "sticky";
        const bottomLike = rect.bottom > window.innerHeight - 110 && rect.top > window.innerHeight * 0.45;
        if(fixedLike || bottomLike) break;
        target = target.parentElement;
      }

      if(!target || target === document.body) return;
      const r = target.getBoundingClientRect();
      const cs = getComputedStyle(target);
      const shouldHide = cs.position === "fixed" || cs.position === "sticky" || (r.bottom > window.innerHeight - 110 && r.top > window.innerHeight * 0.45);
      if(shouldHide){
        target.classList.add("zel-v6-kill-source-hold");
        target.style.setProperty("display","none","important");
        target.style.setProperty("visibility","hidden","important");
      }
    });
  }

  function expose(){
    window.__ZEL_BOOK_V6__ = {
      version: VERSION,
      targets: Array.from(targets.keys()),
      ws: window.__ZEL_BOOK_V6_WS__ || "init",
      state: Object.fromEntries(SYMBOLS.map(s => [s, state.get(s) || emptyBook(s)])),
      ts: Date.now()
    };
  }

  function boot(){
    SYMBOLS.forEach(s => state.set(s, emptyBook(s, "loading")));
    claimCards();
    killBottomSourceHold();
    connectWs();
    startFallback();
    SYMBOLS.forEach(fetchBook);
    setInterval(() => { claimCards(); killBottomSourceHold(); expose(); }, 1800);
    setInterval(() => SYMBOLS.forEach(renderOne), 3000);
    expose();
    console.info("[ZEL]", VERSION, "boot");
  }

  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", boot, {once:true});
  else boot();
})();

;try{window.__ZEL_ORDERBOOK_PERF_STABILIZE_V1__={installed:true,stream:'depth10@500ms',fallbackMs:5000,claimMs:'1800-3000',ts:Date.now()};}catch(_){ }
