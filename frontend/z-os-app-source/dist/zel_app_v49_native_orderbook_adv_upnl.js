/* ZEL APP V49 native orderbook + compact Advanced ZEL stack with uPNL.
 * App-only runtime. No nginx/caddy/systemd/server-route mutation.
 * Replaces older v4x app runtimes on install; fetches exchange live feed directly in browser.
 */
(function(){
  'use strict';
  if (window.__ZEL_APP_V49_NATIVE_ORDERBOOK_ADV_UPNL__) return;
  window.__ZEL_APP_V49_NATIVE_ORDERBOOK_ADV_UPNL__ = true;

  var VER='v49';
  var SYMBOLS=['BTCUSDT','ETHUSDT','SOLUSDT','XRPUSDT','LINKUSDT'];
  var FUTURES_WS='wss://fstream.binance.com/stream?streams='+SYMBOLS.map(function(s){return s.toLowerCase()+'@depth5@100ms';}).join('/');
  var SPOT_WS='wss://stream.binance.com:9443/stream?streams='+SYMBOLS.map(function(s){return s.toLowerCase()+'@depth5@100ms';}).join('/');
  var FUTURES_REST='https://fapi.binance.com/fapi/v1/depth?limit=10&symbol=';
  var SPOT_REST='https://api.binance.com/api/v3/depth?limit=10&symbol=';
  var CF_URLS=[
    'https://lico-canonical-signed-snapshot.tv-sign-proxy.workers.dev/snapshot',
    'https://alimi.z-os.vip/snapshot',
    'https://app.z-os.vip/zel_source_envelope_live.json',
    'https://app.z-os.vip/static/alimi_today_state_latest.json',
    'https://app.z-os.vip/zel_live_normalized.json'
  ];

  var book={}, cards={}, ws=null, reconnectTimer=null, wsMode='futures', lastAnyTick=0;
  var account={
    sourceTs:0, proof:'pending', hash:'pending', source:'exchange',
    live:{wallet:null, available:null, upnl:null, pnlPct:null, per:{}},
    virtual:{equity:null, balance:null, upnl:null, pnlPct:null, dd:null, per:{}}
  };
  SYMBOLS.forEach(function(s){ book[s]={ok:false, asks:[], bids:[], last:null, prev:null, mid:null, spread:null, ts:0, ticks:0, source:'wait', err:null}; account.live.per[s]={}; account.virtual.per[s]={}; });

  function n(v){ if(v===null||v===undefined||v==='') return null; if(typeof v==='string') v=v.replace(/[%,$x ]/g,''); var x=Number(v); return Number.isFinite(x)?x:null; }
  function isObj(o){ return o && typeof o==='object' && !Array.isArray(o); }
  function arrify(v){ return Array.isArray(v)?v:(v?[v]:[]); }
  function pick(o, keys){ if(!o) return null; for(var i=0;i<keys.length;i++){ var k=keys[i]; if(o[k]!==undefined && o[k]!==null && o[k] !== '') return o[k]; } return null; }
  function esc(s){ return String(s==null?'':s).replace(/[&<>"']/g,function(c){return {'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c];}); }
  function fmtPrice(sym,x){ x=n(x); if(x===null) return '—'; var d=sym==='BTCUSDT'?1:(sym==='ETHUSDT'?1:(sym==='SOLUSDT'?3:(sym==='LINKUSDT'?3:4))); return x.toLocaleString('en-US',{minimumFractionDigits:d,maximumFractionDigits:d}); }
  function fmtQty(q){ q=n(q); if(q===null) return '—'; if(Math.abs(q)>=1000) return (q/1000).toFixed(q>=10000?1:2)+'K'; if(Math.abs(q)>=100) return q.toFixed(0); if(Math.abs(q)>=10) return q.toFixed(2).replace(/\.00$/,''); return q.toFixed(3).replace(/0+$/,'').replace(/\.$/,''); }
  function compact(v,suf){ v=n(v); if(v===null) return '—'; var abs=Math.abs(v), s; if(abs>=1000000) s=(v/1000000).toFixed(2)+'M'; else if(abs>=1000) s=(v/1000).toFixed(2)+'K'; else if(abs>=100) s=v.toFixed(1); else if(abs>=10) s=v.toFixed(2).replace(/0+$/,'').replace(/\.$/,''); else s=v.toFixed(3).replace(/0+$/,'').replace(/\.$/,''); return s+(suf||''); }
  function pnlText(val,pct){ var v=n(val), p=n(pct); if(v!==null){ var sign=v>0?'+':''; return sign+compact(v,'U'); } if(p!==null){ var sign2=p>0?'+':''; return sign2+compact(p,'%'); } return '—'; }

  function normalizeDepth(sym, asks, bids, src){
    if(!sym || SYMBOLS.indexOf(sym)<0) return;
    asks=arrify(asks).map(function(r){ return {p:n(r.p!==undefined?r.p:r[0]), q:n(r.q!==undefined?r.q:r[1])}; }).filter(function(r){return r.p!==null && r.q!==null;}).sort(function(a,b){return a.p-b.p;}).slice(0,5);
    bids=arrify(bids).map(function(r){ return {p:n(r.p!==undefined?r.p:r[0]), q:n(r.q!==undefined?r.q:r[1])}; }).filter(function(r){return r.p!==null && r.q!==null;}).sort(function(a,b){return b.p-a.p;}).slice(0,5);
    if(!asks.length || !bids.length) return;
    var b=book[sym], bid=bids[0].p, ask=asks[0].p, mid=(bid+ask)/2;
    b.prev = b.last || mid; b.last=mid; b.mid=mid; b.spread=ask-bid; b.asks=asks; b.bids=bids; b.ok=true; b.source=src||'exchange-ws'; b.ts=Date.now(); b.ticks++; b.err=null; lastAnyTick=Date.now();
    renderSymbol(sym); renderAdvanced();
  }
  function connectWS(mode){
    try{ if(ws) ws.close(); }catch(e){}
    wsMode=mode||wsMode||'futures'; var url=wsMode==='spot'?SPOT_WS:FUTURES_WS;
    try{ ws=new WebSocket(url); }catch(e){ fallbackRest(); return; }
    ws.onmessage=function(ev){ try{ var msg=JSON.parse(ev.data), d=msg.data||msg; var sym=String(d.s||'').toUpperCase(); if(SYMBOLS.indexOf(sym)<0) return; normalizeDepth(sym,d.a||d.asks,d.b||d.bids,wsMode==='spot'?'binance-spot-ws':'binance-futures-ws'); }catch(e){} };
    ws.onerror=function(){ scheduleReconnect(); };
    ws.onclose=function(){ scheduleReconnect(); };
    setTimeout(function(){ if(Date.now()-lastAnyTick>5000){ if(wsMode==='futures') connectWS('spot'); else fallbackRest(); } },5500);
  }
  function scheduleReconnect(){ clearTimeout(reconnectTimer); reconnectTimer=setTimeout(function(){ connectWS(wsMode==='futures'?'spot':'futures'); },2500); }
  function fallbackRest(){
    SYMBOLS.forEach(function(sym,idx){ (function poll(){
      fetch(FUTURES_REST+sym,{cache:'no-store',mode:'cors'}).then(function(r){return r.ok?r.json():Promise.reject(r.status);})
      .catch(function(){return fetch(SPOT_REST+sym,{cache:'no-store',mode:'cors'}).then(function(r){return r.ok?r.json():Promise.reject(r.status);});})
      .then(function(j){ normalizeDepth(sym,j.asks,j.bids,'binance-rest'); })
      .catch(function(e){ book[sym].err=String(e||'fetch'); renderSymbol(sym); })
      .finally(function(){ setTimeout(poll,1200+idx*130); });
    })(); });
  }

  function applyPerSymbol(target,sym,obj,src){
    if(!target||!sym||SYMBOLS.indexOf(sym)<0||!isObj(obj)) return;
    var slot=target.per[sym]||(target.per[sym]={});
    var pos=pick(obj,['pos_pct','pos%','position_pct','position_percent','positionPct','pos','position','size_pct','sizePct']);
    var lev=pick(obj,['lev','leverage','leverage_x','leverageX']);
    var liq=pick(obj,['liq_buffer_pct','liq_buffer%','liqBufferPct','liq_buffer','liquidation_buffer_pct']);
    var upnl=pick(obj,['upnl','uPNL','unrealized_pnl','unrealizedPnl','unrealizedProfit','pnl_usdt','pnl','live_pnl','virtual_asset_pnl']);
    var upnlPct=pick(obj,['upnl_pct','uPNL_pct','pnl_pct','pnl%','roe','ROE','unrealized_pnl_pct']);
    if(pos!==null) slot.pos=n(pos); if(lev!==null) slot.lev=n(lev); if(liq!==null) slot.liq=n(liq); if(upnl!==null) slot.upnl=n(upnl); if(upnlPct!==null) slot.upnlPct=n(upnlPct);
    var eq=pick(obj,['equity','equity_usdt','virtual_equity_usdt','balance','current_balance_usdt']); if(eq!==null) slot.eq=n(eq);
    if(pos!==null||lev!==null||liq!==null||upnl!==null||upnlPct!==null||eq!==null) slot.src=src||'cf';
  }
  function parsePayload(j){
    if(!j) return; account.sourceTs=Date.now(); account.proof='pending'; account.hash='pending'; account.source='cf/gs';
    var roots=[]; function add(o){ if(isObj(o)&&roots.indexOf(o)<0) roots.push(o); }
    add(j); add(j.payload); add(j.data); add(j.alimi); add(j.trade_state); add(j.risk); add(j.live_account); add(j.virtual_account); add(j.account);
    roots.slice().forEach(function(o){ add(o&&o.payload); add(o&&o.data); add(o&&o.trade_state); add(o&&o.risk); add(o&&o.live_account); add(o&&o.virtual_account); });
    var la=j.live_account||(j.payload&&j.payload.live_account)||(j.data&&j.data.live_account)||(j.account&&j.account.live)||{};
    var va=j.virtual_account||(j.payload&&j.payload.virtual_account)||(j.data&&j.data.virtual_account)||(j.account&&j.account.virtual)||{};
    account.live.wallet=n(pick(la,['wallet_balance','walletBalance','totalWalletBalance','balance','equity','account_equity']));
    account.live.available=n(pick(la,['availableBalance','available_balance','available','free']));
    account.live.upnl=n(pick(la,['upnl','uPNL','unrealized_pnl','unrealizedPnl','unrealizedProfit','pnl']));
    account.live.pnlPct=n(pick(la,['pnl_pct','upnl_pct','roe','ROE']));
    account.virtual.equity=n(pick(va,['virtual_equity_usdt','equity_usdt','equity','current_balance_usdt','balance']));
    account.virtual.balance=n(pick(va,['current_balance_usdt','balance','current_balance']));
    account.virtual.upnl=n(pick(va,['upnl','uPNL','virtual_asset_pnl','pnl','unrealized_pnl']));
    account.virtual.pnlPct=n(pick(va,['virtual_pnl_pct','pnl_pct','upnl_pct','roe']));
    account.virtual.dd=n(pick(va,['DD_day_pct','DD_day','dd_day_pct','drawdown_day_pct','DD_total_pct','drawdown_pct']));
    account.proof=String(pick(j,['proof','proof_state','cf_gs_proof','receipt_state'])||account.proof).toLowerCase();
    account.hash=String(pick(j,['source_hash','receipt_hash','hash'])||account.hash).toLowerCase();
    roots.forEach(function(o){
      if(!isObj(o)) return;
      var sym=String(pick(o,['symbol','sym','ticker'])||'').toUpperCase();
      if(SYMBOLS.indexOf(sym)>=0){ applyPerSymbol(account.live,sym,o,'cf'); if(o.virtual||o.paper||o.route==='virtual') applyPerSymbol(account.virtual,sym,o,'cf'); }
      ['positions','position','live_positions','livePositions','symbols','market_cards','cards','trade_states'].forEach(function(k){ arrify(o&&o[k]).forEach(function(p){ var ps=String(p&&(p.symbol||p.sym||p.ticker||p.name)||'').toUpperCase(); applyPerSymbol(account.live,ps,p,'cf'); }); });
      ['virtual_positions','paper_positions','virtualPositions','paperPositions'].forEach(function(k){ arrify(o&&o[k]).forEach(function(p){ var ps=String(p&&(p.symbol||p.sym||p.ticker||p.name)||'').toUpperCase(); applyPerSymbol(account.virtual,ps,p,'cf'); }); });
    });
    var flat=j.payload||j.data||j; if(isObj(flat)){ var fs=String(pick(flat,['symbol','sym'])||'').toUpperCase(); if(!fs && n(pick(flat,['pos_pct','pos%','pos']))!==null) fs='BTCUSDT'; if(SYMBOLS.indexOf(fs)>=0) applyPerSymbol(account.live,fs,flat,'cf'); var price=n(pick(flat,['price','last_price','mark_price'])); if(price!==null&&fs&&SYMBOLS.indexOf(fs)>=0&&!book[fs].ok){ var b=book[fs]; b.prev=b.last||price; b.last=price; b.mid=price; b.source='cf-price'; b.ts=Date.now(); } }
  }
  function fetchJson(url){ return fetch(url+(url.indexOf('?')>=0?'&':'?')+'v='+Date.now(),{cache:'no-store',mode:'cors'}).then(function(r){ return r.ok?r.text():Promise.reject(r.status); }).then(function(txt){ txt=String(txt||'').trim(); if(!txt||txt.charAt(0)==='<') throw new Error('non-json'); return JSON.parse(txt); }); }
  function pollCF(){ var chain=Promise.reject('start'); CF_URLS.forEach(function(url){ chain=chain.catch(function(){ return fetchJson(url); }); }); chain.then(parsePayload).catch(parseDomMetrics).finally(function(){ renderAll(); renderAdvanced(); setTimeout(pollCF,1700); }); }
  function parseDomMetrics(){
    var t=(document.body&&document.body.innerText)||'', o={symbol:'BTCUSDT'};
    var m=t.match(/pos(?:%|_pct)?\s*[:= ]\s*([0-9.]+)/i); if(m) o.pos_pct=n(m[1]);
    m=t.match(/lev\s*[:= ]\s*([0-9.]+)/i); if(m) o.lev=n(m[1]);
    m=t.match(/liq[_ ]?buffer(?:%|_pct)?\s*[:= ]\s*([0-9.]+)/i); if(m) o.liq_buffer_pct=n(m[1]);
    m=t.match(/u?pnl\s*[:= ]\s*(-?[0-9.]+)/i); if(m) o.upnl=n(m[1]);
    applyPerSymbol(account.live,'BTCUSDT',o,'dom');
  }

  function accountLine(sym){
    var lp=account.live.per[sym]||{}, vp=account.virtual.per[sym]||{};
    return '<div class="z49-account">'
      + '<span class="z49-mini live">POS '+compact(lp.pos,'%')+'</span>'
      + '<span class="z49-mini live">LEV '+compact(lp.lev,'x')+'</span>'
      + '<span class="z49-mini live">uPNL '+pnlText(lp.upnl,lp.upnlPct)+'</span>'
      + '<span class="z49-mini virt">V.POS '+compact(vp.pos,'%')+'</span>'
      + '<span class="z49-mini virt">V.LEV '+compact(vp.lev,'x')+'</span>'
      + '<span class="z49-mini virt">V.uPNL '+pnlText(vp.upnl, vp.upnlPct)+'</span>'
      + '</div>';
  }
  function template(sym){ return '<div class="z49-card" data-z49-sym="'+sym+'"><div class="z49-head"><div class="z49-sym">'+sym+'</div><div class="z49-venue" data-z49-venue>CONNECTING</div></div><div class="z49-priceLine"><div class="z49-price" data-z49-price>loading</div><div class="z49-move flat" data-z49-move>0.000%</div></div><div data-z49-account>'+accountLine(sym)+'</div><div class="z49-book" data-z49-book></div><div class="z49-foot" data-z49-foot></div></div>'; }
  function pctMove(b){ if(!b.last||!b.prev||b.prev===0) return {txt:'0.000%',cls:'flat'}; var p=((b.last-b.prev)/b.prev)*100; return {txt:(p>0?'+':'')+p.toFixed(3)+'%', cls:p>0?'up':(p<0?'down':'flat')}; }
  function renderRows(sym,b){
    if(!b.ok){ return '<div class="z49-row ask"><span>ask —</span><span class="qty">—</span></div><div class="z49-row ask"><span>ask —</span><span class="qty">—</span></div><div class="z49-row ask"><span>ask —</span><span class="qty">—</span></div><div class="z49-mid"><span class="last">waiting live orderbook</span><span class="spread">spr —</span></div><div class="z49-row bid"><span>bid —</span><span class="qty">—</span></div><div class="z49-row bid"><span>bid —</span><span class="qty">—</span></div><div class="z49-row bid"><span>bid —</span><span class="qty">—</span></div>'; }
    var all=b.asks.concat(b.bids), maxq=1; all.forEach(function(r){ if(r.q>maxq) maxq=r.q; });
    function row(r,cls){ var w=maxq?Math.max(3,Math.min(100,(r.q/maxq)*100)):0; return '<div class="z49-row '+cls+'" style="--w:'+w.toFixed(1)+'%"><span>'+fmtPrice(sym,r.p)+'</span><span class="qty">'+fmtQty(r.q)+'</span></div>'; }
    return b.asks.slice().reverse().map(function(r){return row(r,'ask');}).join('') + '<div class="z49-mid"><span class="last">'+fmtPrice(sym,b.last)+'</span><span class="spread">spr '+fmtPrice(sym,b.spread)+'</span></div>' + b.bids.slice(0,5).map(function(r){return row(r,'bid');}).join('');
  }
  function renderFoot(sym,b){ return '<span class="z49-pill lock">ORDER RO</span><span class="z49-pill">ticks '+(b.ticks||0)+'</span>'; }
  function renderSymbol(sym){ var el=cards[sym]; if(!el||!el.isConnected) return; var b=book[sym]; var price=el.querySelector('[data-z49-price]'); if(price) price.textContent=b.ok?fmtPrice(sym,b.last):(b.last?fmtPrice(sym,b.last):'live pending'); var mv=pctMove(b), move=el.querySelector('[data-z49-move]'); if(move){ move.textContent=mv.txt; move.className='z49-move '+mv.cls; } var venue=el.querySelector('[data-z49-venue]'); if(venue) venue.textContent=b.ok?'LIVE '+(b.source.indexOf('futures')>=0?'FUTURES':(b.source.indexOf('spot')>=0?'SPOT':'BOOK')):'CONNECTING'; var acct=el.querySelector('[data-z49-account]'); if(acct) acct.innerHTML=accountLine(sym); var bk=el.querySelector('[data-z49-book]'); if(bk) bk.innerHTML=renderRows(sym,b); var foot=el.querySelector('[data-z49-foot]'); if(foot) foot.innerHTML=renderFoot(sym,b); }
  function renderAll(){ SYMBOLS.forEach(renderSymbol); }

  function inAdvanced(el){ var p=el; for(var i=0;p&&i<7;i++,p=p.parentElement){ var t=(p.innerText||'').slice(0,900); if(/Advanced\s+ZEL\s+stack|ZEL\s+DECISION\s+STACK|LIVE\s*\/\s*REAL/i.test(t)) return true; } return false; }
  function scoreCard(el,sym){ if(!el||el.nodeType!==1) return null; if(el.closest('[data-zel-v49-card="1"]')) return null; if(inAdvanced(el)) return null; var r=el.getBoundingClientRect(); if(r.width<130||r.height<80||r.width>900||r.height>760) return null; var txt=(el.innerText||'').trim(); if(txt.indexOf(sym)<0) return null; if(txt.length>1800) return null; if(/CURRENT\s+ZEL\s+OPERATING\s+CONCLUSION|ADVISOR\s+MICRO\s+STRIP|EVIDENCE\s+SUMMARY/i.test(txt)) return null; return {el:el,area:r.width*r.height,len:txt.length}; }
  function bestCardFor(sym){ var all=Array.prototype.slice.call(document.querySelectorAll('article,section,div,li')); var scored=[]; for(var i=0;i<all.length;i++){ var s=scoreCard(all[i],sym); if(s) scored.push(s); } scored.sort(function(a,b){return a.area-b.area||a.len-b.len;}); return scored.length?scored[0].el:null; }
  function patchCards(){ SYMBOLS.forEach(function(sym){ var existing=document.querySelector('[data-zel-v49-card="1"][data-z49-symbol="'+sym+'"]'); if(existing){ cards[sym]=existing; return; } var old=document.querySelector('[data-zel-v47-card="1"][data-z47-symbol="'+sym+'"],[data-zel-v46-card="1"][data-z46-symbol="'+sym+'"],[data-zel-v43-card="1"][data-z43-symbol="'+sym+'"]'); var card=old||bestCardFor(sym); if(!card) return; card.setAttribute('data-zel-v49-card','1'); card.setAttribute('data-z49-symbol',sym); ['data-zel-v47-card','data-z47-symbol','data-zel-v46-card','data-z46-symbol','data-zel-v43-card','data-z43-symbol'].forEach(function(a){card.removeAttribute(a);}); card.innerHTML=template(sym); cards[sym]=card; renderSymbol(sym); }); }

  function findAdvancedRoot(){
    var all=Array.prototype.slice.call(document.querySelectorAll('article,section,div'));
    var scored=[];
    all.forEach(function(el){
      if(el.closest('[data-zel-v49-card="1"]')) return;
      var txt=(el.innerText||'').trim();
      if(!/Advanced\s+ZEL\s+stack/i.test(txt)) return;
      var r=el.getBoundingClientRect();
      if(r.width<240||r.width>900||r.height<60||r.height>1400) return;
      var hasBody=/ZEL\s+DECISION\s+STACK|LIVE\s*\/\s*REAL|Virtual\s*\/\s*Strategy|BingX\s+paper|Guard/i.test(txt);
      scored.push({el:el, area:r.width*r.height, len:txt.length, body:hasBody?0:1});
    });
    scored.sort(function(a,b){ return a.body-b.body || a.area-b.area || a.len-b.len; });
    return scored.length?scored[0].el:null;
  }
  function advHtml(){
    var sym='BTCUSDT', b=book[sym], lp=account.live.per[sym]||{}, vp=account.virtual.per[sym]||{};
    var age = account.sourceTs ? (Date.now()-account.sourceTs) : null;
    var feed = b && b.ok ? 'exchange=live' : 'exchange=waiting';
    var proof = account.proof && account.proof!=='pending' ? account.proof : 'proof=pending';
    var hash = account.hash && account.hash!=='pending' ? 'hash=bound' : 'hash=pending';
    return '<div class="z49-adv-wrap" data-zel-v49-adv="1">'
      + '<div class="z49-adv-title"><div><span>Advanced ZEL stack</span><small>live · virtual · guard</small></div><button type="button" data-z49-close>close</button></div>'
      + '<div class="z49-adv-status"><b>READ-ONLY HOLD</b><span>exchange feed는 시각·호가 전용, ZEL 최종 액션은 CF/GS proof 전까지 HOLD.</span></div>'
      + '<div class="z49-adv-grid">'
      + '<section class="live"><div class="k">LIVE / REAL <em>'+sym+'</em></div><strong>'+fmtPrice(sym,b&&b.last)+'</strong><div class="z49-adv-metrics"><span>pos <b>'+compact(lp.pos,'%')+'</b></span><span>lev <b>'+compact(lp.lev,'x')+'</b></span><span>uPNL <b>'+pnlText(lp.upnl,lp.upnlPct)+'</b></span><span>liq <b>'+compact(lp.liq,'%')+'</b></span></div></section>'
      + '<section class="virt"><div class="k">VIRTUAL / PAPER</div><strong>'+compact(account.virtual.equity,'U')+'</strong><div class="z49-adv-metrics"><span>v.pos <b>'+compact(vp.pos,'%')+'</b></span><span>v.lev <b>'+compact(vp.lev,'x')+'</b></span><span>v.uPNL <b>'+pnlText(vp.upnl,account.virtual.pnlPct)+'</b></span><span>DD <b>'+compact(account.virtual.dd,'%')+'</b></span></div></section>'
      + '<section class="guard"><div class="k">GUARD / ORDER</div><strong>ORDER RO · DATA HOLD</strong><div class="z49-adv-metrics"><span>order <b>read-only</b></span><span>action <b>hold</b></span><span>proof <b>pending</b></span><span>route <b>blocked</b></span></div></section>'
      + '<section class="feed"><div class="k">5-CARD LIVE FEED</div><strong>BTC · ETH · SOL · XRP · LINK</strong><div class="z49-adv-metrics"><span>cards <b>live book</b></span><span>orders <b>disabled</b></span><span>source <b>exchange</b></span><span>mode <b>visual</b></span></div></section>'
      + '</div>'
      + '<div class="z49-audit">'+feed+' · '+proof+' · '+hash+' · age '+(age===null?'—':age+'ms')+' · uPNL included</div>'
      + '</div>';
  }
  function renderAdvanced(){ return; }
  function killLegacyFloating(){
    var nodes=Array.prototype.slice.call(document.body?document.body.querySelectorAll('body *'):[]);
    nodes.forEach(function(el){
      if(el.closest('[data-zel-v49-card="1"]') || el.closest('[data-zel-v49-adv="1"]')) return;
      var cs; try{cs=getComputedStyle(el);}catch(e){return;} if(cs.position!=='fixed'&&cs.position!=='sticky') return;
      var txt=(el.innerText||'').trim(); if(/SOURCE\s+(BOUND|HOLD)|age_ms|missing:price|V3[4-9]|V4[0-8]/i.test(txt)){ try{el.remove();}catch(e){el.style.display='none';} }
    });
  }
  function start(){ patchCards(); renderAdvanced(); killLegacyFloating(); connectWS('futures'); pollCF(); setInterval(function(){ patchCards(); renderAdvanced(); killLegacyFloating(); renderAll(); },1200); var mo=new MutationObserver(function(){ patchCards(); renderAdvanced(); killLegacyFloating(); }); if(document.body) mo.observe(document.body,{childList:true,subtree:true}); }
  if(document.readyState==='loading') document.addEventListener('DOMContentLoaded',start,{once:true}); else start();
})();
