/* ZEL APP V52 - V47 native market cards + real exchange live feed; old static strip removed.
 * App-only browser runtime. No nginx/caddy/systemd/server config mutation. No orders.
 */
(function(){
  'use strict';
  var VER='v52';
  var SYMBOLS=['BTCUSDT','ETHUSDT','SOLUSDT','XRPUSDT','LINKUSDT'];
  var STREAMS=SYMBOLS.map(function(s){return s.toLowerCase()+'@trade';}).join('/');
  var WS_URL='wss://fstream.binance.com/stream?streams='+STREAMS;
  var REST_FUTURES='https://fapi.binance.com/fapi/v1/ticker/price?symbol=';
  var REST_SPOT='https://api.binance.com/api/v3/ticker/price?symbol=';
  var MAX=96;
  var states={};
  var ws=null, wsOk=false, lastScan=0, booted=false, scanBusy=false;
  SYMBOLS.forEach(function(s){states[s]={symbol:s,price:null,prev:null,first:null,ticks:0,ts:0,source:'init',hist:[],card:null,valueNode:null,statusNode:null,wrap:null,svg:null,line:null,area:null,dot:null,lastRender:0,origTitle:null};});

  function now(){return Date.now();}
  function isNum(n){return typeof n==='number' && isFinite(n);}
  function textOf(el){return (el&&el.textContent||'').replace(/\s+/g,' ').trim();}
  function visible(el){
    if(!el || el.nodeType!==1) return false;
    var cs=getComputedStyle(el);
    if(cs.display==='none'||cs.visibility==='hidden'||Number(cs.opacity)===0) return false;
    var r=el.getBoundingClientRect();
    return r.width>0 && r.height>0;
  }
  function decimals(sym,n){
    if(sym==='BTCUSDT') return 1;
    if(sym==='ETHUSDT') return 2;
    if(sym==='XRPUSDT') return 4;
    if(sym==='SOLUSDT'||sym==='LINKUSDT') return 3;
    return n>=1000?1:n>=100?2:n>=1?4:6;
  }
  function fmt(n,sym){
    if(!isNum(n)) return '';
    var d=decimals(sym,n);
    return n.toLocaleString('en-US',{minimumFractionDigits:d,maximumFractionDigits:d});
  }
  function pct(st){
    if(!isNum(st.first)||!isNum(st.price)||st.first===0) return '+0.000%';
    var p=(st.price-st.first)/st.first*100;
    return (p>=0?'+':'')+p.toFixed(3)+'%';
  }

  function cardScore(el,sym){
    if(!visible(el) || el.closest('[data-zel-v52-live="1"]')) return -1;
    var t=textOf(el);
    if(t.indexOf(sym)<0) return -1;
    var r=el.getBoundingClientRect();
    if(r.width<150 || r.height<120 || r.width>980 || r.height>780) return -1;
    var sc=0;
    if(/sig\s*=\s*read_only/i.test(t)) sc+=60;
    if(/risk\s*=\s*hold/i.test(t)) sc+=42;
    if(/proof\s*=\s*missing/i.test(t)) sc+=30;
    if(/XAI\s*:/i.test(t)) sc+=24;
    if(/source-required|receipt_hash|liq-unbound/i.test(t)) sc+=18;
    if(textOf(el).slice(0,80).indexOf(sym)>=0) sc+=18;
    sc += Math.max(0,240000-(r.width*r.height))/10000;
    return sc;
  }
  function findCard(sym){
    var all=document.querySelectorAll('article,section,li,main,div');
    var best=null, bestScore=-1;
    for(var i=0;i<all.length;i++){
      var sc=cardScore(all[i],sym);
      if(sc>bestScore){bestScore=sc;best=all[i];}
    }
    return bestScore>44?best:null;
  }
  function findValueNode(card,sym){
    if(!card) return null;
    var cr=card.getBoundingClientRect();
    var list=card.querySelectorAll('h1,h2,h3,strong,b,span,div,p');
    var cand=[];
    for(var i=0;i<list.length;i++){
      var el=list[i];
      if(el.closest('[data-zel-v52-live="1"]')) continue;
      if(!visible(el)) continue;
      var tx=textOf(el);
      if(!tx || tx===sym || tx.length>48) continue;
      if(/sig\s*=\s*read_only|risk=|proof=|source-required|liq-|receipt_|XAI\s*:|LIVE FEED/i.test(tx)) continue;
      var r=el.getBoundingClientRect();
      if(r.top<cr.top || r.top>cr.top+98) continue;
      var fs=parseFloat(getComputedStyle(el).fontSize)||0;
      if(/^(unbound|source-bound|wait|hold|data hold)$/i.test(tx) || /^\d[\d,.]*$/.test(tx) || fs>=18){
        cand.push({el:el,tx:tx,top:r.top,left:r.left,fs:fs,area:r.width*r.height});
      }
    }
    cand.sort(function(a,b){
      var ap=/^(unbound|source-bound|wait|hold|data hold)$/i.test(a.tx)||/^\d/.test(a.tx)?0:30;
      var bp=/^(unbound|source-bound|wait|hold|data hold)$/i.test(b.tx)||/^\d/.test(b.tx)?0:30;
      return ap-bp || b.fs-a.fs || a.top-b.top || a.left-b.left;
    });
    return cand.length?cand[0].el:null;
  }
  function hideEl(el){
    if(!el || el.getAttribute('data-zel-v52-live')==='1') return;
    el.setAttribute('data-zel-v52-hide-rail','1');
    try{
      el.style.setProperty('display','none','important');
      el.style.setProperty('visibility','hidden','important');
      el.style.setProperty('opacity','0','important');
      el.style.setProperty('height','0','important');
      el.style.setProperty('min-height','0','important');
      el.style.setProperty('max-height','0','important');
      el.style.setProperty('margin','0','important');
      el.style.setProperty('padding','0','important');
      el.style.setProperty('border','0','important');
      el.style.setProperty('overflow','hidden','important');
    }catch(e){}
  }
  function isRailish(el,cr){
    if(!el || el.nodeType!==1 || el.closest('[data-zel-v52-live="1"]')) return false;
    if(el.matches('button,a,input,textarea,select')) return false;
    var tx=textOf(el);
    if(tx) return false;
    if(!visible(el)) return false;
    var r=el.getBoundingClientRect();
    if(r.top<cr.top+58 || r.top>cr.bottom-12) return false;
    var wMin=Math.max(82,cr.width*0.22);
    if(r.width<wMin) return false;
    if(r.height>0 && r.height<=14) return true;
    if(r.height<=24 && el.children.length<=2){
      var kids=el.children;
      for(var i=0;i<kids.length;i++){
        var kr=kids[i].getBoundingClientRect();
        if(kr.width>=wMin*.6 && kr.height>0 && kr.height<=12 && !textOf(kids[i])) return true;
      }
    }
    var cls=(el.className&&String(el.className)||'').toLowerCase();
    if(/bar|rail|track|progress|meter|line|strip/.test(cls) && r.width>=wMin && r.height<=32) return true;
    return false;
  }
  function removeStaticStrip(card){
    if(!card) return;
    var cr=card.getBoundingClientRect();
    var nodes=card.querySelectorAll('div,span,i,b,em,small,svg,canvas');
    for(var i=0;i<nodes.length;i++){
      var el=nodes[i];
      if(isRailish(el,cr)) hideEl(el);
    }
  }

  function ensureStatus(st){
    if(!st.card) return;
    if(st.statusNode && document.body.contains(st.statusNode)) return;
    var node=document.createElement('div');
    node.className='zel-v52-status';
    node.setAttribute('data-zel-v52-live','1');
    var anchor=st.valueNode || findValueNode(st.card,st.symbol);
    if(anchor && anchor.parentNode && anchor!==st.card) anchor.insertAdjacentElement('afterend',node);
    else st.card.insertBefore(node,st.card.firstChild?st.card.firstChild.nextSibling:null);
    st.statusNode=node;
  }
  function ensureSpark(st){
    if(!st.card) return;
    if(st.wrap && document.body.contains(st.wrap)) return;
    var wrap=document.createElement('div');
    wrap.className='zel-v52-spark-wrap';
    wrap.setAttribute('data-zel-v52-live','1');
    wrap.innerHTML='<svg class="zel-v52-spark" data-zel-v52-live="1" viewBox="0 0 100 40" preserveAspectRatio="none" aria-hidden="true">'
      +'<defs><linearGradient id="zelv52g_'+st.symbol+'" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="rgba(95,255,235,.30)"/><stop offset="1" stop-color="rgba(95,255,235,0)"/></linearGradient></defs>'
      +'<g class="zgrid"><line x1="0" x2="100" y1="8" y2="8"/><line x1="0" x2="100" y1="20" y2="20"/><line x1="0" x2="100" y1="32" y2="32"/></g>'
      +'<path class="zarea" d=""></path><path class="zline" d=""></path><circle class="zdot" cx="0" cy="0" r="1.2" opacity="0"></circle></svg>';
    st.svg=wrap.querySelector('svg'); st.line=wrap.querySelector('.zline'); st.area=wrap.querySelector('.zarea'); st.dot=wrap.querySelector('.zdot');
    var anchor=st.statusNode || st.valueNode || findValueNode(st.card,st.symbol);
    if(anchor && anchor.parentNode && anchor!==st.card) anchor.insertAdjacentElement('afterend',wrap);
    else st.card.insertBefore(wrap,st.card.firstChild?st.card.firstChild.nextSibling:null);
    st.wrap=wrap;
  }
  function bindCards(){
    if(scanBusy) return; scanBusy=true;
    try{
      SYMBOLS.forEach(function(sym){
        var st=states[sym];
        var card=findCard(sym);
        if(!card) return;
        if(card!==st.card){
          st.card=card; st.valueNode=null; st.statusNode=null; st.wrap=null;
          card.classList.add('zel-v52-live-card');
          card.setAttribute('data-zel-v52-symbol',sym);
        }
        st.valueNode=(st.valueNode&&document.body.contains(st.valueNode))?st.valueNode:findValueNode(card,sym);
        if(st.valueNode && !st.origTitle) st.origTitle=textOf(st.valueNode);
        ensureStatus(st);
        ensureSpark(st);
        removeStaticStrip(card);
        renderOne(st,true);
      });
    }finally{scanBusy=false;}
  }

  function draw(st){
    if(!st.line || !st.area || !st.dot) return;
    var arr=st.hist.map(function(x){return x.p;});
    if(!arr.length){st.line.setAttribute('d','');st.area.setAttribute('d','');st.dot.setAttribute('opacity','0');return;}
    if(arr.length===1) arr=[arr[0],arr[0]];
    var min=Math.min.apply(null,arr), max=Math.max.apply(null,arr);
    if(max===min){max=min*1.00025; min=min*0.99975;}
    var pts=[];
    for(var i=0;i<arr.length;i++){
      var x=(i/(arr.length-1))*100;
      var y=36-((arr[i]-min)/(max-min))*30;
      if(y<4)y=4; if(y>36)y=36;
      pts.push([x,y]);
    }
    var d='M '+pts.map(function(p){return p[0].toFixed(2)+' '+p[1].toFixed(2);}).join(' L ');
    st.line.setAttribute('d',d);
    st.area.setAttribute('d',d+' L 100 40 L 0 40 Z');
    var last=pts[pts.length-1];
    st.dot.setAttribute('cx',last[0].toFixed(2)); st.dot.setAttribute('cy',last[1].toFixed(2)); st.dot.setAttribute('opacity','1');
  }
  function renderOne(st,force){
    if(!st.card || !document.body.contains(st.card)) return;
    var t=now();
    if(!force && t-st.lastRender<90) return;
    st.lastRender=t;
    ensureStatus(st); ensureSpark(st); removeStaticStrip(st.card);
    var live=isNum(st.price);
    st.card.setAttribute('data-zel-v52-bound',live?'1':'0');
    if(live && st.valueNode){
      st.valueNode.textContent=fmt(st.price,st.symbol);
      st.valueNode.classList.add('zel-v52-value');
      st.valueNode.setAttribute('data-zel-v52-live','1');
    }
    if(st.statusNode){
      if(live){
        st.statusNode.textContent='LIVE FEED '+st.source+' · '+pct(st)+' · ticks '+st.ticks+' · age '+Math.max(0,t-st.ts)+'ms · proof RO';
      }else{
        st.statusNode.textContent='LIVE FEED connecting · no exchange tick yet · proof RO';
      }
    }
    draw(st);
  }
  function renderAll(force){SYMBOLS.forEach(function(s){renderOne(states[s],!!force);});}

  function push(sym,price,source){
    var st=states[sym];
    if(!st || !isNum(price) || price<=0) return;
    st.prev=st.price;
    if(!isNum(st.first)) st.first=price;
    st.price=price; st.ticks++; st.ts=now(); st.source=source||'exchange';
    if(!st.hist.length || st.hist[st.hist.length-1].p!==price || now()-st.hist[st.hist.length-1].t>950){
      st.hist.push({p:price,t:st.ts});
      if(st.hist.length>MAX) st.hist=st.hist.slice(st.hist.length-MAX);
    }
    renderOne(st,false);
  }
  function seedRest(sym){
    var urls=[REST_FUTURES+encodeURIComponent(sym),REST_SPOT+encodeURIComponent(sym)];
    var i=0;
    function next(){
      if(i>=urls.length) return Promise.resolve();
      return fetch(urls[i++],{cache:'no-store'}).then(function(r){if(!r.ok) throw new Error('http'); return r.json();}).then(function(j){var p=parseFloat(j.price); if(isNum(p)) push(sym,p,'binance-rest');}).catch(next);
    }
    return next();
  }
  function pollRest(){SYMBOLS.forEach(seedRest);}
  function openWs(){
    try{
      if(ws){try{ws.close();}catch(e){}}
      ws=new WebSocket(WS_URL);
      ws.onopen=function(){wsOk=true;};
      ws.onmessage=function(ev){
        try{var m=JSON.parse(ev.data), d=m.data||m, sym=d.s, p=parseFloat(d.p||d.c||d.price); if(states[sym]&&isNum(p)) push(sym,p,'binance-ws');}catch(e){}
      };
      ws.onerror=function(){wsOk=false;};
      ws.onclose=function(){wsOk=false; setTimeout(openWs,2200);};
    }catch(e){wsOk=false;}
  }
  function cleanupLegacy(){
    var sel=['.zel-v34-source-badge','.zel-v35-source-badge','.zel-v36-live-panel','.zel-v37-live-panel','.zel-v38-live-panel','.zel-v39-live-panel','.zel-v40-live-panel','.zel-v41-live-graph','.zel-v41-graph','.zel-v42-live-tick-chart','.zel-v42-tick-chart','.zel-v43-live-layer','.zel-v43-card-live-pill','.zel-v44-live-layer','.zel-v44-card-live-pill','.zel-v45-live-layer','.zel-v45-live-canvas-wrap','.zel-v46-live-layer','.zel-v47-live-panel','.zel-v48-live-panel','.zel-v49-live-panel','.zel-v50-live-panel','.zel-v51-live-panel','#zel-v34-source-badge','#zel-v41-live-graph','#zel-v42-live-tick-chart','#zel-v43-live-chart','#zel-v44-live-chart','#zel-v45-live-chart'].join(',');
    try{document.querySelectorAll(sel).forEach(function(n){n.remove();});}catch(e){}
  }
  function loop(){
    var t=now();
    if(t-lastScan>700){lastScan=t; cleanupLegacy(); bindCards();}
    renderAll(false);
    requestAnimationFrame(loop);
  }
  function boot(){
    if(booted) return; booted=true;
    document.documentElement.classList.add('zel-app-v52-live-feed');
    cleanupLegacy(); bindCards(); pollRest(); openWs();
    setInterval(function(){
      var stale=false; SYMBOLS.forEach(function(s){var st=states[s]; if(!isNum(st.price)||now()-st.ts>3500) stale=true;});
      if(stale || !wsOk) pollRest();
    },1300);
    setInterval(function(){if(!wsOk) openWs();},6000);
    var mo=new MutationObserver(function(){cleanupLegacy(); bindCards();});
    mo.observe(document.documentElement,{childList:true,subtree:true});
    window.ZEL_APP_V52_LIVE_FEED={version:VER,states:states,rebind:bindCards,poll:pollRest,removeStaticStrip:removeStaticStrip};
    loop();
  }
  if(document.readyState==='loading') document.addEventListener('DOMContentLoaded',boot,{once:true}); else boot();
})();
