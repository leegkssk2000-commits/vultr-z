/* ZEL APP V47 native market-card live sparkline
 * App-only browser runtime. No server/nginx/caddy/systemd mutation. No nested visible panels, no floating badges.
 * Purpose: live exchange feed layer -> existing market cards render native rolling sparkline only.
 */
(function(){
  'use strict';
  var VERSION='V47_NATIVE_MARKET_CARD_LIVE_SPARKLINE_APP_ONLY';
  if (window.ZEL_APP_V47_LIVE_FEED && window.ZEL_APP_V47_LIVE_FEED.version===VERSION) return;

  var SYMBOLS=['BTCUSDT','ETHUSDT','SOLUSDT','XRPUSDT','LINKUSDT'];
  var MAX_POINTS=120;
  var STALE_MS=15000;
  var WS_ENDPOINTS=[
    {name:'binance-futures-mark', url:function(){return 'wss://fstream.binance.com/stream?streams='+SYMBOLS.map(function(s){return s.toLowerCase()+'@markPrice@1s';}).join('/');}, parse:function(raw){var d=raw&&raw.data?raw.data:raw; var sym=d&&d.s; var p=d&&(d.p||d.markPrice); var ts=d&&(d.E||d.T); return sym&&p?{symbol:sym,price:Number(p),ts:Number(ts||Date.now()),source:'binance-futures-mark'}:null;}},
    {name:'binance-spot-ticker', url:function(){return 'wss://stream.binance.com:9443/stream?streams='+SYMBOLS.map(function(s){return s.toLowerCase()+'@ticker';}).join('/');}, parse:function(raw){var d=raw&&raw.data?raw.data:raw; var sym=d&&d.s; var p=d&&(d.c||d.w); var ts=d&&d.E; return sym&&p?{symbol:sym,price:Number(p),ts:Number(ts||Date.now()),source:'binance-spot-ticker'}:null;}}
  ];
  var REST_URLS=[
    {name:'binance-futures-premiumIndex',url:'https://fapi.binance.com/fapi/v1/premiumIndex',parse:function(j){return Array.isArray(j)?j.map(function(x){return {symbol:x.symbol,price:Number(x.markPrice),ts:Number(x.time||Date.now()),source:'binance-futures-rest'};}):[];}},
    {name:'binance-futures-ticker',url:'https://fapi.binance.com/fapi/v1/ticker/price',parse:function(j){return Array.isArray(j)?j.map(function(x){return {symbol:x.symbol,price:Number(x.price),ts:Number(Date.now()),source:'binance-futures-rest'};}):[];}}
  ];

  var state={};
  SYMBOLS.forEach(function(sym){state[sym]={symbol:sym,price:null,prev:null,delta:0,ts:0,age_ms:null,ticks:0,source:'none',ok:false,status:'BOOT',history:[]};});
  var ws=null, wsMode=0, reconnectDelay=1000, reconnectTimer=0, renderTimer=0, mountTimer=0, restTimer=0, resizeTimer=0;

  window.ZEL_APP_V47_LIVE_FEED={
    version:VERSION,
    symbols:SYMBOLS.slice(),
    state:state,
    connect:connect,
    refresh:restPoll,
    render:renderAll,
    stop:function(){try{if(ws) ws.close();}catch(e){} clearTimeout(reconnectTimer); clearInterval(renderTimer); clearInterval(mountTimer); clearInterval(restTimer); clearTimeout(resizeTimer);}
  };

  function now(){return Date.now();}
  function text(el){return (el&&el.textContent||'').replace(/\s+/g,' ').trim();}
  function clamp(n,a,b){return Math.max(a,Math.min(b,n));}
  function isFinitePrice(x){return isFinite(x)&&x>0;}
  function visible(el){if(!el||!el.getBoundingClientRect) return false; var r=el.getBoundingClientRect(); return r.width>16&&r.height>8;}
  function pct(a,b){return (isFinitePrice(a)&&isFinitePrice(b))?((a-b)/b)*100:0;}

  function cleanupLegacy(){
    var sel=[
      '.zel-v34-source-badge','.zel-v35-source-badge','.zel-v36-live-panel','.zel-v37-live-panel','.zel-v38-live-panel','.zel-v39-live-panel','.zel-v40-live-panel',
      '.zel-v41-live-graph','.zel-v41-graph','.zel-v42-live-tick-chart','.zel-v42-tick-chart',
      '.zel-v43-live-layer','.zel-v43-card-live-pill','.zel-v44-live-layer','.zel-v44-card-live-pill',
      '.zel-v45-live-layer','.zel-v45-live-canvas-wrap','.zel-v45-live-meta','.zel-v45-live-head',
      '[data-zel-v41]','[data-zel-v42]','[data-zel-v43]','[data-zel-v44]','[data-zel-v45-live-card="child"]',
      '#zel-v34-source-badge','#zel-v41-live-graph','#zel-v42-live-tick-chart','#zel-v43-live-chart','#zel-v44-live-chart','#zel-v45-live-chart'
    ].join(',');
    document.querySelectorAll(sel).forEach(function(n){try{n.remove();}catch(e){}});
    document.querySelectorAll('[class*="float"],[class*="badge"],[id*="float"],[id*="badge"]').forEach(function(n){
      var t=text(n); if(/SOURCE\s+(BOUND|HOLD)|missing:|age_ms|V3[4-9]|V4[0-6]/i.test(t)){try{n.remove();}catch(e){}}
    });
  }

  function scoreMarketCard(el,sym){
    if(!visible(el)) return -9999;
    if(el.closest('.zel-v47-ignore,.zel-v45-live-layer,.zel-v42-live-tick-chart,.zel-v43-live-layer,.zel-v44-live-layer')) return -9999;
    var t=text(el); if(t.indexOf(sym)<0) return -9999;
    if(/Operational Console|CURRENT ZEL OPERATING CONCLUSION|Decision proof|Advanced ZEL stack|Advisor Micro|Evidence Summary|Execution guard|Virtual route|Live account/i.test(t)) return -9999;
    var r=el.getBoundingClientRect(); if(r.width<150||r.height<80||r.height>650) return -9999;
    var sc=0;
    if(t.slice(0,100).indexOf(sym)>=0) sc+=12;
    if(/sig=read_only|sig-read|read_only/i.test(t)) sc+=8;
    if(/risk-hold|proof=missing|source-required|vol=medium|receipt_hash|liq=unbound/i.test(t)) sc+=8;
    if(/unbound|source-bound|source bound/i.test(t)) sc+=5;
    if(r.height<360) sc+=5; else sc-=Math.floor((r.height-360)/40);
    sc+=clamp(12-Math.floor(t.length/170),-16,12);
    sc-=Math.floor(el.querySelectorAll('*').length/90);
    return sc;
  }

  function findCard(sym){
    var nodes=Array.prototype.slice.call(document.querySelectorAll('article,section,main div,div'));
    var best=null, bestScore=-9999;
    nodes.forEach(function(el){var s=scoreMarketCard(el,sym); if(s>bestScore){bestScore=s; best=el;}});
    return bestScore>0?best:null;
  }

  function findNativeBar(card){
    var cr=card.getBoundingClientRect();
    var bars=[];
    Array.prototype.slice.call(card.querySelectorAll('div,span,i,b')).forEach(function(el){
      if(el.classList&&el.classList.contains('zel-v47-native-spark-wrap')) return;
      if(!visible(el)) return;
      var r=el.getBoundingClientRect();
      if(r.width<Math.min(120,cr.width*0.34)||r.height>14||r.height<1) return;
      if(r.top<cr.top+42||r.top>cr.bottom-70) return;
      var cs=getComputedStyle(el);
      var bg=(cs.backgroundColor||'')+' '+(cs.borderTopColor||'')+' '+(cs.color||'');
      var cyan=/rgb\(\s*(0|3[0-9]|4[0-9]|5[0-9]|6[0-9]|7[0-9]|8[0-9])\s*,\s*(1[5-9][0-9]|2[0-5][0-9])\s*,\s*(1[5-9][0-9]|2[0-5][0-9])\s*\)/i.test(bg);
      var muted=/rgb\(\s*(2[0-9]|3[0-9]|4[0-9])\s*,\s*(3[0-9]|4[0-9]|5[0-9])\s*,\s*(4[0-9]|5[0-9]|6[0-9])\s*\)/i.test(bg);
      var sc=(cyan?20:0)+(muted?4:0)+Math.min(20,r.width/12)-Math.abs((r.top-cr.top)-(cr.height*0.42))/12;
      bars.push({el:el,score:sc,r:r});
    });
    bars.sort(function(a,b){return b.score-a.score;});
    return bars.length?bars[0].el:null;
  }

  function ensureSpark(card,sym){
    var wrap=card.querySelector(':scope > .zel-v47-native-spark-wrap, .zel-v47-native-spark-wrap[data-symbol="'+sym+'"]');
    if(wrap) return wrap;
    var bar=findNativeBar(card);
    card.classList.add('zel-v47-live-card');
    card.setAttribute('data-zel-v47-symbol',sym);
    card.style.position=card.style.position||'relative';
    wrap=document.createElement('div');
    wrap.className='zel-v47-native-spark-wrap';
    wrap.setAttribute('data-symbol',sym);
    var canvas=document.createElement('canvas');
    canvas.className='zel-v47-native-spark';
    canvas.setAttribute('aria-hidden','true');
    wrap.appendChild(canvas);
    if(bar&&bar.parentNode){
      bar.setAttribute('data-zel-v47-hidden-static-bar','1');
      bar.parentNode.insertBefore(wrap,bar);
      // Hide nearby old static cyan/gray rails only inside the same graph band.
      var br=bar.getBoundingClientRect();
      Array.prototype.slice.call(card.querySelectorAll('div,span,i,b')).forEach(function(el){
        if(el===wrap||wrap.contains(el)) return;
        var r=el.getBoundingClientRect&&el.getBoundingClientRect(); if(!r) return;
        if(Math.abs(r.top-br.top)<26&&r.width>80&&r.height<=14){el.setAttribute('data-zel-v47-hidden-static-bar','1');}
      });
    }else{
      // Fallback: insert after the first status-looking line, but still native inside card.
      var ref=null;
      Array.prototype.slice.call(card.children).some(function(ch){if(text(ch).indexOf(sym)>=0||/unbound|source-bound/i.test(text(ch))){ref=ch; return true;} return false;});
      if(ref&&ref.nextSibling) card.insertBefore(wrap,ref.nextSibling); else card.appendChild(wrap);
    }
    return wrap;
  }

  function mountCard(sym){
    var card=findCard(sym); if(!card) return null;
    ensureSpark(card,sym);
    return card;
  }
  function mountAll(){cleanupLegacy(); SYMBOLS.forEach(mountCard);}

  function ingest(t){
    if(!t||SYMBOLS.indexOf(t.symbol)<0||!isFinitePrice(t.price)) return;
    var s=state[t.symbol], old=s.price, ts=Number(t.ts||now());
    s.prev=old; s.price=t.price; s.ts=ts; s.age_ms=Math.max(0,now()-ts); s.ticks+=1; s.source=t.source||s.source; s.ok=true; s.status='LIVE';
    s.delta=pct(t.price,old);
    s.history.push({p:t.price,t:ts});
    if(s.history.length>MAX_POINTS) s.history=s.history.slice(s.history.length-MAX_POINTS);
    window.dispatchEvent(new CustomEvent('zel:exchange-live-tick',{detail:{version:VERSION,symbol:t.symbol,price:t.price,ts:ts,source:s.source,ticks:s.ticks}}));
  }

  async function restPoll(){
    for(var i=0;i<REST_URLS.length;i++){
      try{
        var ep=REST_URLS[i], r=await fetch(ep.url+(ep.url.indexOf('?')<0?'?':'&')+'v='+now(),{cache:'no-store',mode:'cors'});
        if(!r.ok) continue;
        var arr=ep.parse(await r.json()).filter(function(x){return SYMBOLS.indexOf(x.symbol)>=0&&isFinitePrice(x.price);});
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
    ws.onopen=function(){reconnectDelay=1000;};
    ws.onmessage=function(ev){try{ingest(ep.parse(JSON.parse(ev.data)));}catch(e){}};
    ws.onerror=function(){};
    ws.onclose=function(){scheduleReconnect();};
  }
  function scheduleReconnect(){clearTimeout(reconnectTimer); reconnectTimer=setTimeout(connect,reconnectDelay); reconnectDelay=Math.min(15000,Math.floor(reconnectDelay*1.6));}

  function drawSpark(sym,wrap){
    var canvas=wrap&&wrap.querySelector('canvas'); if(!canvas) return;
    var s=state[sym], hist=(s&&s.history)||[];
    var rect=wrap.getBoundingClientRect();
    if(rect.width<40||rect.height<28) return;
    var dpr=window.devicePixelRatio||1, w=Math.max(1,Math.floor(rect.width*dpr)), h=Math.max(1,Math.floor(rect.height*dpr));
    if(canvas.width!==w||canvas.height!==h){canvas.width=w; canvas.height=h; canvas.style.width=rect.width+'px'; canvas.style.height=rect.height+'px';}
    var ctx=canvas.getContext('2d');
    ctx.clearRect(0,0,w,h);
    ctx.save(); ctx.scale(dpr,dpr);
    var cw=rect.width, ch=rect.height, pad=6;
    ctx.lineWidth=1;
    ctx.strokeStyle='rgba(125,220,255,.16)';
    for(var gy=0;gy<4;gy++){var y=pad+gy*(ch-pad*2)/3; ctx.beginPath(); ctx.moveTo(pad,y); ctx.lineTo(cw-pad,y); ctx.stroke();}
    if(hist.length<2){
      // Waiting state: no fake price movement, just a native empty rail.
      ctx.strokeStyle='rgba(111,229,255,.45)'; ctx.lineWidth=2; ctx.beginPath(); ctx.moveTo(pad,ch/2); ctx.lineTo(cw-pad,ch/2); ctx.stroke(); ctx.restore(); return;
    }
    var vals=hist.map(function(x){return x.p;}).filter(isFinitePrice);
    var min=Math.min.apply(Math,vals), max=Math.max.apply(Math,vals);
    if(max===min){max=min*1.00005; min=min*0.99995;}
    var span=max-min;
    function X(i){return pad+(cw-pad*2)*(i/(hist.length-1));}
    function Y(p){return ch-pad-((p-min)/span)*(ch-pad*2);}
    var grad=ctx.createLinearGradient(0,0,0,ch);
    grad.addColorStop(0,'rgba(0,255,196,.24)'); grad.addColorStop(1,'rgba(0,255,196,0)');
    ctx.beginPath();
    hist.forEach(function(pt,i){var x=X(i), y=Y(pt.p); if(i===0)ctx.moveTo(x,y); else ctx.lineTo(x,y);});
    ctx.lineTo(cw-pad,ch-pad); ctx.lineTo(pad,ch-pad); ctx.closePath(); ctx.fillStyle=grad; ctx.fill();
    ctx.beginPath();
    hist.forEach(function(pt,i){var x=X(i), y=Y(pt.p); if(i===0)ctx.moveTo(x,y); else ctx.lineTo(x,y);});
    ctx.strokeStyle='rgba(99,231,255,.95)'; ctx.lineWidth=2.2; ctx.shadowColor='rgba(0,255,196,.38)'; ctx.shadowBlur=8; ctx.stroke();
    var last=hist[hist.length-1];
    ctx.shadowBlur=10; ctx.fillStyle=(now()-(s.ts||0)<STALE_MS)?'rgba(0,255,196,.98)':'rgba(255,214,89,.95)';
    ctx.beginPath(); ctx.arc(X(hist.length-1),Y(last.p),3.4,0,Math.PI*2); ctx.fill();
    ctx.restore();
  }

  function renderCard(sym,card){
    card=card||findCard(sym); if(!card) return;
    var s=state[sym];
    var wrap=ensureSpark(card,sym);
    var age=s&&s.ts?Math.max(0,now()-s.ts):null;
    card.setAttribute('data-zel-v47-live-price',s&&s.price?String(s.price):'');
    card.setAttribute('data-zel-v47-live-source',s&&s.source?s.source:'none');
    card.setAttribute('data-zel-v47-live-ticks',s?String(s.ticks||0):'0');
    card.setAttribute('data-zel-v47-live-age-ms',age===null?'':String(age));
    card.classList.toggle('zel-v47-feed-live',!!(s&&s.price&&age!==null&&age<STALE_MS));
    card.classList.toggle('zel-v47-feed-wait',!(s&&s.price&&age!==null&&age<STALE_MS));
    drawSpark(sym,wrap);
  }
  function renderAll(){cleanupLegacy(); SYMBOLS.forEach(function(sym){renderCard(sym,mountCard(sym));});}

  function boot(){
    mountAll(); restPoll(); connect();
    mountTimer=setInterval(mountAll,2500);
    renderTimer=setInterval(renderAll,500);
    restTimer=setInterval(restPoll,5000);
    window.addEventListener('resize',function(){clearTimeout(resizeTimer); resizeTimer=setTimeout(renderAll,150);},{passive:true});
  }
  if(document.readyState==='loading') document.addEventListener('DOMContentLoaded',boot,{once:true}); else boot();
})();
