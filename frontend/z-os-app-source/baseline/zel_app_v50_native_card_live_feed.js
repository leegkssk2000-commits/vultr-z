/* ZEL APP V50 native market-card live feed. V47 shape, fixed: no legacy bar, live exchange price in existing card. */
(function(){
  'use strict';
  var VER='V50';
  var SYMBOLS=['BTCUSDT','ETHUSDT','SOLUSDT','XRPUSDT','LINKUSDT'];
  var STREAM_SYMBOLS=SYMBOLS.map(function(s){return s.toLowerCase()+'@markPrice@1s';}).join('/');
  var WS_URL='wss://fstream.binance.com/stream?streams='+STREAM_SYMBOLS;
  var REST_BASE='https://fapi.binance.com/fapi/v1/premiumIndex?symbol=';
  var MAX_POINTS=96;
  var PATCH_ATTR='data-zel-v50-live-card';
  var state={};
  SYMBOLS.forEach(function(sym){state[sym]={symbol:sym,price:null,prev:null,ts:0,src:'init',ok:false,points:[],delta:0,ticks:0,lastDraw:0};});

  function now(){return Date.now();}
  function num(v){var n=Number(v);return isFinite(n)?n:null;}
  function fmtPrice(v){
    v=num(v); if(v===null) return 'WAIT';
    if(v>=1000) return v.toLocaleString('en-US',{maximumFractionDigits:0});
    if(v>=100) return v.toLocaleString('en-US',{minimumFractionDigits:2,maximumFractionDigits:2});
    if(v>=10) return v.toLocaleString('en-US',{minimumFractionDigits:3,maximumFractionDigits:3});
    return v.toLocaleString('en-US',{minimumFractionDigits:4,maximumFractionDigits:4});
  }
  function fmtDelta(st){
    if(!st || !st.prev || !st.price) return 'Δ 0.000%';
    var d=((st.price-st.prev)/st.prev)*100;
    var sign=d>0?'+':'';
    return 'Δ '+sign+d.toFixed(3)+'%';
  }
  function addPoint(sym,price,src,ts){
    price=num(price); if(price===null) return;
    var st=state[sym]; if(!st) return;
    if(st.price!==null) st.prev=st.price;
    st.price=price; st.ts=Number(ts)||now(); st.src=src||'exchange'; st.ok=true; st.ticks++;
    if(st.prev){ st.delta=((st.price-st.prev)/st.prev)*100; }
    var pts=st.points;
    var last=pts.length?pts[pts.length-1]:null;
    if(!last || last.p!==price || (st.ts-last.t)>850){
      pts.push({p:price,t:st.ts});
      while(pts.length>MAX_POINTS) pts.shift();
    }
  }

  async function restTick(sym){
    try{
      var r=await fetch(REST_BASE+encodeURIComponent(sym)+'&v='+Date.now(),{cache:'no-store',mode:'cors'});
      if(!r.ok) throw new Error('HTTP_'+r.status);
      var j=await r.json();
      var p=num(j.markPrice)||num(j.indexPrice)||num(j.lastFundingRate)||null;
      if(num(j.markPrice)!==null) p=num(j.markPrice);
      if(p!==null) addPoint(sym,p,'binance-futures-rest',Date.parse(j.time)||now());
    }catch(e){
      var st=state[sym]; if(st){st.src='rest_wait';}
    }
  }
  function restPollAll(){SYMBOLS.forEach(restTick);}

  function startWs(){
    try{
      var ws=new WebSocket(WS_URL);
      ws.onmessage=function(ev){
        try{
          var msg=JSON.parse(ev.data); var d=msg.data||msg;
          var sym=d.s; if(!state[sym]) return;
          var p=num(d.p)||num(d.markPrice)||num(d.c);
          if(p!==null) addPoint(sym,p,'binance-futures-ws',Number(d.E)||now());
        }catch(e){}
      };
      ws.onclose=function(){setTimeout(startWs,2500);};
      ws.onerror=function(){try{ws.close();}catch(e){}};
    }catch(e){setTimeout(startWs,5000);}
  }

  function visible(el){
    if(!el || el.nodeType!==1) return false;
    var cs=getComputedStyle(el); if(cs.display==='none'||cs.visibility==='hidden'||Number(cs.opacity)===0) return false;
    var r=el.getBoundingClientRect(); return r.width>4 && r.height>4;
  }
  function directText(el){
    var out='';
    for(var n=el.firstChild;n;n=n.nextSibling){ if(n.nodeType===3) out+=n.nodeValue; }
    return out.replace(/\s+/g,' ').trim();
  }
  function allVisibleText(el){return (el.textContent||'').replace(/\s+/g,' ').trim();}
  function hasSym(el,sym){return (el.textContent||'').toUpperCase().indexOf(sym)>=0;}
  function cardCandidates(){
    return Array.prototype.slice.call(document.querySelectorAll('section,article,div,li'));
  }
  function scoreCard(el,sym){
    if(!visible(el) || !hasSym(el,sym)) return -1;
    var r=el.getBoundingClientRect();
    if(r.width<120 || r.height<110 || r.height>900) return -1;
    var txt=allVisibleText(el).toUpperCase();
    var score=0;
    if(txt.indexOf(sym)>=0) score+=20;
    if(/UNBOUND|SOURCE-BOUND|WAIT|RISK-HOLD|PROOF=MISSING|SIG=READ_ONLY/.test(txt)) score+=15;
    var br=parseFloat(getComputedStyle(el).borderTopWidth)||0; if(br>0) score+=5;
    score-=Math.max(0,(r.width*r.height)/90000);
    return score;
  }
  function findCard(sym){
    var best=null, bestScore=-1;
    cardCandidates().forEach(function(el){
      var sc=scoreCard(el,sym);
      if(sc>bestScore){best=el; bestScore=sc;}
    });
    return bestScore>0?best:null;
  }
  function symbolNode(card,sym){
    var nodes=Array.prototype.slice.call(card.querySelectorAll('*')).filter(visible);
    var best=null, bestTop=1e9;
    var ct=card.getBoundingClientRect().top;
    nodes.forEach(function(el){
      var t=directText(el).toUpperCase();
      if(t===sym){var top=el.getBoundingClientRect().top-ct; if(top<bestTop){best=el; bestTop=top;}}
    });
    return best;
  }
  function primaryValueNode(card,sym){
    var ct=card.getBoundingClientRect().top;
    var cr=card.getBoundingClientRect();
    var nodes=Array.prototype.slice.call(card.querySelectorAll('*')).filter(visible);
    var candidates=[];
    nodes.forEach(function(el){
      if(el.classList && (el.classList.contains('zel-v50-native-chart')||el.closest('.zel-v50-native-chart'))) return;
      var dt=directText(el); if(!dt) return;
      var tx=dt.replace(/\s+/g,' ').trim();
      var up=tx.toUpperCase();
      if(up===sym) return;
      if(/SIG=READ_ONLY|RISK|PROOF|HOLD|SOURCE-REQUIRED|LIQ=|RECEIPT|XAI|LIVE FEED/.test(up)) return;
      var r=el.getBoundingClientRect();
      var top=r.top-ct;
      if(top<0 || top>Math.min(115,cr.height*.42)) return;
      var fs=parseFloat(getComputedStyle(el).fontSize)||0;
      var main=/^(UNBOUND|SOURCE-BOUND|WAIT|[0-9][0-9,\.]+)$/.test(up);
      if(main || fs>=18){candidates.push({el:el,score:(main?50:0)+fs*3-top/5});}
    });
    candidates.sort(function(a,b){return b.score-a.score;});
    return candidates.length?candidates[0].el:null;
  }
  function ensureMeta(card,valueNode){
    var m=card.querySelector(':scope > .zel-v50-live-meta');
    if(!m){
      m=document.createElement('div'); m.className='zel-v50-live-meta';
      if(valueNode && valueNode.parentNode===card){ valueNode.insertAdjacentElement('afterend',m); }
      else if(valueNode){ valueNode.parentNode.insertBefore(m,valueNode.nextSibling); }
      else { card.insertBefore(m,card.firstChild); }
    }
    return m;
  }
  function railLike(el,card){
    if(!visible(el)) return false;
    if(el.closest('.zel-v50-native-chart')) return false;
    if(el.matches('canvas,svg,path,button,input,a')) return false;
    var txt=allVisibleText(el); if(txt.length>0) return false;
    var r=el.getBoundingClientRect(), cr=card.getBoundingClientRect();
    if(r.width<Math.min(110,cr.width*.35) || r.height>18 || r.height<2) return false;
    var cs=getComputedStyle(el);
    var bg=(cs.backgroundColor||'')+' '+(cs.borderTopColor||'')+' '+(cs.boxShadow||'');
    return /rgb\(|rgba\(|#/.test(bg) || r.height<=8;
  }
  function hideStaticRails(card){
    Array.prototype.slice.call(card.querySelectorAll('*')).forEach(function(el){
      if(railLike(el,card)) el.setAttribute('data-zel-v50-hidden-static-rail','1');
    });
  }
  function firstOldRail(card){
    var nodes=Array.prototype.slice.call(card.querySelectorAll('*'));
    for(var i=0;i<nodes.length;i++){ if(railLike(nodes[i],card)) return nodes[i]; }
    return null;
  }
  function ensureChart(card,valueNode){
    var wrap=card.querySelector(':scope > .zel-v50-native-chart');
    if(!wrap){
      wrap=document.createElement('div');
      wrap.className='zel-v50-native-chart';
      wrap.innerHTML='<canvas class="zel-v50-native-canvas" aria-hidden="true"></canvas>';
      var rail=firstOldRail(card);
      if(rail && rail.parentNode){ rail.parentNode.insertBefore(wrap,rail); }
      else if(valueNode && valueNode.parentNode){ valueNode.parentNode.insertBefore(wrap,valueNode.nextSibling); }
      else { card.appendChild(wrap); }
    }
    return wrap.querySelector('canvas');
  }
  function draw(canvas,st){
    if(!canvas || !st) return;
    var wrap=canvas.parentElement;
    var rect=wrap.getBoundingClientRect();
    var w=Math.max(180,Math.floor(rect.width));
    var h=Math.max(48,Math.floor(rect.height));
    var dpr=Math.min(2,window.devicePixelRatio||1);
    if(canvas.width!==Math.floor(w*dpr)||canvas.height!==Math.floor(h*dpr)){
      canvas.width=Math.floor(w*dpr); canvas.height=Math.floor(h*dpr);
      canvas.style.width=w+'px'; canvas.style.height=h+'px';
    }
    var ctx=canvas.getContext('2d');
    ctx.setTransform(dpr,0,0,dpr,0,0);
    ctx.clearRect(0,0,w,h);
    ctx.lineWidth=1;
    ctx.strokeStyle='rgba(125,220,255,.16)';
    for(var g=1;g<4;g++){var gy=Math.round((h*g)/4)+.5;ctx.beginPath();ctx.moveTo(0,gy);ctx.lineTo(w,gy);ctx.stroke();}
    var pts=st.points||[];
    if(!pts.length){return;}
    var vals=pts.map(function(p){return p.p;});
    var min=Math.min.apply(null,vals), max=Math.max.apply(null,vals);
    if(min===max){min-=Math.max(1,min*.0008);max+=Math.max(1,max*.0008);}
    var pad=7;
    function x(i){return pts.length===1?w-4:pad+(w-pad*2)*(i/(pts.length-1));}
    function y(v){return pad+(h-pad*2)*(1-(v-min)/(max-min));}
    var grad=ctx.createLinearGradient(0,0,0,h);
    grad.addColorStop(0,'rgba(0,255,220,.34)'); grad.addColorStop(1,'rgba(0,255,220,0)');
    ctx.beginPath();
    pts.forEach(function(p,i){var xx=x(i), yy=y(p.p); if(i===0)ctx.moveTo(xx,yy); else ctx.lineTo(xx,yy);});
    ctx.lineTo(x(pts.length-1),h-pad); ctx.lineTo(x(0),h-pad); ctx.closePath(); ctx.fillStyle=grad; ctx.fill();
    ctx.beginPath();
    pts.forEach(function(p,i){var xx=x(i), yy=y(p.p); if(i===0)ctx.moveTo(xx,yy); else ctx.lineTo(xx,yy);});
    ctx.strokeStyle='rgba(83,246,255,.96)'; ctx.lineWidth=2; ctx.lineJoin='round'; ctx.lineCap='round'; ctx.stroke();
    var last=pts[pts.length-1];
    ctx.beginPath(); ctx.arc(x(pts.length-1),y(last.p),3.3,0,Math.PI*2); ctx.fillStyle='rgba(0,255,196,.95)'; ctx.fill();
  }
  function render(sym){
    var card=findCard(sym); if(!card) return;
    card.setAttribute(PATCH_ATTR,sym);
    card.classList.add('zel-v50-live-card');
    var st=state[sym];
    var val=primaryValueNode(card,sym);
    if(val && st && st.price!==null){
      val.textContent=fmtPrice(st.price);
      val.classList.add('zel-v50-price-node');
    }
    var meta=ensureMeta(card,val||symbolNode(card,sym));
    if(st && st.price!==null){
      meta.textContent='LIVE '+(st.src||'exchange')+' · '+fmtDelta(st)+' · ticks '+st.ticks+' · age '+Math.max(0,now()-st.ts)+'ms';
      card.classList.add('zel-v50-feed-live'); card.classList.remove('zel-v50-feed-wait');
    }else{
      meta.textContent='LIVE FEED waiting · no exchange tick yet · RO';
      card.classList.add('zel-v50-feed-wait'); card.classList.remove('zel-v50-feed-live');
    }
    var canvas=ensureChart(card,val);
    hideStaticRails(card);
    draw(canvas,st);
  }
  function tickRender(){ SYMBOLS.forEach(render); }
  function cleanupLegacy(){
    var sel=['.zel-v34-source-badge','.zel-v35-source-badge','.zel-v36-live-panel','.zel-v37-live-panel','.zel-v38-live-panel','.zel-v39-live-panel','.zel-v40-live-panel','.zel-v41-live-graph','.zel-v42-live-tick-chart','.zel-v43-live-layer','.zel-v44-live-layer','.zel-v45-live-layer','.zel-v46-live-canvas-wrap','.zel-v47-native-spark-wrap','.zel-v48-native-feed-block','.zel-v49-live-canvas'].join(',');
    document.querySelectorAll(sel).forEach(function(el){el.setAttribute('data-zel-v50-kill','1');});
  }
  function boot(){
    cleanupLegacy();
    restPollAll(); startWs();
    setInterval(restPollAll,3500);
    setInterval(function(){cleanupLegacy();tickRender();},500);
    var mo=new MutationObserver(function(){cleanupLegacy();tickRender();});
    mo.observe(document.documentElement,{childList:true,subtree:true});
    tickRender();
  }
  if(document.readyState==='loading') document.addEventListener('DOMContentLoaded',boot); else boot();
})();
