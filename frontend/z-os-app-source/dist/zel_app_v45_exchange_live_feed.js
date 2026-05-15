/* ZEL APP V45 EXCHANGE LIVE FEED NATIVE CARDS
 * Scope: browser/app only. No server config, no order path, no floating badge.
 * Purpose: existing market cards become live exchange tick charts.
 */
(function(){
  'use strict';
  var VERSION='V45_EXCHANGE_LIVE_FEED_NATIVE_CARDS';
  var SYMBOLS=['BTCUSDT','ETHUSDT','SOLUSDT','XRPUSDT','LINKUSDT'];
  var MAX_TICKS=180;
  var PATCH_ATTR='data-zel-v45-live-card';
  var state={};
  SYMBOLS.forEach(function(s){state[s]={symbol:s, price:null, prev:null, ts:0, ticks:[], source:'exchange', status:'CONNECTING', ws:null};});
  var ws=null, endpointMode=0, reconnectTimer=null, reconnectDelay=1200;
  var endpointList=[
    {name:'binance-futures-mark', url:function(){return 'wss://fstream.binance.com/stream?streams='+SYMBOLS.map(function(s){return s.toLowerCase()+'@markPrice@1s';}).join('/');}, parse:function(raw){var d=raw && raw.data ? raw.data : raw; var sym=d && d.s; var p=d && (d.p||d.markPrice); return sym&&p?{symbol:sym,price:Number(p),ts:Number(d.E||d.T||Date.now())}:null;}},
    {name:'binance-spot-ticker', url:function(){return 'wss://stream.binance.com:9443/stream?streams='+SYMBOLS.map(function(s){return s.toLowerCase()+'@ticker';}).join('/');}, parse:function(raw){var d=raw && raw.data ? raw.data : raw; var sym=d && d.s; var p=d && (d.c||d.w); return sym&&p?{symbol:sym,price:Number(p),ts:Number(d.E||Date.now())}:null;}}
  ];
  window.ZEL_APP_V45_LIVE_FEED={version:VERSION,state:state,reconnect:connect,render:renderAll};

  function now(){return Date.now();}
  function fmtPrice(x){
    if(!isFinite(x)) return '—';
    if(x>=1000) return Math.round(x).toLocaleString('en-US');
    if(x>=100) return x.toFixed(2);
    if(x>=1) return x.toFixed(4);
    return x.toPrecision(5);
  }
  function pct(a,b){return isFinite(a)&&isFinite(b)&&b!==0?((a-b)/b*100):0;}
  function safeText(el){return (el && el.textContent || '').replace(/\s+/g,' ').trim();}
  function isVisible(el){var r=el.getBoundingClientRect(); return r.width>160 && r.height>90;}
  function cleanupOld(){
    var sel=[
      '.zel-v41-live-graph','.zel-v41-graph','.zel-v42-live-tick-chart','.zel-v42-tick-chart',
      '.zel-v43-card-live-pill','.zel-v43-live-layer','.zel-v44-card-live-pill','.zel-v44-live-layer',
      '[data-zel-v41]','[data-zel-v42]','[data-zel-v43]','[data-zel-v44]',
      '#zel-v41-live-graph','#zel-v42-live-tick-chart','#zel-v43-live-chart','#zel-v44-live-chart'
    ].join(',');
    document.querySelectorAll(sel).forEach(function(n){try{n.remove();}catch(e){}});
    document.querySelectorAll('[class*="float"][class*="badge"],[class*="source"][class*="badge"]').forEach(function(n){
      var t=safeText(n); if(/SOURCE\s+(BOUND|HOLD)|missing:|age_ms|V3[4-9]|V4[0-4]/i.test(t)){try{n.remove();}catch(e){}}
    });
  }
  function scoreCandidate(el,sym){
    if(!el || el.closest('.zel-v45-live-layer')) return -999;
    if(el.getAttribute(PATCH_ATTR)==='child') return -999;
    var t=safeText(el);
    if(t.indexOf(sym)<0) return -999;
    if(/CURRENT ZEL OPERATING CONCLUSION|Operational Console|Advisor|Evidence Summary/i.test(t)) return -999;
    var r=el.getBoundingClientRect();
    if(r.width<180 || r.height<95) return -999;
    var score=0;
    if(/sig=read_only|sig-read|read_only/i.test(t)) score+=8;
    if(/unbound|source-bound|SOURCE BOUND|risk-hold|proof=missing/i.test(t)) score+=8;
    if(t.slice(0,120).indexOf(sym)>=0) score+=6;
    score += Math.max(0, 8 - Math.floor(t.length/180));
    score -= Math.max(0, el.querySelectorAll('*').length/80);
    return score;
  }
  function findCard(sym){
    var nodes=Array.prototype.slice.call(document.querySelectorAll('article,section,main div,div'));
    var best=null, bestScore=-999;
    nodes.forEach(function(el){
      if(el.closest('.zel-v45-live-layer')) return;
      var sc=scoreCandidate(el,sym);
      if(sc>bestScore){bestScore=sc; best=el;}
    });
    return bestScore>0 ? best : null;
  }
  function mountCard(sym){
    var card=findCard(sym); if(!card) return;
    if(card.getAttribute(PATCH_ATTR)==='1') return;
    card.setAttribute(PATCH_ATTR,'1');
    card.classList.add('zel-v45-market-live-card');
    var old=card.querySelector('.zel-v45-live-layer'); if(old) old.remove();
    var layer=document.createElement('div');
    layer.className='zel-v45-live-layer';
    layer.setAttribute(PATCH_ATTR,'child');
    layer.innerHTML=''
      +'<div class="zel-v45-live-head"><div class="zel-v45-live-title">'+sym+' EXCHANGE LIVE</div><div class="zel-v45-live-state">CONNECTING</div></div>'
      +'<div class="zel-v45-live-canvas-wrap"><canvas class="zel-v45-live-canvas"></canvas></div>'
      +'<div class="zel-v45-live-meta"><span>price <b data-k="price">—</b></span><span>Δ <b data-k="delta">—</b></span><span>ticks <b data-k="ticks">0</b></span><span>age <b data-k="age">—</b></span><span>feed <b data-k="feed">ws</b></span></div>';
    var anchor=card.querySelector('.zel-v45-live-layer');
    if(anchor) anchor.replaceWith(layer); else card.appendChild(layer);
    renderCard(sym,card);
  }
  function mountAll(){cleanupOld(); SYMBOLS.forEach(mountCard);}
  function updateTick(sym,price,ts,src){
    if(!state[sym] || !isFinite(price)) return;
    var s=state[sym];
    s.prev=s.price; s.price=price; s.ts=ts||now(); s.source=src||s.source; s.status='LIVE';
    if(!s.ticks.length || s.ticks[s.ticks.length-1].price!==price || s.ticks[s.ticks.length-1].ts!==s.ts){
      s.ticks.push({price:price,ts:s.ts});
      if(s.ticks.length>MAX_TICKS) s.ticks=s.ticks.slice(s.ticks.length-MAX_TICKS);
    }
  }
  async function seedFromCf(){
    try{
      var r=await fetch('/zel_source_envelope_live.json?v='+Date.now(),{cache:'no-store'});
      if(!r.ok) return;
      var j=await r.json(); var p=j.payload||j;
      var sym=p.symbol||p.symbol_usdt||'BTCUSDT';
      var price=Number(p.price||p.price_usdt||p.last_price||p.mark_price);
      if(SYMBOLS.indexOf(sym)>=0 && isFinite(price)) updateTick(sym,price,Number(p.source_ts_ms||p.ts_ms||Date.now()),'cf-seed');
    }catch(e){}
  }
  function connect(){
    try{if(ws) ws.close();}catch(e){}
    clearTimeout(reconnectTimer);
    var ep=endpointList[endpointMode%endpointList.length]; endpointMode++;
    SYMBOLS.forEach(function(sym){if(state[sym].status!=='LIVE') state[sym].status='CONNECTING';});
    try{ws=new WebSocket(ep.url());}catch(e){scheduleReconnect();return;}
    ws.onopen=function(){reconnectDelay=1200; SYMBOLS.forEach(function(sym){if(!state[sym].price) state[sym].status='WAITING'; state[sym].feed=ep.name;});};
    ws.onmessage=function(ev){
      try{var raw=JSON.parse(ev.data); var t=ep.parse(raw); if(t && SYMBOLS.indexOf(t.symbol)>=0) updateTick(t.symbol,t.price,t.ts,ep.name);}catch(e){}
    };
    ws.onerror=function(){SYMBOLS.forEach(function(sym){if(state[sym].status!=='LIVE') state[sym].status='WS_ERROR';});};
    ws.onclose=function(){SYMBOLS.forEach(function(sym){if(now()-(state[sym].ts||0)>5000) state[sym].status='RECONNECT';}); scheduleReconnect();};
  }
  function scheduleReconnect(){clearTimeout(reconnectTimer); reconnectTimer=setTimeout(connect,reconnectDelay); reconnectDelay=Math.min(reconnectDelay*1.7,15000);}
  function draw(canvas,ticks,sym){
    var dpr=window.devicePixelRatio||1, rect=canvas.getBoundingClientRect();
    var w=Math.max(220,Math.floor(rect.width*dpr)), h=Math.max(64,Math.floor(rect.height*dpr));
    if(canvas.width!==w||canvas.height!==h){canvas.width=w; canvas.height=h;}
    var ctx=canvas.getContext('2d'); ctx.clearRect(0,0,w,h);
    ctx.fillStyle='rgba(1,13,22,.78)'; ctx.fillRect(0,0,w,h);
    ctx.strokeStyle='rgba(103,220,255,.14)'; ctx.lineWidth=1*dpr;
    for(var i=1;i<4;i++){var y=h*i/4; ctx.beginPath(); ctx.moveTo(0,y); ctx.lineTo(w,y); ctx.stroke();}
    if(!ticks || ticks.length<2){
      ctx.fillStyle='rgba(190,238,255,.85)'; ctx.font=(11*dpr)+'px ui-monospace,monospace'; ctx.fillText('waiting exchange ticks',12*dpr,24*dpr); return;
    }
    var prices=ticks.map(function(t){return t.price;});
    var min=Math.min.apply(null,prices), max=Math.max.apply(null,prices); if(max===min){max+=1; min-=1;}
    var pad=8*dpr, xstep=(w-pad*2)/Math.max(1,ticks.length-1);
    function y(v){return h-pad-((v-min)/(max-min))*(h-pad*2);}
    ctx.strokeStyle='rgba(0,255,196,.15)'; ctx.beginPath(); ctx.moveTo(pad,y(ticks[0].price)); ctx.lineTo(w-pad,y(ticks[0].price)); ctx.stroke();
    ctx.strokeStyle='rgba(80,225,255,.98)'; ctx.lineWidth=2*dpr; ctx.beginPath();
    ticks.forEach(function(t,i){var x=pad+i*xstep, yy=y(t.price); if(i===0) ctx.moveTo(x,yy); else ctx.lineTo(x,yy);}); ctx.stroke();
    var last=ticks[ticks.length-1]; var lx=pad+(ticks.length-1)*xstep, ly=y(last.price);
    ctx.fillStyle='rgba(0,255,180,.95)'; ctx.beginPath(); ctx.arc(lx,ly,3.5*dpr,0,Math.PI*2); ctx.fill();
    ctx.fillStyle='rgba(230,255,255,.95)'; ctx.font=(10*dpr)+'px ui-monospace,monospace';
    ctx.fillText(fmtPrice(last.price),8*dpr,18*dpr);
  }
  function renderCard(sym,card){
    card=card||document.querySelector('['+PATCH_ATTR+'="1"]'); if(!card) return;
    var layer=card.querySelector('.zel-v45-live-layer'); if(!layer) return;
    var s=state[sym]; var status=layer.querySelector('.zel-v45-live-state');
    var age=s.ts?now()-s.ts:null; var first=s.ticks.length?s.ticks[0].price:null; var delta=first?pct(s.price,first):null;
    var ok=s.price && age!==null && age<8000;
    status.textContent=(ok?'LIVE ':'WAIT ') + (s.feed||s.source||'ws') + ' · ticks '+s.ticks.length + (age!==null?' · age '+Math.max(0,age)+'ms':'');
    status.classList.toggle('zel-v45-warn',!ok);
    var set=function(k,v){var n=layer.querySelector('[data-k="'+k+'"]'); if(n) n.textContent=v;};
    set('price',fmtPrice(s.price)); set('delta',delta===null?'—':(delta>=0?'+':'')+delta.toFixed(3)+'%'); set('ticks',String(s.ticks.length)); set('age',age===null?'—':Math.max(0,age)+'ms'); set('feed',(s.feed||s.source||'ws').replace('binance-',''));
    var canvas=layer.querySelector('canvas'); if(canvas) draw(canvas,s.ticks,sym);
  }
  function renderAll(){
    SYMBOLS.forEach(function(sym){
      var cards=Array.prototype.slice.call(document.querySelectorAll('.zel-v45-market-live-card')).filter(function(c){return safeText(c).indexOf(sym)>=0;});
      cards.forEach(function(c){renderCard(sym,c);});
    });
  }
  function boot(){cleanupOld(); seedFromCf(); mountAll(); connect(); setInterval(seedFromCf,5000); setInterval(mountAll,1700); setInterval(renderAll,500);}
  if(document.readyState==='loading') document.addEventListener('DOMContentLoaded',boot,{once:true}); else boot();
})();
