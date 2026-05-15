/* ZEL APP V47 live orderbook/account cards
 * Scope: app-only browser layer. No nginx/caddy/systemd/server-route mutation. No orders.
 * Purpose: make the existing 5 market cards become native live mini orderbooks, with live/virtual account slots.
 */
(function(){
  'use strict';
  if (window.__ZEL_APP_V47_LIVE_ORDERBOOK_ACCOUNT_CARDS__) return;
  window.__ZEL_APP_V47_LIVE_ORDERBOOK_ACCOUNT_CARDS__ = true;

  var VERSION = 'V47';
  var SYMBOLS = ['BTCUSDT','ETHUSDT','SOLUSDT','XRPUSDT','LINKUSDT'];
  var STREAMS = SYMBOLS.map(function(s){return s.toLowerCase()+'@depth5@500ms';}).join('/');
  var FUTURES_WS = 'wss://fstream.binance.com/stream?streams=' + STREAMS;
  var SPOT_WS = 'wss://stream.binance.com:9443/stream?streams=' + STREAMS;
  var FUTURES_REST = 'https://fapi.binance.com/fapi/v1/depth?limit=5&symbol=';
  var SPOT_REST = 'https://api.binance.com/api/v3/depth?limit=5&symbol=';
  var CF_URLS = [
    'https://lico-canonical-signed-snapshot.tv-sign-proxy.workers.dev/snapshot'
  ];

  var book = Object.create(null);
  var cards = Object.create(null);
  var ws = null;
  var wsMode = 'futures';
  var reconnectTimer = 0;
  var lastAnyTick = 0;
  var startedAt = Date.now();
  var account = {
    source: 'exchange+cf',
    sourceTs: 0,
    live: { wallet:null, available:null, upnl:null, pnl:null, per:Object.create(null) },
    virtual: { equity:null, balance:null, start:null, pnl:null, pnlPct:null, per:Object.create(null) }
  };

  SYMBOLS.forEach(function(sym){
    book[sym] = {symbol:sym, ok:false, asks:[], bids:[], mid:null, last:null, prev:null, spread:null, source:'waiting', ts:0, ticks:0, err:null};
    account.live.per[sym] = {pos:null, lev:null, liq:null, entry:null, src:null};
    account.virtual.per[sym] = {pos:null, lev:null, eq:null, pnl:null, src:null};
  });

  function n(v){
    if (v === null || v === undefined || v === '' || v === '—' || v === 'unbound') return null;
    if (typeof v === 'string') v = v.replace(/[%x,]/g,'').trim();
    var x = Number(v);
    return Number.isFinite(x) ? x : null;
  }
  function isObj(v){ return v && typeof v === 'object' && !Array.isArray(v); }
  function esc(s){ return String(s==null?'':s).replace(/[&<>\"]/g,function(c){return {'&':'&amp;','<':'&lt;','>':'&gt;','\"':'&quot;'}[c]||c;}); }
  function text(v, fallback){ return v==null || v==='' ? (fallback || '—') : String(v); }
  function compact(v, suffix){ v=n(v); return v==null ? '—' : fmtQty(v) + (suffix||''); }

  function fmtPrice(sym, v){
    v=n(v); if(v===null) return '—';
    var d = sym.indexOf('BTC')===0 || sym.indexOf('ETH')===0 ? 1 : (v>=10 ? 3 : 4);
    return v.toLocaleString('en-US',{minimumFractionDigits:d, maximumFractionDigits:d});
  }
  function fmtQty(v){
    v=n(v); if(v===null) return '—';
    var av=Math.abs(v);
    if(av>=1000000) return (v/1000000).toFixed(2).replace(/\.00$/,'')+'M';
    if(av>=1000) return (v/1000).toFixed(2).replace(/\.00$/,'')+'K';
    if(av>=100) return v.toFixed(0);
    if(av>=10) return v.toFixed(1).replace(/\.0$/,'');
    if(av>=1) return v.toFixed(3).replace(/0+$/,'').replace(/\.$/,'');
    return v.toFixed(4).replace(/0+$/,'').replace(/\.$/,'');
  }
  function pctMove(b){
    if(!b.prev || !b.last) return {txt:'0.000%', cls:'flat'};
    var p = ((b.last-b.prev)/b.prev)*100;
    return {txt:(p>0?'+':'')+p.toFixed(3)+'%', cls:p>0?'up':(p<0?'down':'flat')};
  }

  function pick(obj, keys){
    if(!isObj(obj)) return null;
    for(var i=0;i<keys.length;i++){
      if(Object.prototype.hasOwnProperty.call(obj, keys[i]) && obj[keys[i]] !== undefined && obj[keys[i]] !== null && obj[keys[i]] !== '') return obj[keys[i]];
    }
    return null;
  }
  function deepPick(root, keys, limit){
    limit = limit || 120;
    var seen = [];
    function walk(o, depth){
      if(!isObj(o) || depth>5 || seen.indexOf(o)>=0 || seen.length>limit) return null;
      seen.push(o);
      var direct = pick(o, keys);
      if(direct !== null) return direct;
      var names = Object.keys(o);
      for(var i=0;i<names.length;i++){
        var v=o[names[i]];
        if(isObj(v)){
          var got=walk(v, depth+1); if(got !== null) return got;
        }
      }
      return null;
    }
    return walk(root,0);
  }
  function arrify(v){ return Array.isArray(v) ? v : (isObj(v) ? Object.keys(v).map(function(k){ var x=v[k]; if(isObj(x) && !x.symbol) x.symbol=k; return x; }) : []); }

  function normalizeDepth(sym, asks, bids, source){
    var old = book[sym] || {};
    var a = (asks||[]).map(function(r){return {p:n(r[0]), q:n(r[1])};}).filter(function(r){return r.p!==null && r.q!==null;}).slice(0,5);
    var b = (bids||[]).map(function(r){return {p:n(r[0]), q:n(r[1])};}).filter(function(r){return r.p!==null && r.q!==null;}).slice(0,5);
    if(!a.length || !b.length) return;
    var bestAsk=a[0].p, bestBid=b[0].p;
    var mid=(bestAsk+bestBid)/2;
    book[sym] = {
      symbol:sym, ok:true, asks:a, bids:b, mid:mid, last:mid, prev:old.last || mid,
      spread: bestAsk-bestBid, source:source, ts:Date.now(), ticks:(old.ticks||0)+1, err:null
    };
    lastAnyTick = Date.now();
    renderSymbol(sym);
    renderAdvancedPanel();
  }

  function connectWS(mode){
    clearTimeout(reconnectTimer);
    try { if(ws) ws.close(); } catch(e) {}
    wsMode = mode || wsMode || 'futures';
    var url = wsMode === 'spot' ? SPOT_WS : FUTURES_WS;
    try { ws = new WebSocket(url); } catch(e) { fallbackRest(); return; }
    ws.onmessage = function(ev){
      try{
        var msg=JSON.parse(ev.data); var d=msg.data||msg;
        var sym=(d.s||'').toUpperCase();
        if(SYMBOLS.indexOf(sym)<0) return;
        normalizeDepth(sym, d.a || d.asks, d.b || d.bids, wsMode==='spot'?'binance-spot-ws':'binance-futures-ws');
      }catch(e){}
    };
    ws.onerror = function(){ scheduleReconnect(); };
    ws.onclose = function(){ scheduleReconnect(); };
    setTimeout(function(){
      if(Date.now()-lastAnyTick>4500){
        if(wsMode==='futures') connectWS('spot'); else fallbackRest();
      }
    }, 5000);
  }
  function scheduleReconnect(){
    clearTimeout(reconnectTimer);
    reconnectTimer=setTimeout(function(){ connectWS(wsMode==='futures'?'spot':'futures'); }, 2500);
  }
  function fallbackRest(){
    SYMBOLS.forEach(function(sym, idx){
      (function poll(){
        fetch(FUTURES_REST+sym,{cache:'no-store',mode:'cors'}).then(function(r){return r.ok?r.json():Promise.reject(r.status);})
        .catch(function(){return fetch(SPOT_REST+sym,{cache:'no-store',mode:'cors'}).then(function(r){return r.ok?r.json():Promise.reject(r.status);});})
        .then(function(j){ normalizeDepth(sym, j.asks, j.bids, 'binance-rest'); })
        .catch(function(e){ book[sym].err=String(e||'fetch'); renderSymbol(sym); })
        .finally(function(){ setTimeout(poll, 1000 + idx*140); });
      })();
    });
  }

  function applyPerSymbol(target, sym, obj, src){
    if(!target || !sym || SYMBOLS.indexOf(sym)<0 || !isObj(obj)) return;
    var slot = target.per[sym] || (target.per[sym]={pos:null,lev:null,liq:null,entry:null,src:null});
    var pos = pick(obj, ['pos_pct','pos%','position_pct','position_percent','positionPct','pos','position','size_pct','sizePct']);
    var lev = pick(obj, ['lev','leverage','leverage_x','leverageX']);
    var liq = pick(obj, ['liq_buffer_pct','liq_buffer%','liqBufferPct','liq_buffer','liquidation_buffer_pct']);
    var entry = pick(obj, ['entry_ts','entryTs','entry_time','open_ts','source_ts_ms']);
    var eq = pick(obj, ['equity','equity_usdt','virtual_equity_usdt','balance','current_balance_usdt']);
    var pnl = pick(obj, ['pnl','upnl','unrealized_pnl','virtual_asset_pnl','pnl_pct','virtual_pnl_pct']);
    if(pos !== null) slot.pos=n(pos);
    if(lev !== null) slot.lev=n(lev);
    if(liq !== null) slot.liq=n(liq);
    if(entry !== null) slot.entry=entry;
    if(eq !== null) slot.eq=n(eq);
    if(pnl !== null) slot.pnl=n(pnl);
    if(pos !== null || lev !== null || liq !== null || eq !== null || pnl !== null) slot.src = src || 'cf';
  }

  function parsePayload(j){
    if(!j) return;
    var roots=[];
    function add(o){ if(isObj(o) && roots.indexOf(o)<0) roots.push(o); }
    add(j); add(j.payload); add(j.data); add(j.alimi); add(j.trade_state); add(j.risk); add(j.live_account); add(j.virtual_account);
    roots.forEach(function(o){ add(o && o.payload); add(o && o.trade_state); add(o && o.risk); add(o && o.live_account); add(o && o.virtual_account); });

    account.sourceTs = Date.now();
    var la = j.live_account || (j.payload && j.payload.live_account) || (j.data && j.data.live_account) || {};
    var va = j.virtual_account || (j.payload && j.payload.virtual_account) || (j.data && j.data.virtual_account) || {};
    account.live.wallet = n(pick(la,['wallet_balance','walletBalance','totalWalletBalance','balance','USDT.free+locked']));
    account.live.available = n(pick(la,['availableBalance','available_balance','available','free']));
    account.live.upnl = n(pick(la,['unrealized_pnl','unrealizedPnl','upnl','live_pnl']));
    account.live.pnl = n(pick(la,['pnl','live_pnl','realized_pnl']));
    account.virtual.equity = n(pick(va,['virtual_equity_usdt','equity_usdt','equity','current_balance_usdt']));
    account.virtual.balance = n(pick(va,['current_balance_usdt','balance','current_balance']));
    account.virtual.start = n(pick(va,['start_balance_usdt','start_balance']));
    account.virtual.pnl = n(pick(va,['virtual_asset_pnl','pnl','asset_pnl']));
    account.virtual.pnlPct = n(pick(va,['virtual_pnl_pct','pnl_pct','pnl%']));

    roots.forEach(function(o){
      if(!isObj(o)) return;
      var sym = String(pick(o,['symbol','sym','ticker']) || '').toUpperCase();
      if(SYMBOLS.indexOf(sym)>=0){
        applyPerSymbol(account.live, sym, o, 'cf');
        if(o.virtual || o.paper || o.route === 'virtual') applyPerSymbol(account.virtual, sym, o, 'cf');
      }
    });
    roots.forEach(function(o){
      ['positions','position','live_positions','livePositions','symbols','market_cards','cards','trade_states'].forEach(function(k){
        arrify(o && o[k]).forEach(function(p){
          var sym=String(p && (p.symbol || p.sym || p.ticker || p.name) || '').toUpperCase();
          applyPerSymbol(account.live, sym, p, 'cf');
        });
      });
      ['virtual_positions','paper_positions','virtualPositions','paperPositions'].forEach(function(k){
        arrify(o && o[k]).forEach(function(p){
          var sym=String(p && (p.symbol || p.sym || p.ticker || p.name) || '').toUpperCase();
          applyPerSymbol(account.virtual, sym, p, 'cf');
        });
      });
    });

    // BTC fallback from flat source-bound envelope.
    var flat = j.payload || j.data || j;
    if(isObj(flat)){
      var fsym = String(pick(flat,['symbol','sym']) || '').toUpperCase();
      if(!fsym && n(pick(flat,['pos_pct','pos%','pos'])) !== null) fsym='BTCUSDT';
      if(SYMBOLS.indexOf(fsym)>=0) applyPerSymbol(account.live, fsym, flat, 'cf');
      var price = n(pick(flat,['price','last_price','mark_price']));
      if(price !== null && fsym && SYMBOLS.indexOf(fsym)>=0 && !book[fsym].ok){
        book[fsym].last=price; book[fsym].prev=book[fsym].prev||price; book[fsym].mid=price; book[fsym].source='cf-price'; book[fsym].ts=Date.now();
      }
    }
  }

  function fetchJson(url){
    return fetch(url + (url.indexOf('?')>=0?'&':'?') + 'v=' + Date.now(), {cache:'no-store', mode:'cors'})
      .then(function(r){ return r.ok ? r.text() : Promise.reject(r.status); })
      .then(function(txt){
        txt = String(txt||'').trim();
        if(!txt || txt.charAt(0)==='<') throw new Error('non-json');
        return JSON.parse(txt);
      });
  }
  function pollCF(){
    var chain = Promise.reject('start');
    CF_URLS.forEach(function(url){ chain = chain.catch(function(){ return fetchJson(url); }); });
    chain.then(parsePayload).catch(function(){ parseDomMetrics(); }).finally(function(){ renderAll(); renderAdvancedPanel(); setTimeout(pollCF, 1600); });
  }
  function parseDomMetrics(){
    var t=(document.body&&document.body.innerText)||'';
    var o={symbol:'BTCUSDT'};
    var m=t.match(/pos(?:%|_pct)?\s*[:= ]\s*([0-9.]+)/i); if(m) o.pos_pct=n(m[1]);
    m=t.match(/lev\s*[:= ]\s*([0-9.]+)/i); if(m) o.lev=n(m[1]);
    m=t.match(/liq[_ ]?buffer(?:%|_pct)?\s*[:= ]\s*([0-9.]+)/i); if(m) o.liq_buffer_pct=n(m[1]);
    applyPerSymbol(account.live, 'BTCUSDT', o, 'dom');
  }

  function accountLine(sym){
    var lp = account.live.per[sym] || {};
    var vp = account.virtual.per[sym] || {};
    var virtPos = vp.pos != null ? compact(vp.pos,'%') : '—';
    var virtLev = vp.lev != null ? compact(vp.lev,'x') : '—';
    var liq = lp.liq != null ? '<span class="z47-mini">LQ '+compact(lp.liq,'%')+'</span>' : '';
    return '<div class="z47-account">'
      + '<span class="z47-mini live">LIVE POS '+compact(lp.pos,'%')+'</span>'
      + '<span class="z47-mini live">LEV '+compact(lp.lev,'x')+'</span>'
      + liq
      + '<span class="z47-mini virt">VIRT POS '+virtPos+'</span>'
      + '<span class="z47-mini virt">LEV '+virtLev+'</span>'
      + '</div>';
  }

  function template(sym){
    return '<div class="z47-card" data-z47-sym="'+sym+'">'
      + '<div class="z47-head"><div class="z47-sym">'+sym+'</div><div class="z47-venue" data-z47-venue>CONNECTING</div></div>'
      + '<div class="z47-priceLine"><div class="z47-price" data-z47-price>loading</div><div class="z47-move flat" data-z47-move>0.000%</div></div>'
      + '<div data-z47-account>'+accountLine(sym)+'</div>'
      + '<div class="z47-book" data-z47-book></div>'
      + '<div class="z47-foot" data-z47-foot></div>'
      + '</div>';
  }

  function renderRows(sym,b){
    if(!b.ok){
      return '<div class="z47-row ask"><span>ask —</span><span class="qty">—</span></div>'
        + '<div class="z47-row ask"><span>ask —</span><span class="qty">—</span></div>'
        + '<div class="z47-row ask"><span>ask —</span><span class="qty">—</span></div>'
        + '<div class="z47-mid"><span class="last">waiting live orderbook</span><span class="spread">spread —</span></div>'
        + '<div class="z47-row bid"><span>bid —</span><span class="qty">—</span></div>'
        + '<div class="z47-row bid"><span>bid —</span><span class="qty">—</span></div>'
        + '<div class="z47-row bid"><span>bid —</span><span class="qty">—</span></div>';
    }
    var all=b.asks.concat(b.bids); var maxq=1;
    all.forEach(function(r){ if(r.q>maxq) maxq=r.q; });
    function row(r,cls){
      var w = maxq ? Math.max(3, Math.min(100, (r.q/maxq)*100)) : 0;
      return '<div class="z47-row '+cls+'" style="--w:'+w.toFixed(1)+'%"><span>'+fmtPrice(sym,r.p)+'</span><span class="qty">'+fmtQty(r.q)+'</span></div>';
    }
    var asks=b.asks.slice().reverse().map(function(r){return row(r,'ask');}).join('');
    var bids=b.bids.slice(0,5).map(function(r){return row(r,'bid');}).join('');
    return asks + '<div class="z47-mid"><span class="last">'+fmtPrice(sym,b.last)+'</span><span class="spread">spr '+fmtPrice(sym,b.spread)+'</span></div>' + bids;
  }
  function renderFoot(sym,b){
    var parts=[];
    parts.push('<span class="z47-pill lock">ORDER RO</span>');
    parts.push('<span class="z47-pill">'+(b.ok?'ticks '+b.ticks:'feed wait')+'</span>');
    if(account.live.per[sym] && account.live.per[sym].src) parts.push('<span class="z47-pill src">acct '+esc(account.live.per[sym].src)+'</span>');
    return parts.join('');
  }
  function renderSymbol(sym){
    var el=cards[sym]; if(!el || !el.isConnected) return;
    var b=book[sym];
    var price=el.querySelector('[data-z47-price]'); if(price) price.textContent=b.ok?fmtPrice(sym,b.last):(b.last?fmtPrice(sym,b.last):'live pending');
    var mv=pctMove(b); var move=el.querySelector('[data-z47-move]'); if(move){ move.textContent=mv.txt; move.className='z47-move '+mv.cls; }
    var venue=el.querySelector('[data-z47-venue]'); if(venue) venue.textContent=b.ok?'LIVE '+(b.source.indexOf('futures')>=0?'FUTURES':(b.source.indexOf('spot')>=0?'SPOT':'BOOK')):'CONNECTING';
    var acct=el.querySelector('[data-z47-account]'); if(acct) acct.innerHTML=accountLine(sym);
    var bk=el.querySelector('[data-z47-book]'); if(bk) bk.innerHTML=renderRows(sym,b);
    var foot=el.querySelector('[data-z47-foot]'); if(foot) foot.innerHTML=renderFoot(sym,b);
  }
  function renderAll(){ SYMBOLS.forEach(renderSymbol); }

  function insideAdvanced(el){
    var p=el;
    for(var i=0; p && i<6; i++, p=p.parentElement){
      var t=(p.innerText||'').slice(0,1800);
      if(/Advanced\s+ZEL\s+stack|ZEL\s+DECISION\s+STACK|LIVE\s*\/\s*REAL/i.test(t)) return true;
    }
    return false;
  }
  function scoreCard(el, sym){
    if(!el || el.nodeType!==1) return null;
    if(el.closest('[data-zel-v47-card="1"]')) return null;
    if(insideAdvanced(el)) return null;
    var r=el.getBoundingClientRect();
    if(r.width<130 || r.height<80 || r.width>900 || r.height>760) return null;
    var txt=(el.innerText||'').trim();
    if(txt.indexOf(sym)<0) return null;
    if(txt.length>1800) return null;
    if(/CURRENT\s+ZEL\s+OPERATING\s+CONCLUSION|ADVISOR\s+MICRO\s+STRIP|EVIDENCE\s+SUMMARY/i.test(txt)) return null;
    var area=r.width*r.height;
    return {el:el, area:area, len:txt.length};
  }
  function bestCardFor(sym){
    var all = Array.prototype.slice.call(document.querySelectorAll('article,section,div,li'));
    var scored=[];
    for(var i=0;i<all.length;i++){ var s=scoreCard(all[i],sym); if(s) scored.push(s); }
    scored.sort(function(a,b){ return a.area-b.area || a.len-b.len; });
    return scored.length?scored[0].el:null;
  }
  function patchCards(){
    SYMBOLS.forEach(function(sym){
      var existing=document.querySelector('[data-zel-v47-card="1"][data-z47-symbol="'+sym+'"]');
      if(existing){ cards[sym]=existing; return; }
      var old=document.querySelector('[data-zel-v46-card="1"][data-z46-symbol="'+sym+'"],[data-zel-v43-card="1"][data-z43-symbol="'+sym+'"]');
      var card=old || bestCardFor(sym);
      if(!card) return;
      card.setAttribute('data-zel-v47-card','1');
      card.setAttribute('data-z47-symbol',sym);
      card.removeAttribute('data-zel-v46-card'); card.removeAttribute('data-z46-symbol');
      card.innerHTML = template(sym);
      cards[sym]=card;
      renderSymbol(sym);
    });
  }

  function advancedTemplate(){
    var b=book.BTCUSDT, lp=account.live.per.BTCUSDT||{}, vp=account.virtual.per.BTCUSDT||{};
    return '<div class="z47-adv-clean">'
      + '<div class="z47-adv-head"><span>LIVE / REAL</span><b>exchange visual · read-only</b></div>'
      + '<div class="z47-adv-price"><span>BTCUSDT</span><strong>'+ (b && b.last ? fmtPrice('BTCUSDT', b.last) : 'live pending') +'</strong></div>'
      + '<div class="z47-adv-grid">'
      + '<div><label>LIVE POS</label><b>'+compact(lp.pos,'%')+'</b></div>'
      + '<div><label>LIVE LEV</label><b>'+compact(lp.lev,'x')+'</b></div>'
      + '<div><label>VIRTUAL EQUITY</label><b>'+compact(account.virtual.equity,' USDT')+'</b></div>'
      + '<div><label>VIRTUAL POS</label><b>'+compact(vp.pos,'%')+'</b></div>'
      + '<div><label>ORDER</label><b>read-only</b></div>'
      + '<div><label>PROOF</label><b>CF/GS required</b></div>'
      + '</div>'
      + '<p>Exchange orderbook/price is live visual feed only. ZEL action remains DATA HOLD until CF/GS proof passes.</p>'
      + '</div>';
  }
  function normalizeAdvancedStack(){
    var nodes=Array.prototype.slice.call(document.querySelectorAll('article,section,div'));
    var cand=[];
    nodes.forEach(function(el){
      if(el.closest('[data-zel-v47-card="1"]')) return;
      var txt=(el.innerText||'').trim();
      if(!/LIVE\s*\/\s*REAL/i.test(txt)) return;
      if(!/DATA\s+HOLD|source-bound|required|read-only/i.test(txt)) return;
      var r=el.getBoundingClientRect();
      if(r.width<150 || r.height<100 || r.width>900 || r.height>900) return;
      cand.push({el:el, area:r.width*r.height, len:txt.length});
    });
    cand.sort(function(a,b){ return a.area-b.area || a.len-b.len; });
    if(!cand.length) return;
    var target=cand[0].el;
    if(target.getAttribute('data-z47-adv-clean')==='1') return;
    target.setAttribute('data-z47-adv-clean','1');
    target.innerHTML=advancedTemplate();
  }
  function renderAdvancedPanel(){
    var target=document.querySelector('[data-z47-adv-clean="1"]');
    if(target) target.innerHTML=advancedTemplate();
  }

  function killLegacyFloating(){
    var nodes=Array.prototype.slice.call(document.body ? document.body.querySelectorAll('body *') : []);
    nodes.forEach(function(el){
      if(el.closest('[data-zel-v47-card="1"]') || el.closest('[data-z47-adv-clean="1"]')) return;
      var cs; try{ cs=getComputedStyle(el); }catch(e){ return; }
      if(cs.position!=='fixed' && cs.position!=='sticky') return;
      var txt=(el.innerText||'').trim();
      if(/SOURCE\s+(BOUND|HOLD)|age_ms|missing:price|V3[4-9]|V4[0-6]/i.test(txt)){
        try{ el.remove(); }catch(e){ el.style.display='none'; }
      }
    });
  }

  function start(){
    patchCards();
    normalizeAdvancedStack();
    killLegacyFloating();
    connectWS('futures');
    pollCF();
    setInterval(function(){ patchCards(); normalizeAdvancedStack(); killLegacyFloating(); renderAll(); }, 1200);
    var mo=new MutationObserver(function(){ patchCards(); normalizeAdvancedStack(); killLegacyFloating(); });
    if(document.body) mo.observe(document.body,{childList:true,subtree:true});
  }
  if(document.readyState==='loading') document.addEventListener('DOMContentLoaded',start,{once:true}); else start();
})();
