/* ZEL APP V52 Advanced stack anchor-only overlay
 * Scope: Advanced ZEL stack only. Does NOT mutate market/orderbook cards.
 * Fix: no body fallback, no generic text deletion, no standalone blank-page render.
 */
(function(){
  'use strict';
  var VER='V52';
  var SYMBOLS=['BTCUSDT','ETHUSDT','SOLUSDT','XRPUSDT','LINKUSDT'];
  var TEAMS={
    Alpha:{tier:'Tier S',mode:'primary route',lead:'LBot',method:'MBot',venue:'OBot',safety:'SBot',score:'84',state:'active'},
    Beta:{tier:'Tier A',mode:'fallback trend/range',lead:'B-Lane',method:'Range confirm',venue:'Venue watch',safety:'Guard clean',score:'72',state:'standby'},
    Gamma:{tier:'Tier B',mode:'volatility defense',lead:'G-Lane',method:'Shock filter',venue:'Spread watch',safety:'DD veto',score:'61',state:'standby'},
    Delta:{tier:'Tier C',mode:'rollback/safe lane',lead:'D-Lane',method:'Rollback map',venue:'Route freeze',safety:'Block first',score:'54',state:'fallback'}
  };
  var activeTeam='Alpha';
  function q(sel,ctx){ return (ctx||document).querySelector(sel); }
  function qa(sel,ctx){ return Array.prototype.slice.call((ctx||document).querySelectorAll(sel)); }
  function txt(el){ return el ? (el.textContent||'').trim() : '—'; }
  function clean(v){ v=(v==null?'—':String(v)).trim(); return v || '—'; }
  function esc(s){ return String(s==null?'—':s).replace(/[&<>"]/g,function(c){return {'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c];}); }
  function hasCard(sym){ return !!q('[data-zel-v49-card="1"][data-z49-symbol="'+sym+'"],[data-zel-v46-card="1"][data-z46-symbol="'+sym+'"],[data-zel-v47-card="1"][data-z47-symbol="'+sym+'"]'); }
  function card(sym){ return q('[data-zel-v49-card="1"][data-z49-symbol="'+sym+'"],[data-zel-v46-card="1"][data-z46-symbol="'+sym+'"],[data-zel-v47-card="1"][data-z47-symbol="'+sym+'"]'); }
  function price(sym){ var c=card(sym); return clean(txt(q('[data-z49-price],[data-z46-price],[data-z47-price]',c))); }
  function accountFromCard(sym){
    var c=card(sym), out={pos:'—',lev:'—',upnl:'—',liq:'—',vpos:'—',vlev:'—',vupnl:'—',dd:'—'};
    if(!c) return out;
    qa('.z49-mini,.z47-mini,.z46-mini,span,div',c).forEach(function(el){
      var t=txt(el).replace(/\s+/g,' '); if(!t || t.length>80) return;
      var m;
      if(/^POS\s+/i.test(t) && out.pos==='—') out.pos=t.replace(/^POS\s+/i,'');
      else if(/^LEV\s+/i.test(t) && out.lev==='—') out.lev=t.replace(/^LEV\s+/i,'');
      else if(/^uPNL\s+/i.test(t) && out.upnl==='—') out.upnl=t.replace(/^uPNL\s+/i,'');
      else if(/^liq\s+/i.test(t) && out.liq==='—') out.liq=t.replace(/^liq\s+/i,'');
      else if(/^V\.POS\s+/i.test(t) && out.vpos==='—') out.vpos=t.replace(/^V\.POS\s+/i,'');
      else if(/^V\.LEV\s+/i.test(t) && out.vlev==='—') out.vlev=t.replace(/^V\.LEV\s+/i,'');
      else if(/^V\.uPNL\s+/i.test(t) && out.vupnl==='—') out.vupnl=t.replace(/^V\.uPNL\s+/i,'');
      else if(/^DD\s+/i.test(t) && out.dd==='—') out.dd=t.replace(/^DD\s+/i,'');
      else if((m=t.match(/pos\s*[:=]?\s*([\-0-9.]+%?)/i)) && out.pos==='—') out.pos=m[1];
      else if((m=t.match(/lev\s*[:=]?\s*([\-0-9.]+x?)/i)) && out.lev==='—') out.lev=m[1];
      else if((m=t.match(/u?pnl\s*[:=]?\s*([\-+0-9.,%U$]+)/i)) && out.upnl==='—') out.upnl=m[1];
    });
    return out;
  }
  function findAdvRoot(){
    // Exact anchors only. Never append to body. Never scan broad text and replace app containers.
    return q('[data-zel-v52-adv-root="1"]') || q('[data-zel-v49-adv-root="1"]') || q('[data-zel-v48-adv-root="1"]') || q('[data-zel-adv-root="1"]');
  }
  function removeBadOnly(){
    // Exact known bad injected roots only. No generic text matching.
    qa('[data-zel-v50-root="1"],[data-zel-v51-root="1"],[data-zel-v50-adv="1"],[data-zel-v51-adv="1"]').forEach(function(el){ try{el.remove();}catch(e){el.style.display='none';} });
  }
  function sourceStrip(){
    return SYMBOLS.map(function(s){ return '<span class="z52-src"><b>'+s.replace('USDT','')+'</b> '+esc(price(s))+'</span>'; }).join('');
  }
  function metricsHtml(a,prefix){
    return '<div class="z52-metrics">'
      + '<div><em>POS</em><b>'+esc(a[prefix+'pos']||a.pos)+'</b></div>'
      + '<div><em>LEV</em><b>'+esc(a[prefix+'lev']||a.lev)+'</b></div>'
      + '<div><em>uPNL</em><b>'+esc(a[prefix+'upnl']||a.upnl)+'</b></div>'
      + '<div><em>'+ (prefix?'DD':'LIQ') +'</em><b>'+esc(prefix?a.dd:a.liq)+'</b></div>'
      + '</div>';
  }
  function teamHtml(){
    var t=TEAMS[activeTeam]||TEAMS.Alpha;
    return '<section class="z52-panel z52-team"><div class="z52-panel-head"><span>TEAM OVERLAY</span><b>single active view</b></div>'
      + '<div class="z52-tabs">'+Object.keys(TEAMS).map(function(k){return '<button type="button" data-z52-team="'+k+'" class="'+(k===activeTeam?'on':'')+'">'+k+'</button>';}).join('')+'</div>'
      + '<div class="z52-team-main"><div><strong>'+activeTeam+' · '+t.tier+'</strong><p>'+t.mode+'</p></div><div class="z52-score">'+t.score+'</div></div>'
      + '<div class="z52-botgrid">'
      + '<div><b>'+t.lead+'</b><em>lead</em><span>PASS</span></div>'
      + '<div><b>'+t.method+'</b><em>method</em><span>PASS</span></div>'
      + '<div><b>'+t.venue+'</b><em>venue</em><span>WATCH</span></div>'
      + '<div><b>'+t.safety+'</b><em>safety</em><span>CLEAR</span></div>'
      + '</div></section>';
  }
  function html(){
    var sym='BTCUSDT', a=accountFromCard(sym);
    var cardsReady=SYMBOLS.filter(hasCard).length;
    return '<div class="z52-stack" data-zel-v52-stack="1">'
      + '<div class="z52-head"><div><small>ADVANCED ZEL STACK</small><h2>Live · Virtual · Guard</h2><p>시장카드/호가창은 그대로 두고, 계좌·uPNL·팀 오버레이만 압축 표시.</p></div><strong>READ-ONLY HOLD</strong></div>'
      + '<div class="z52-source-strip">'+sourceStrip()+'</div>'
      + '<div class="z52-grid">'
      + '<section class="z52-panel z52-live"><div class="z52-panel-head"><span>LIVE ACCOUNT</span><b>'+sym+'</b></div><div class="z52-big">'+esc(price(sym))+'</div>'+metricsHtml(a,'')+'</section>'
      + '<section class="z52-panel z52-virt"><div class="z52-panel-head"><span>VIRTUAL ACCOUNT</span><b>PAPER</b></div><div class="z52-big">simulation</div>'+metricsHtml(a,'v')+'</section>'
      + '<section class="z52-panel z52-guard"><div class="z52-panel-head"><span>EXECUTION GUARD</span><b>orders</b></div><h3>ORDER RO · DATA HOLD</h3><p>최종 주문/차단 판정은 CF/GS proof가 붙을 때만 갱신.</p><div class="z52-pills"><span>proof pending</span><span>route locked</span><span>guard read-only</span></div></section>'
      + teamHtml()
      + '</div><div class="z52-audit">feed exchange · proof pending · hash pending · cards '+cardsReady+'/5 · uPNL included · '+VER+'</div>'
      + '</div>';
  }
  var last='';
  function render(){
    removeBadOnly();
    var root=findAdvRoot();
    if(!root) return; // anchor-only: no blank-page standalone render.
    root.setAttribute('data-zel-v52-adv-root','1');
    var markup=html();
    if(root.getAttribute('data-z52-last')!==String(markup.length) || root.innerHTML.indexOf('data-zel-v52-stack')<0){
      root.innerHTML=markup;
      root.setAttribute('data-z52-last',String(markup.length));
    } else {
      // refresh volatile numbers without remount if layout already present
      root.innerHTML=markup;
      root.setAttribute('data-z52-last',String(markup.length));
    }
    qa('[data-z52-team]',root).forEach(function(btn){ btn.onclick=function(){ activeTeam=btn.getAttribute('data-z52-team')||'Alpha'; root.removeAttribute('data-z52-last'); render(); }; });
  }
  function start(){
    removeBadOnly(); render();
    setInterval(render,650);
    if(document.body){ new MutationObserver(function(){ removeBadOnly(); render(); }).observe(document.body,{childList:true,subtree:true}); }
  }
  if(document.readyState==='loading') document.addEventListener('DOMContentLoaded',start,{once:true}); else start();
})();
