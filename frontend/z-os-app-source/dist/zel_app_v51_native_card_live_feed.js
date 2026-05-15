/* ZEL APP V51 - V47-style native market cards with real exchange live feed.
 * App-only browser runtime. No server route mutation. No orders.
 */
(function(){
  'use strict';
  var VER='v51';
  var SYMBOLS=['BTCUSDT','ETHUSDT','SOLUSDT','XRPUSDT','LINKUSDT'];
  var STREAMS=SYMBOLS.map(function(s){return s.toLowerCase()+'@trade';}).join('/');
  var WS_URL='wss://fstream.binance.com/stream?streams='+STREAMS;
  var REST_FUTURES='https://fapi.binance.com/fapi/v1/ticker/price?symbol=';
  var REST_SPOT='https://api.binance.com/api/v3/ticker/price?symbol=';
  var MAX=72;
  var states={};
  var ws=null, wsOk=false, lastScan=0, booted=false;
  SYMBOLS.forEach(function(s){states[s]={symbol:s,price:null,first:null,last:null,ticks:0,ts:0,source:'init',hist:[],card:null,valueNode:null,statusNode:null,wrap:null,svg:null,path:null,area:null,dot:null,lastRender:0};});

  function now(){return Date.now();}
  function isNum(n){return typeof n==='number' && isFinite(n);}
  function fmtPrice(n,s){
    if(!isNum(n)) return '';
    var d = n>=1000 ? 0 : (n>=100 ? 2 : (n>=1 ? 4 : 6));
    return n.toLocaleString('en-US',{minimumFractionDigits:d,maximumFractionDigits:d});
  }
  function pct(st){
    if(!isNum(st.first)||!isNum(st.price)||st.first===0) return '0.000%';
    var p=(st.price-st.first)/st.first*100;
    return (p>=0?'+':'')+p.toFixed(3)+'%';
  }
  function vis(el){
    if(!el || el.nodeType!==1) return false;
    var r=el.getBoundingClientRect();
    var cs=getComputedStyle(el);
    return r.width>0 && r.height>0 && cs.display!=='none' && cs.visibility!=='hidden';
  }
  function cleanText(t){return (t||'').replace(/\s+/g,' ').trim();}

  function scoreCard(el,sym){
    if(!vis(el)) return -1;
    if(el.closest('[data-zel-v51-live="1"]')) return -1;
    var t=cleanText(el.textContent);
    if(t.indexOf(sym)<0) return -1;
    var r=el.getBoundingClientRect();
    if(r.width<150 || r.height<125) return -1;
    if(r.width>900 || r.height>700) return -1;
    var score=0;
    if(/sig\s*=\s*read_only/i.test(t)) score+=60;
    if(/risk\s*=\s*hold/i.test(t)) score+=45;
    if(/proof\s*=\s*missing/i.test(t)) score+=30;
    if(/XAI\s*:/i.test(t)) score+=25;
    if(/^\s*[A-Z]{2,6}USDT\b/.test(t)) score+=20;
    score+=Math.max(0,260000-(r.width*r.height))/10000;
    return score;
  }
  function findCard(sym){
    var all=document.querySelectorAll('section,article,main,div,li');
    var best=null, bestScore=-1;
    for(var i=0;i<all.length;i++){
      var sc=scoreCard(all[i],sym);
      if(sc>bestScore){best=all[i];bestScore=sc;}
    }
    return bestScore>40 ? best : null;
  }

  function findValueNode(card,sym){
    if(!card) return null;
    var cr=card.getBoundingClientRect();
    var els=card.querySelectorAll('h1,h2,h3,strong,b,span,div,p');
    var cand=[];
    for(var i=0;i<els.length;i++){
      var el=els[i];
      if(el.closest('[data-zel-v51-live="1"]')) continue;
      if(!vis(el)) continue;
      var tx=cleanText(el.textContent);
      if(!tx || tx===sym || tx.length>40) continue;
      if(/sig\s*=\s*read_only/i.test(tx)) continue;
      if(/risk=|proof=|source-required|liq-|receipt_|XAI\s*:/i.test(tx)) continue;
      var r=el.getBoundingClientRect();
      if(r.top<cr.top || r.top>cr.top+92) continue;
      var fs=parseFloat(getComputedStyle(el).fontSize)||0;
      if(/^(unbound|source-bound|wait|hold|data hold)$/i.test(tx) || /^\d[\d,.]*$/.test(tx) || fs>=18){
        cand.push({el:el,top:r.top,left:r.left,fs:fs,area:r.width*r.height,tx:tx});
      }
    }
    cand.sort(function(a,b){
      var av = (/^(unbound|source-bound|wait|hold|data hold)$/i.test(a.tx)||/^\d/.test(a.tx)) ? 0 : 30;
      var bv = (/^(unbound|source-bound|wait|hold|data hold)$/i.test(b.tx)||/^\d/.test(b.tx)) ? 0 : 30;
      return av-bv || b.fs-a.fs || a.top-b.top || a.left-b.left;
    });
    return cand.length ? cand[0].el : null;
  }

  function hideStaticRails(card){
    if(!card) return;
    var cr=card.getBoundingClientRect();
    var nodes=card.querySelectorAll('div,span,i,b');
    for(var i=0;i<nodes.length;i++){
      var el=nodes[i];
      if(el.closest('[data-zel-v51-live="1"]')) continue;
      if(!vis(el)) continue;
      var tx=cleanText(el.textContent);
      if(tx) continue;
      var r=el.getBoundingClientRect();
      if(r.width < Math.max(95, cr.width*0.32)) continue;
      if(r.height < 2 || r.height > 9) continue;
      if(r.top < cr.top+55 || r.top > cr.bottom-18) continue;
      el.setAttribute('data-zel-v51-hidden-static-bar','1');
    }
  }

  function ensureSpark(st){
    var card=st.card;
    if(!card) return;
    if(st.wrap && document.body.contains(st.wrap)) return;
    var wrap=document.createElement('div');
    wrap.className='zel-v51-native-spark-wrap';
    wrap.setAttribute('data-zel-v51-live','1');
    wrap.innerHTML='<svg class="zel-v51-native-spark" viewBox="0 0 100 40" preserveAspectRatio="none" aria-hidden="true">'
      +'<defs><linearGradient id="zelv51g_'+st.symbol+'" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="rgba(95,255,235,.28)"/><stop offset="1" stop-color="rgba(95,255,235,0)"/></linearGradient></defs>'
      +'<g class="zgrid"><line x1="0" x2="100" y1="8" y2="8"/><line x1="0" x2="100" y1="20" y2="20"/><line x1="0" x2="100" y1="32" y2="32"/></g>'
      +'<path class="zarea" d=""></path><path class="zline" d=""></path><circle class="zdot" cx="0" cy="0" r="1.25"></circle></svg>';
    st.svg=wrap.querySelector('svg');
    st.path=wrap.querySelector('.zline');
    st.area=wrap.querySelector('.zarea');
    st.dot=wrap.querySelector('.zdot');
    var anchor=st.valueNode || findValueNode(card,st.symbol);
    if(anchor && anchor.parentNode && anchor!==card){
      anchor.insertAdjacentElement('afterend',wrap);
    } else {
      var firstRail=null;
      var list=card.children;
      for(var i=0;i<list.length;i++){
        var r=list[i].getBoundingClientRect();
        if(r.top>card.getBoundingClientRect().top+60){firstRail=list[i];break;}
      }
      if(firstRail) card.insertBefore(wrap,firstRail); else card.appendChild(wrap);
    }
    st.wrap=wrap;
  }

  function ensureStatus(st){
    if(!st.card) return;
    if(st.statusNode && document.body.contains(st.statusNode)) return;
    var node=document.createElement('div');
    node.className='zel-v51-live-status';
    node.setAttribute('data-zel-v51-live','1');
    var anchor=st.valueNode || findValueNode(st.card,st.symbol);
    if(anchor && anchor.parentNode && anchor!==st.card){anchor.insertAdjacentElement('afterend',node);} else {st.card.insertBefore(node, st.card.firstChild.nextSibling || null);}
    st.statusNode=node;
  }

  function bindCards(){
    var changed=false;
    SYMBOLS.forEach(function(sym){
      var st=states[sym];
      var card=findCard(sym);
      if(card && card!==st.card){
        st.card=card;
        card.classList.add('zel-v51-live-card');
        card.setAttribute('data-zel-v51-symbol',sym);
        st.valueNode=findValueNode(card,sym);
        ensureStatus(st);
        ensureSpark(st);
        hideStaticRails(card);
        changed=true;
      } else if(card){
        st.card=card;
        st.valueNode=st.valueNode && document.body.contains(st.valueNode) ? st.valueNode : findValueNode(card,sym);
        ensureStatus(st);
        ensureSpark(st);
        hideStaticRails(card);
      }
    });
    if(changed) renderAll(true);
  }

  function push(sym,price,source){
    var st=states[sym];
    if(!st || !isNum(price) || price<=0) return;
    if(!isNum(st.first)) st.first=price;
    st.last=st.price;
    st.price=price;
    st.ticks++;
    st.ts=now();
    st.source=source||'exchange';
    st.hist.push({p:price,t:st.ts});
    if(st.hist.length>MAX) st.hist=st.hist.slice(st.hist.length-MAX);
    renderOne(st,false);
  }

  function renderOne(st,force){
    if(!st.card || !document.body.contains(st.card)) return;
    if(!force && now()-st.lastRender<120) return;
    st.lastRender=now();
    ensureStatus(st);
    ensureSpark(st);
    hideStaticRails(st.card);
    var has=isNum(st.price);
    st.card.classList.toggle('zel-v51-feed-live',has);
    st.card.classList.toggle('zel-v51-feed-wait',!has);
    if(has && st.valueNode){
      st.valueNode.textContent=fmtPrice(st.price,st.symbol);
      st.valueNode.classList.add('zel-v51-live-price');
      st.valueNode.setAttribute('data-zel-v51-price','1');
    }
    if(st.statusNode){
      if(has){
        var age=now()-st.ts;
        st.statusNode.textContent='LIVE FEED '+st.source+' · '+pct(st)+' · ticks '+st.ticks+' · age '+age+'ms · proof RO';
      } else {
        st.statusNode.textContent='LIVE FEED connecting · proof RO';
      }
    }
    draw(st);
  }
  function renderAll(force){SYMBOLS.forEach(function(s){renderOne(states[s],!!force);});}

  function draw(st){
    if(!st.path || !st.area || !st.dot) return;
    var h=st.hist;
    if(!h.length){st.path.setAttribute('d','');st.area.setAttribute('d','');st.dot.setAttribute('opacity','0');return;}
    var arr=h.map(function(x){return x.p;});
    if(arr.length===1) arr=[arr[0],arr[0]];
    var min=Math.min.apply(null,arr), max=Math.max.apply(null,arr);
    if(max===min){max=min*1.0005; min=min*0.9995;}
    var pts=[];
    for(var i=0;i<arr.length;i++){
      var x=arr.length===1?50:(i/(arr.length-1))*100;
      var y=36-((arr[i]-min)/(max-min))*30;
      if(y<4)y=4; if(y>36)y=36;
      pts.push([x,y]);
    }
    var d='M '+pts.map(function(p){return p[0].toFixed(2)+' '+p[1].toFixed(2);}).join(' L ');
    var area=d+' L 100 40 L 0 40 Z';
    st.path.setAttribute('d',d);
    st.area.setAttribute('d',area);
    var last=pts[pts.length-1];
    st.dot.setAttribute('cx',last[0].toFixed(2));
    st.dot.setAttribute('cy',last[1].toFixed(2));
    st.dot.setAttribute('opacity','1');
  }

  function seedRest(sym){
    var urls=[REST_FUTURES+encodeURIComponent(sym), REST_SPOT+encodeURIComponent(sym)];
    var idx=0;
    function next(){
      if(idx>=urls.length) return Promise.reject(new Error('seed_fail'));
      return fetch(urls[idx++],{cache:'no-store'}).then(function(r){if(!r.ok) throw new Error('http_'+r.status); return r.json();}).then(function(j){
        var p=parseFloat(j.price);
        if(!isNum(p)) throw new Error('bad_price');
        push(sym,p,'binance-rest');
      }).catch(next);
    }
    return next().catch(function(){});
  }
  function pollRest(){SYMBOLS.forEach(seedRest);}

  function openWs(){
    try{
      if(ws){try{ws.close();}catch(e){}}
      ws=new WebSocket(WS_URL);
      ws.onopen=function(){wsOk=true;};
      ws.onmessage=function(ev){
        try{
          var msg=JSON.parse(ev.data);
          var d=msg.data||msg;
          var sym=d.s;
          var p=parseFloat(d.p||d.price);
          if(states[sym] && isNum(p)) push(sym,p,'binance-ws');
        }catch(e){}
      };
      ws.onerror=function(){wsOk=false;};
      ws.onclose=function(){wsOk=false; setTimeout(openWs,2500);};
    }catch(e){wsOk=false;}
  }

  function tick(){
    var t=now();
    if(t-lastScan>900){lastScan=t; bindCards();}
    renderAll(false);
    requestAnimationFrame(tick);
  }

  function boot(){
    if(booted) return; booted=true;
    document.documentElement.classList.add('zel-app-v51-live-feed');
    cleanupLegacy();
    bindCards();
    pollRest();
    openWs();
    setInterval(function(){
      var stale=false;
      SYMBOLS.forEach(function(s){var st=states[s]; if(!isNum(st.price) || now()-st.ts>4500) stale=true;});
      if(stale || !wsOk) pollRest();
    },1800);
    setInterval(function(){if(!wsOk) openWs();},7000);
    tick();
    var mo=new MutationObserver(function(){bindCards(); cleanupLegacy();});
    mo.observe(document.documentElement,{childList:true,subtree:true});
    window.ZEL_APP_V51_LIVE_FEED={version:VER,states:states,rebind:bindCards,poll:pollRest};
  }
  function cleanupLegacy(){
    var sel=['.zel-v34-source-badge','.zel-v35-source-badge','.zel-v36-live-panel','.zel-v37-live-panel','.zel-v38-live-panel','.zel-v39-live-panel','.zel-v40-live-panel','.zel-v41-live-graph','.zel-v41-graph','.zel-v42-live-tick-chart','.zel-v42-tick-chart','.zel-v43-live-layer','.zel-v43-card-live-pill','.zel-v44-live-layer','.zel-v44-card-live-pill','.zel-v45-live-layer','.zel-v45-live-canvas-wrap','.zel-v46-live-layer','.zel-v47-live-panel','.zel-v48-live-panel','.zel-v49-live-panel','.zel-v50-live-panel','#zel-v34-source-badge','#zel-v41-live-graph','#zel-v42-live-tick-chart','#zel-v43-live-chart','#zel-v44-live-chart','#zel-v45-live-chart'].join(',');
    try{document.querySelectorAll(sel).forEach(function(n){n.remove();});}catch(e){}
  }
  if(document.readyState==='loading') document.addEventListener('DOMContentLoaded',boot,{once:true}); else boot();
})();
