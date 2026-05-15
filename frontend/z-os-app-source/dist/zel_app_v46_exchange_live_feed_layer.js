/* ZEL APP V46 EXCHANGE LIVE FEED LAYER
 * App-only browser layer. No visible chart, no floating badge, no server/nginx/systemd mutation.
 * Purpose: subscribe to exchange live feed and make native market cards consume live symbol state.
 */
(function(){
  'use strict';
  var VERSION='V46_EXCHANGE_LIVE_FEED_LAYER_NO_VISIBLE_CHART';
  if (window.ZEL_APP_V46_LIVE_FEED && window.ZEL_APP_V46_LIVE_FEED.version===VERSION) return;

  var SYMBOLS=['BTCUSDT','ETHUSDT','SOLUSDT','XRPUSDT','LINKUSDT'];
  var WS_ENDPOINTS=[
    {name:'binance-futures-mark', url:function(){return 'wss://fstream.binance.com/stream?streams='+SYMBOLS.map(function(s){return s.toLowerCase()+'@markPrice@1s';}).join('/');},
      parse:function(raw){var d=raw&&raw.data?raw.data:raw; var sym=d&&d.s; var p=d&&(d.p||d.markPrice); var ts=d&&(d.E||d.T); return sym&&p?{symbol:sym,price:Number(p),ts:Number(ts||Date.now()),source:'binance-futures-mark'}:null;}},
    {name:'binance-spot-ticker', url:function(){return 'wss://stream.binance.com:9443/stream?streams='+SYMBOLS.map(function(s){return s.toLowerCase()+'@ticker';}).join('/');},
      parse:function(raw){var d=raw&&raw.data?raw.data:raw; var sym=d&&d.s; var p=d&&(d.c||d.w); var ts=d&&d.E; return sym&&p?{symbol:sym,price:Number(p),ts:Number(ts||Date.now()),source:'binance-spot-ticker'}:null;}}
  ];
  var REST_URLS=[
    {name:'binance-futures-premiumIndex', url:'https://fapi.binance.com/fapi/v1/premiumIndex', parse:function(j){return Array.isArray(j)?j.map(function(x){return {symbol:x.symbol,price:Number(x.markPrice),ts:Number(x.time||Date.now()),source:'binance-futures-rest'};}):[];}},
    {name:'binance-futures-ticker', url:'https://fapi.binance.com/fapi/v1/ticker/price', parse:function(j){return Array.isArray(j)?j.map(function(x){return {symbol:x.symbol,price:Number(x.price),ts:Number(x.time||Date.now()),source:'binance-futures-rest'};}):[];}}
  ];

  var state={};
  SYMBOLS.forEach(function(sym){state[sym]={symbol:sym,price:null,prev:null,delta:0,ts:0,age_ms:null,ticks:0,source:'none',ok:false,status:'BOOT'};});
  var ws=null, wsMode=0, reconnectDelay=1200, reconnectTimer=null, renderTimer=null, mountTimer=null, restTimer=null;

  window.ZEL_APP_V46_LIVE_FEED={
    version:VERSION,
    symbols:SYMBOLS.slice(),
    state:state,
    connect:connect,
    refresh:restPoll,
    render:renderAll,
    stop:function(){try{if(ws) ws.close();}catch(e){} clearTimeout(reconnectTimer); clearInterval(renderTimer); clearInterval(mountTimer); clearInterval(restTimer);}
  };

  function now(){return Date.now();}
  function text(el){return (el&&el.textContent||'').replace(/\s+/g,' ').trim();}
  function clamp(n,a,b){return Math.max(a,Math.min(b,n));}
  function fmtPrice(x){
    if(!isFinite(x)) return 'unbound';
    if(x>=1000) return Math.round(x).toLocaleString('en-US');
    if(x>=100) return x.toFixed(2);
    if(x>=1) return x.toFixed(4);
    return x.toPrecision(5);
  }
  function fmtDelta(x){if(!isFinite(x)) return 'Δ 0.000%'; return 'Δ '+(x>=0?'+':'')+x.toFixed(3)+'%';}
  function isNodeVisible(el){var r=el.getBoundingClientRect(); return r.width>20&&r.height>10;}

  function cleanupVisibleLegacy(){
    var selectors=[
      '.zel-v41-live-graph','.zel-v41-graph','.zel-v42-live-tick-chart','.zel-v42-tick-chart',
      '.zel-v43-live-layer','.zel-v43-card-live-pill','.zel-v44-live-layer','.zel-v44-card-live-pill',
      '.zel-v45-live-layer','.zel-v45-live-canvas-wrap','.zel-v45-live-meta','.zel-v45-live-head',
      '[data-zel-v41]','[data-zel-v42]','[data-zel-v43]','[data-zel-v44]','[data-zel-v45-live-card="child"]',
      '#zel-v41-live-graph','#zel-v42-live-tick-chart','#zel-v43-live-chart','#zel-v44-live-chart','#zel-v45-live-chart'
    ].join(',');
    document.querySelectorAll(selectors).forEach(function(n){try{n.remove();}catch(e){}});
    document.querySelectorAll('[class*="float"],[class*="badge"],[id*="float"],[id*="badge"]').forEach(function(n){
      var t=text(n); if(/SOURCE\s+(BOUND|HOLD)|missing:|age_ms|V3[4-9]|V4[0-5]/i.test(t)){try{n.remove();}catch(e){}}
    });
  }

  function scoreCard(el,sym){
    if(!el||!isNodeVisible(el)) return -9999;
    if(el.closest('.zel-v45-live-layer,.zel-v42-live-tick-chart,.zel-v43-live-layer,.zel-v44-live-layer')) return -9999;
    var t=text(el); if(t.indexOf(sym)<0) return -9999;
    if(/Operational Console|CURRENT ZEL OPERATING CONCLUSION|Decision proof|Advanced ZEL stack|Advisor|Evidence Summary/i.test(t)) return -9999;
    var r=el.getBoundingClientRect();
    if(r.width<150||r.height<80) return -9999;
    var sc=0;
    if(t.slice(0,80).indexOf(sym)>=0) sc+=10;
    if(/sig=read_only|sig-read|read_only/i.test(t)) sc+=7;
    if(/risk-hold|proof=missing|source-required|liq=unbound/i.test(t)) sc+=7;
    if(/unbound|source-bound/i.test(t)) sc+=5;
    sc+=clamp(12-Math.floor(t.length/150),-12,12);
    sc-=Math.floor(el.querySelectorAll('*').length/80);
    return sc;
  }
  function findCard(sym){
    var nodes=Array.prototype.slice.call(document.querySelectorAll('article,section,main div,div'));
    var best=null, bestScore=-9999;
    nodes.forEach(function(el){var s=scoreCard(el,sym); if(s>bestScore){bestScore=s; best=el;}});
    return bestScore>0?best:null;
  }
  function candidatesInCard(card){
    return Array.prototype.slice.call(card.querySelectorAll('h1,h2,h3,h4,strong,b,span,div,p')).filter(function(n){
      if(!isNodeVisible(n)) return false;
      var t=text(n);
      if(!/^(unbound|source-bound|source bound|DATA HOLD|SOURCE HOLD|SOURCE BOUND)$/i.test(t)) return false;
      if(/risk-hold|proof=missing|source-required|liq=unbound|receipt_hash/i.test(t)) return false;
      var r=n.getBoundingClientRect();
      if(r.width<25||r.height<12) return false;
      return true;
    });
  }
  function pickStatusNode(card){
    var existing=card.querySelector('[data-zel-v46-native-status="1"]'); if(existing) return existing;
    var arr=candidatesInCard(card);
    if(!arr.length) return null;
    arr.sort(function(a,b){
      var sa=parseFloat(getComputedStyle(a).fontSize||'0')+(a.getBoundingClientRect().top<card.getBoundingClientRect().top+100?8:0);
      var sb=parseFloat(getComputedStyle(b).fontSize||'0')+(b.getBoundingClientRect().top<card.getBoundingClientRect().top+100?8:0);
      return sb-sa;
    });
    var n=arr[0];
    n.setAttribute('data-zel-v46-native-status','1');
    n.setAttribute('data-zel-v46-original-text',text(n));
    return n;
  }
  function ensureNativeLine(card){
    var line=card.querySelector('[data-zel-v46-native-line="1"]');
    if(line) return line;
    line=document.createElement('div');
    line.setAttribute('data-zel-v46-native-line','1');
    line.className='zel-v46-native-line';
    line.textContent='LIVE FEED waiting';
    var status=pickStatusNode(card);
    if(status&&status.parentNode){status.insertAdjacentElement('afterend',line);} else {card.insertBefore(line,card.firstChild);}
    return line;
  }
  function mountCard(sym){
    var card=findCard(sym); if(!card) return null;
    card.setAttribute('data-zel-v46-live-card','1');
    card.setAttribute('data-zel-v46-symbol',sym);
    card.classList.add('zel-v46-native-feed-card');
    pickStatusNode(card);
    ensureNativeLine(card);
    return card;
  }
  function mountAll(){cleanupVisibleLegacy(); SYMBOLS.forEach(mountCard);}

  function ingest(t){
    if(!t||SYMBOLS.indexOf(t.symbol)<0||!isFinite(t.price)||t.price<=0) return;
    var s=state[t.symbol], old=s.price;
    s.prev=old; s.price=t.price; s.ts=Number(t.ts||now()); s.age_ms=Math.max(0,now()-s.ts); s.ticks+=1; s.source=t.source||s.source; s.ok=true; s.status='LIVE';
    if(isFinite(old)&&old>0) s.delta=((t.price-old)/old)*100;
    window.dispatchEvent(new CustomEvent('zel:exchange-live-tick',{detail:{version:VERSION,symbol:t.symbol,state:Object.assign({},s)}}));
  }
  async function seedCf(){
    try{
      var r=await fetch('/zel_source_envelope_live.json?v='+now(),{cache:'no-store'}); if(!r.ok) return;
      var j=await r.json(), p=j.payload||j, sym=p.symbol||p.symbol_usdt||'BTCUSDT';
      var price=Number(p.price||p.mark_price||p.last_price||p.price_usdt); var ts=Number(p.source_ts_ms||p.ts_ms||p.updated_ts||now());
      ingest({symbol:sym,price:price,ts:ts,source:'cf-seed'});
    }catch(e){}
  }
  async function restPoll(){
    for(var i=0;i<REST_URLS.length;i++){
      try{
        var ep=REST_URLS[i]; var r=await fetch(ep.url+'?v='+now(),{cache:'no-store',mode:'cors'}); if(!r.ok) continue;
        var arr=ep.parse(await r.json()).filter(function(x){return SYMBOLS.indexOf(x.symbol)>=0&&isFinite(x.price);});
        if(arr.length){arr.forEach(ingest); return true;}
      }catch(e){}
    }
    return false;
  }
  function connect(){
    try{if(ws) ws.close();}catch(e){}
    clearTimeout(reconnectTimer);
    var ep=WS_ENDPOINTS[wsMode%WS_ENDPOINTS.length]; wsMode++;
    try{ws=new WebSocket(ep.url());}catch(e){scheduleReconnect(); return;}
    ws.onopen=function(){reconnectDelay=1200; Object.keys(state).forEach(function(k){if(!state[k].ok) state[k].status='WAIT';});};
    ws.onmessage=function(ev){try{ingest(ep.parse(JSON.parse(ev.data)));}catch(e){}};
    ws.onerror=function(){Object.keys(state).forEach(function(k){if(!state[k].ok) state[k].status='WS_ERR';});};
    ws.onclose=function(){scheduleReconnect();};
  }
  function scheduleReconnect(){clearTimeout(reconnectTimer); reconnectTimer=setTimeout(connect,reconnectDelay); reconnectDelay=Math.min(15000,Math.floor(reconnectDelay*1.65));}

  function renderCard(sym,card){
    var s=state[sym]; if(!s) return;
    var age=s.ts?Math.max(0,now()-s.ts):null; s.age_ms=age;
    var live=s.price&&age!==null&&age<15000;
    card=card||findCard(sym); if(!card) return;
    card.setAttribute('data-zel-live-source',s.source||'none');
    card.setAttribute('data-zel-live-price',s.price||'');
    card.setAttribute('data-zel-live-age-ms',age===null?'':String(age));
    card.setAttribute('data-zel-live-ticks',String(s.ticks||0));
    var status=pickStatusNode(card);
    if(status){
      status.textContent=live ? fmtPrice(s.price) : (s.ticks?'stale':'unbound');
      status.classList.add('zel-v46-native-price');
      status.classList.toggle('zel-v46-live-ok',!!live);
      status.classList.toggle('zel-v46-live-wait',!live);
    }
    var line=ensureNativeLine(card);
    if(line){
      line.textContent=(live?'LIVE ':'WAIT ') + (s.source||'feed') + ' · ' + fmtDelta(s.delta||0) + ' · ticks ' + (s.ticks||0) + (age!==null?' · age '+age+'ms':'');
      line.classList.toggle('zel-v46-live-ok',!!live);
      line.classList.toggle('zel-v46-live-wait',!live);
    }
  }
  function renderAll(){cleanupVisibleLegacy(); SYMBOLS.forEach(function(sym){var c=mountCard(sym); if(c) renderCard(sym,c);});}

  function boot(){
    mountAll(); seedCf(); restPoll(); connect();
    mountTimer=setInterval(mountAll,2500);
    renderTimer=setInterval(renderAll,500);
    restTimer=setInterval(function(){seedCf(); restPoll();},5000);
  }
  if(document.readyState==='loading') document.addEventListener('DOMContentLoaded',boot,{once:true}); else boot();
})();
