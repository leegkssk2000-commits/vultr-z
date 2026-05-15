/* ZEL APP V48 Advanced Stack Compact Audit
 * App-only browser runtime. No orders. No server route mutation.
 * Replaces the broken recursive ZEL DECISION STACK visual with a compact account/guard/audit panel.
 */
(function(){
  'use strict';
  var VER='V48';
  var CF_URL='https://liqo-canonical-signed-snapshot.tv-sign-proxy.workers.dev/snapshot';
  var SYMBOLS=['BTCUSDT','ETHUSDT','SOLUSDT','XRPUSDT','LINKUSDT'];
  var state={cf:null, cfAt:0, ex:{}, lastRender:0};

  function now(){return Date.now();}
  function txt(n){return (n && n.textContent || '').replace(/\s+/g,' ').trim();}
  function qsa(sel,root){return Array.prototype.slice.call((root||document).querySelectorAll(sel));}
  function isNum(v){return typeof v==='number' && isFinite(v);}
  function num(v){
    if(v===null || v===undefined || v==='') return null;
    if(typeof v==='number') return isFinite(v)?v:null;
    var s=String(v).replace(/,/g,'').replace(/%/g,'').replace(/x$/i,'').trim();
    var m=s.match(/-?\d+(?:\.\d+)?/);
    if(!m) return null;
    var n=Number(m[0]);
    return isFinite(n)?n:null;
  }
  function fmt(v,d){
    if(!isNum(v)) return '—';
    var abs=Math.abs(v);
    var dec=(d!==undefined)?d:(abs>=1000?1:abs>=100?3:abs>=10?3:abs>=1?4:5);
    return v.toLocaleString(undefined,{maximumFractionDigits:dec,minimumFractionDigits:0});
  }
  function pct(v){return isNum(v)?(v.toFixed(Math.abs(v)<1?2:1)+'%'):'—';}
  function shortAge(ms){
    if(!isNum(ms)) return '—';
    if(ms<1000) return Math.max(0,Math.round(ms))+'ms';
    if(ms<60000) return Math.round(ms/1000)+'s';
    return Math.round(ms/60000)+'m';
  }
  function pick(obj, paths){
    for(var i=0;i<paths.length;i++){
      var p=paths[i].split('.'), cur=obj, ok=true;
      for(var j=0;j<p.length;j++){
        if(cur && Object.prototype.hasOwnProperty.call(cur,p[j])) cur=cur[p[j]]; else {ok=false;break;}
      }
      if(ok && cur!==undefined && cur!==null && cur!=='') return cur;
    }
    return null;
  }
  function normalizeCf(raw){
    if(!raw || typeof raw!=='object') return null;
    var p=raw.payload && typeof raw.payload==='object' ? raw.payload : raw;
    var live=raw.live_account || p.live_account || raw.live || p.live || {};
    var virt=raw.virtual_account || p.virtual_account || raw.virtual || p.virtual || {};
    var symbol=pick(p,['symbol','ticker','s']) || pick(raw,['symbol','ticker']);
    var source=raw.source || p.source || 'cf';
    var price=num(pick(p,['price','mark_price','last','last_price','close']));
    var pos=num(pick(p,['pos_pct','position_pct','pos','position_percent']));
    var lev=num(pick(p,['lev','leverage']));
    var liq=num(pick(p,['liq_buffer_pct','liq_buffer','liquidation_buffer_pct']));
    var funding=num(pick(p,['funding_8h_pct','funding8h','funding_rate','funding']));
    var ddDay=num(pick(p,['DD_day_pct','dd_day_pct','drawdown_day_pct']));
    var ddTotal=num(pick(p,['DD_total_pct','dd_total_pct','drawdown_total_pct']));
    var ts=num(pick(p,['source_ts_ms','ts_ms','timestamp_ms','updated_ts','updated_ts_ms']));
    var entry=pick(p,['entry_ts','entry_time','open_ts']);
    var hash=pick(raw,['source_hash','hash','payload_hash']) || pick(p,['source_hash','hash','payload_hash']);
    return {
      ok:!!(raw.ok!==false && symbol), source:source, symbol:symbol, price:price, pos:pos, lev:lev, liq:liq,
      funding:funding, ddDay:ddDay, ddTotal:ddTotal, source_ts_ms:ts, entry_ts:entry, hash:hash,
      live:live||{}, virtual:virt||{}, raw:raw
    };
  }
  function fetchCf(){
    var t=now();
    if(t-state.cfAt<1500) return;
    state.cfAt=t;
    fetch(CF_URL+'?v='+t,{cache:'no-store',mode:'cors'})
      .then(function(r){return r.ok?r.json():null;})
      .then(function(j){var c=normalizeCf(j); if(c) state.cf=c;})
      .catch(function(){/* app-only fallback: DOM/exchange only */});
  }

  function findSymbolCard(symbol){
    var nodes=qsa('section,article,div');
    var best=null, bestScore=-1;
    for(var i=0;i<nodes.length;i++){
      var n=nodes[i], s=txt(n);
      if(s.indexOf(symbol)<0) continue;
      if(s.indexOf('LIVE FUTURES')<0 && s.indexOf('ORDER RO')<0) continue;
      var r=n.getBoundingClientRect();
      if(r.width<120 || r.height<80 || r.height>900) continue;
      var score=0;
      if(s.indexOf('LIVE FUTURES')>=0) score+=10;
      if(s.indexOf('ORDER RO')>=0) score+=8;
      score-=Math.abs(r.height-260)/100;
      score-=Math.abs(r.width-420)/100;
      if(score>bestScore){best=n; bestScore=score;}
    }
    return best;
  }
  function readExchangeCard(symbol){
    var card=findSymbolCard(symbol);
    if(!card) return null;
    var s=txt(card);
    var price=null;
    var lines=s.split(' ');
    for(var i=0;i<lines.length;i++){
      if(lines[i]===symbol){
        for(var j=i+1;j<Math.min(lines.length,i+8);j++){
          var n=num(lines[j]);
          if(isNum(n)){ price=n; break; }
        }
        break;
      }
    }
    if(!isNum(price)){
      var m=s.match(/\b\d{1,3}(?:,\d{3})*(?:\.\d+)?\b/);
      if(m) price=num(m[0]);
    }
    var ticks=null;
    var tm=s.match(/ticks\s*(\d+)/i); if(tm) ticks=num(tm[1]);
    var chg=null;
    var cm=s.match(/(-?\d+(?:\.\d+)?)%/); if(cm) chg=num(cm[1]);
    return {symbol:symbol, price:price, ticks:ticks, change:chg, seen:now(), card:card};
  }
  function refreshExchange(){
    SYMBOLS.forEach(function(sym){ var c=readExchangeCard(sym); if(c) state.ex[sym]=c; });
  }

  function findAdvancedHost(){
    var nodes=qsa('section,article,div');
    var best=null, bestScore=-999;
    for(var i=0;i<nodes.length;i++){
      var n=nodes[i], s=txt(n);
      if(s.indexOf('Advanced ZEL stack')<0) continue;
      var r=n.getBoundingClientRect();
      if(r.width<180 || r.height<35 || r.height>1800) continue;
      var score=0;
      if(s.indexOf('live · virtual')>=0 || s.indexOf('live')>=0) score+=10;
      if(s.indexOf('ZEL DECISION STACK')>=0) score+=20;
      if(s.indexOf('LIVE / REAL')>=0) score+=5;
      score+=Math.min(r.height,700)/100;
      score-=Math.abs(r.width-520)/200;
      if(score>bestScore){best=n; bestScore=score;}
    }
    return best;
  }
  function removeOldStackBlocks(host){
    if(!host) return;
    qsa('section,article,div',host).forEach(function(n){
      if(n.id==='zel-v48-adv-stack') return;
      if(n.closest && n.closest('#zel-v48-adv-stack')) return;
      var s=txt(n);
      if(s.indexOf('ZEL DECISION STACK')>=0 || s.indexOf('LIVE / REAL DATA HOLD')>=0 || s.indexOf('exchange visual')>=0){
        var r=n.getBoundingClientRect();
        if(r.width>80 && r.height>40) n.classList.add('zel-v48-hidden-old');
      }
    });
  }
  function ensurePanel(host){
    if(!host) return null;
    removeOldStackBlocks(host);
    var p=document.getElementById('zel-v48-adv-stack');
    if(p && host.contains(p)) return p;
    p=document.createElement('div');
    p.id='zel-v48-adv-stack';
    p.className='zel-v48-stack';
    var headerChild=null;
    for(var i=0;i<host.children.length;i++){
      if(txt(host.children[i]).indexOf('Advanced ZEL stack')>=0){ headerChild=host.children[i]; break; }
    }
    if(headerChild && headerChild.parentNode===host) headerChild.insertAdjacentElement('afterend',p);
    else host.appendChild(p);
    return p;
  }

  function liveMetrics(sym){
    var cf=state.cf && String(state.cf.symbol||'').toUpperCase()===sym ? state.cf : null;
    var ex=state.ex[sym] || null;
    var price=(ex&&isNum(ex.price))?ex.price:(cf&&isNum(cf.price)?cf.price:null);
    var source=(ex&&isNum(ex.price))?'exchange':(cf?'cf':'pending');
    var pos=cf&&isNum(cf.pos)?cf.pos:null;
    var lev=cf&&isNum(cf.lev)?cf.lev:null;
    var liq=cf&&isNum(cf.liq)?cf.liq:null;
    var funding=cf&&isNum(cf.funding)?cf.funding:null;
    var dd=cf&&isNum(cf.ddDay)?cf.ddDay:null;
    var age=null;
    if(cf&&isNum(cf.source_ts_ms)) age=Math.max(0,now()-cf.source_ts_ms);
    else if(ex&&isNum(ex.seen)) age=Math.max(0,now()-ex.seen);
    return {sym:sym, cf:cf, ex:ex, price:price, source:source, pos:pos, lev:lev, liq:liq, funding:funding, dd:dd, age:age};
  }
  function virtualMetrics(cf){
    var v=(cf&&cf.virtual)||{};
    var eq=num(pick(v,['virtual_equity_usdt','equity','current_balance_usdt','balance','wallet_balance']));
    var vp=num(pick(v,['pos_pct','position_pct','virtual_pos_pct']));
    var vl=num(pick(v,['lev','leverage','virtual_lev']));
    var pnl=num(pick(v,['virtual_pnl_pct','pnl_pct','pnl','virtual_asset_pnl']));
    return {equity:eq, pos:vp, lev:vl, pnl:pnl};
  }
  function guardStatus(m){
    var missing=[];
    if(!isNum(m.pos)) missing.push('pos');
    if(!isNum(m.lev)) missing.push('lev');
    if(!isNum(m.liq)) missing.push('liq');
    if(!isNum(m.funding)) missing.push('funding');
    var proof=m.cf && (m.cf.hash || m.cf.raw && (m.cf.raw.receipt_hash || m.cf.raw.source_hash)) ? 'bound' : 'pending';
    var decision=missing.length ? 'DATA HOLD' : 'SOURCE BOUND';
    return {decision:decision, proof:proof, missing:missing};
  }
  function render(){
    var host=findAdvancedHost();
    if(!host) return;
    var panel=ensurePanel(host); if(!panel) return;
    var sym='BTCUSDT';
    var m=liveMetrics(sym), v=virtualMetrics(m.cf), g=guardStatus(m);
    var status=g.decision==='SOURCE BOUND'?'SOURCE BOUND':'READ-ONLY HOLD';
    var audit='feed '+m.source+' · proof '+g.proof+' · hash '+(m.cf&&m.cf.hash?'linked':'pending')+' · age '+shortAge(m.age);
    var missing=g.missing.length?('missing '+g.missing.join('/')):'min-data complete';
    panel.innerHTML=''
      +'<div class="zel-v48-head">'
        +'<div><div class="zel-v48-kicker">Advanced ZEL stack</div>'
        +'<div class="zel-v48-title">Live / Virtual / Guard</div>'
        +'<div class="zel-v48-sub">exchange feed는 시각·호가 전용, 최종 ZEL 액션은 CF/GS proof 기준 read-only.</div></div>'
        +'<div class="zel-v48-pill">'+status+'</div>'
      +'</div>'
      +'<div class="zel-v48-grid">'
        +'<div class="zel-v48-card" data-kind="live"><div class="zel-v48-label"><span>Live account</span><span>'+sym+'</span></div>'
          +'<div class="zel-v48-value">'+fmt(m.price)+'</div>'
          +'<div class="zel-v48-row">'
            +'<div class="zel-v48-chip">POS <b>'+pct(m.pos)+'</b></div>'
            +'<div class="zel-v48-chip">LEV <b>'+(isNum(m.lev)?fmt(m.lev,1)+'x':'—')+'</b></div>'
            +'<div class="zel-v48-chip">LIQ <b>'+pct(m.liq)+'</b></div>'
            +'<div class="zel-v48-chip">FUND <b>'+pct(m.funding)+'</b></div>'
          +'</div></div>'
        +'<div class="zel-v48-card" data-kind="virtual"><div class="zel-v48-label"><span>Virtual account</span><span>paper</span></div>'
          +'<div class="zel-v48-value">'+(isNum(v.equity)?('$'+fmt(v.equity,2)):'—')+'</div>'
          +'<div class="zel-v48-row">'
            +'<div class="zel-v48-chip">V.POS <b>'+pct(v.pos)+'</b></div>'
            +'<div class="zel-v48-chip">V.LEV <b>'+(isNum(v.lev)?fmt(v.lev,1)+'x':'—')+'</b></div>'
            +'<div class="zel-v48-chip">V.PNL <b>'+pct(v.pnl)+'</b></div>'
            +'<div class="zel-v48-chip">DD <b>'+pct(m.dd)+'</b></div>'
          +'</div></div>'
        +'<div class="zel-v48-card" data-kind="guard"><div class="zel-v48-label"><span>Execution guard</span><span>orders</span></div>'
          +'<div class="zel-v48-value">ORDER RO · '+g.decision+'</div>'
          +'<div class="zel-v48-row">'
            +'<div class="zel-v48-chip warn">PROOF <b>'+g.proof+'</b></div>'
            +'<div class="zel-v48-chip warn">CHECK <b>'+missing+'</b></div>'
          +'</div></div>'
        +'<div class="zel-v48-card" data-kind="market"><div class="zel-v48-label"><span>5-card live feed</span><span>visual</span></div>'
          +'<div class="zel-v48-value">BTC · ETH · SOL · XRP · LINK</div>'
          +'<div class="zel-v48-note">시장카드 호가·가격은 거래소 live feed로 갱신. 포지션/레버리지는 CF/GS source가 있을 때만 채움.</div></div>'
      +'</div>'
      +'<div class="zel-v48-audit">'+audit+'</div>';
  }
  function boot(){
    if(document.getElementById('zel-v48-css-marker')) return;
    var marker=document.createElement('meta'); marker.id='zel-v48-css-marker'; marker.setAttribute('data-zel',VER); document.head.appendChild(marker);
    fetchCf(); refreshExchange(); render();
    setInterval(function(){ fetchCf(); refreshExchange(); render(); }, 1000);
    var mo=new MutationObserver(function(){
      var t=now(); if(t-state.lastRender<400) return; state.lastRender=t;
      refreshExchange(); render();
    });
    mo.observe(document.documentElement,{childList:true,subtree:true,characterData:true});
  }
  if(document.readyState==='loading') document.addEventListener('DOMContentLoaded',boot); else boot();
})();
