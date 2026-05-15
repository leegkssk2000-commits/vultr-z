(function(){
  'use strict';
  var VERSION='20260515.team-dense-final.v1';
  if(window.__ZEL_TEAM_DENSE_OVERLAY_FINAL_V1__===VERSION){return;}
  window.__ZEL_TEAM_DENSE_OVERLAY_FINAL_V1__=VERSION;

  var TEAMS={
    alpha:{key:'alpha',name:'Alpha Team',state:'active',tier:'Tier S · primary trend-confirm team',desc:'Primary route team. Holds lead only while trend strength, venue state, and source proof remain inside guard.',score:'74/100',lead:'LBot',confirm:'MBot',venue:'OBot',guard:'SBot',reserve:'Delta',route:'trend-confirm',support:'MBot/OBot/SBot',mode:'primary',condition:'Stay active while trend, venue, source seal, and guard thresholds remain clean.',next:'Demote to Beta when trend edge decays or source/proof becomes stale.',lock:'advisory-only · no order mutation'},
    beta:{key:'beta',name:'Beta Team',state:'standby',tier:'Tier A · range / mean-revert team',desc:'Fallback-ready range team. Promotes only when Alpha trend edge decays and range confirmation is cleaner.',score:'74/100',lead:'MBot',confirm:'LBot',venue:'OBot',guard:'SBot',reserve:'Delta',route:'range-confirm',support:'LBot/OBot/SBot',mode:'fallback queue',condition:'Promote only if range confirmation beats Alpha decay and venue risk stays acceptable.',next:'Return to Alpha on renewed trend strength; reject if spread/slippage expands.',lock:'source-bound · orders blocked'},
    gamma:{key:'gamma',name:'Gamma Team',state:'fallback',tier:'Tier B · reclaim / recovery team',desc:'Recovery scout after failed range/trend handoff. Requires venue recovery and slippage improvement.',score:'58/100',lead:'OBot',confirm:'MBot',venue:'LBot',guard:'SBot',reserve:'Delta',route:'reclaim-probe',support:'MBot/LBot/SBot',mode:'recovery probe',condition:'Use only after reclaim evidence and venue/slippage checks clear.',next:'Reject to Delta if venue risk expands; promote only after clean recovery.',lock:'advisory-only · no app-side execution'},
    delta:{key:'delta',name:'Delta Team',state:'guard',tier:'Tier C · reserve / defensive guard',desc:'Defense-only team. Blocks or protects on stale proof, LKG defense, or drawdown/venue risk escalation.',score:'43/100',lead:'SBot',confirm:'MBot',venue:'OBot',guard:'SBot',reserve:'Manual',route:'guard-defense',support:'OBot/MBot',mode:'safety veto',condition:'Activate only for stale guard, LKG defense, drawdown, or venue-risk escalation.',next:'Release back to Alpha/Beta only after guard clears and source age is valid.',lock:'block/reduce advisory only'}
  };
  var ORDER=['alpha','beta','gamma','delta'];
  var scanCount=0;

  function esc(v){return String(v==null?'':v).replace(/[&<>"]/g,function(c){return {'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c];});}
  function chip(txt,cls){return '<span class="ztdf-chip '+(cls||'')+'">'+esc(txt)+'</span>';}

  function findAdvancedFold(){
    var byData=document.querySelector('[data-zr="advanced-zel-stack"]');
    if(byData)return byData;
    var nodes=document.querySelectorAll('details,section,div');
    for(var i=0;i<nodes.length;i++){
      var txt=(nodes[i].textContent||'').slice(0,240);
      if(txt.indexOf('Advanced ZEL stack')!==-1){return nodes[i];}
    }
    return document.querySelector('#root main')||document.querySelector('#root')||document.body;
  }

  function hideNode(el){
    if(!el||el===document.body||el.id==='ztdf-team-panel'||el.closest&&el.closest('#ztdf-team-panel'))return;
    if(el.id==='ztdf-modal-root'||(el.closest&&el.closest('#ztdf-modal-root')))return;
    el.classList.add('ztdf-hidden-native');
    el.setAttribute('data-ztdf-hidden','native-team-surface');
  }

  function likelyPanel(el){
    if(!el||el===document.body)return false;
    var t=(el.textContent||'');
    if(t.indexOf('LANE / TEAM OVERLAY')!==-1 && t.indexOf('Active / standby / fallback / rejected')!==-1)return true;
    if(t.indexOf('ALPHA BOT OVERLAY')!==-1 && t.indexOf('SBot')!==-1)return true;
    if(t.indexOf('ZEL TEAM SYSTEM REBUILD')!==-1 && t.indexOf('Route teams')!==-1)return true;
    return false;
  }

  function hideLegacySurfaces(){
    document.querySelectorAll('[data-zui-team-modal],[data-zui-team-overlay],[class*="zel-step3"],[id*="zel-step3"],[class*="zuiTeamOverlay"],[id*="zuiTeamOverlay"]').forEach(hideNode);
    var roots=document.querySelectorAll('section,details,div');
    for(var i=0;i<roots.length;i++){
      if(roots[i].id==='ztdf-team-panel'||(roots[i].closest&&roots[i].closest('#ztdf-team-panel')))continue;
      if(likelyPanel(roots[i])){
        var cur=roots[i];
        while(cur.parentElement && cur.parentElement!==document.body && likelyPanel(cur.parentElement))cur=cur.parentElement;
        hideNode(cur);
      }
    }
  }

  function card(team){
    var badgeClass=team.key==='alpha'?'active':team.key==='beta'?'standby':team.key==='gamma'?'fallback':'guard';
    return '<button type="button" class="ztdf-card" data-ztdf-team="'+team.key+'" data-team="'+team.key+'">'+
      '<div class="ztdf-card-top"><div><div class="ztdf-title">'+esc(team.name)+'</div><div class="ztdf-tier">'+esc(team.tier)+'</div></div><span class="ztdf-badge '+badgeClass+'">'+esc(team.state)+'</span></div>'+
      '<div class="ztdf-desc">'+esc(team.desc)+'</div>'+
      '<div class="ztdf-chips">'+chip('state='+team.state,badgeClass)+chip('lead='+team.lead)+chip('support='+team.support)+chip('score='+team.score)+'</div>'+
      '<div class="ztdf-mini"><div><span>Lead</span><b>'+esc(team.lead)+'</b></div><div><span>Route</span><b>'+esc(team.route)+'</b></div></div>'+
    '</button>';
  }

  function ensurePanel(){
    hideLegacySurfaces();
    var panel=document.getElementById('ztdf-team-panel');
    if(panel)return panel;
    var anchor=findAdvancedFold();
    panel=document.createElement('section');
    panel.id='ztdf-team-panel';
    panel.setAttribute('data-ztdf-version',VERSION);
    panel.setAttribute('aria-label','ZEL route team dense single overlay');
    panel.innerHTML='<div class="ztdf-head"><div><span class="ztdf-kicker">ZEL TEAM ROUTE CONTROL</span><h2>Route teams · dense single overlay</h2><p>Alpha/Beta/Gamma/Delta cards are app-bound. Tap one card: one modal only. Proof detail stays compressed.</p></div><span class="ztdf-lock">NO ORDER MUTATION</span></div>'+
      '<div class="ztdf-grid">'+ORDER.map(function(k){return card(TEAMS[k]);}).join('')+'</div>'+
      '<div class="ztdf-foot"><span>source-bound · read-only · team routing only</span><span>tap card</span></div>';
    if(anchor && anchor.tagName==='DETAILS')anchor.appendChild(panel);
    else if(anchor)anchor.appendChild(panel);
    else document.body.appendChild(panel);
    panel.addEventListener('click',function(ev){
      var btn=ev.target.closest('[data-ztdf-team]');
      if(!btn)return;
      ev.preventDefault(); ev.stopPropagation();
      openModal(btn.getAttribute('data-ztdf-team'));
    },true);
    return panel;
  }

  function modalHTML(t){
    var badgeClass=t.key==='alpha'?'hot':t.key==='beta'?'warn':t.key==='gamma'?'':'danger';
    return '<div class="ztdf-modal" data-team="'+t.key+'" role="dialog" aria-modal="true" aria-label="'+esc(t.name)+' route sheet">'+
      '<div class="ztdf-modal-head"><div><span class="ztdf-kicker">TEAM ROUTE SHEET</span><h3>'+esc(t.name)+' · '+esc(t.state)+'</h3><p>'+esc(t.tier)+' — '+esc(t.desc)+'</p></div><div class="ztdf-score"><span>score</span>'+esc(t.score)+'</div><button type="button" class="ztdf-x" data-ztdf-close>×</button></div>'+
      '<div class="ztdf-chips">'+chip('state:'+t.state,badgeClass)+chip('lead='+t.lead,'hot')+chip('confirm='+t.confirm)+chip('venue='+t.venue)+chip('guard='+t.guard,'warn')+chip(t.lock,'danger')+'</div>'+
      '<div class="ztdf-dense-grid">'+
        '<div class="ztdf-box"><strong>Role matrix</strong><div>Lead: '+esc(t.lead)+'\nConfirm: '+esc(t.confirm)+'\nVenue: '+esc(t.venue)+'\nGuard: '+esc(t.guard)+'\nReserve: '+esc(t.reserve)+'</div></div>'+
        '<div class="ztdf-box"><strong>Decision support</strong><div>Route: '+esc(t.route)+'\nMode: '+esc(t.mode)+'\nSupport: '+esc(t.support)+'\nOutput: advisory only</div></div>'+
        '<div class="ztdf-box wide"><strong>Switch condition</strong><div>'+esc(t.condition)+'\nNext: '+esc(t.next)+'</div></div>'+
        '<div class="ztdf-box wide"><strong>Execution guard</strong><div>Final action remains ZEL-owned and source-bound. App-side order mutation is blocked.</div></div>'+
      '</div>'+
      '<div class="ztdf-actions"><button type="button" class="ztdf-action" data-ztdf-zlice>Open Zlice proof</button><button type="button" class="ztdf-action" data-ztdf-close>Close</button></div>'+
      '<div class="ztdf-note"><span>dense overlay · proof compressed</span><span>read-only</span></div>'+
    '</div>';
  }

  function modalRoot(){
    var root=document.getElementById('ztdf-modal-root');
    if(root)return root;
    root=document.createElement('div');
    root.id='ztdf-modal-root';
    root.hidden=true;
    root.addEventListener('click',function(ev){
      if(ev.target===root || ev.target.closest('[data-ztdf-close]'))closeModal();
      if(ev.target.closest('[data-ztdf-zlice]')){ev.preventDefault(); closeModal(); var d=document.querySelector('[data-zr="decision-proof-snapshot"]'); if(d){d.open=true; d.scrollIntoView({block:'center',behavior:'smooth'});} }
    },true);
    document.body.appendChild(root);
    return root;
  }
  function openModal(key){var t=TEAMS[key]||TEAMS.alpha; var root=modalRoot(); root.innerHTML=modalHTML(t); root.hidden=false;}
  function closeModal(){var root=document.getElementById('ztdf-modal-root'); if(root){root.hidden=true; root.innerHTML='';}}

  function install(){
    try{ensurePanel();}catch(e){console.warn('[ztdf] install failed',e);}
  }
  function scheduledPass(){
    if(scanCount>8)return;
    scanCount+=1;
    window.requestAnimationFrame(install);
  }

  document.addEventListener('keydown',function(ev){if(ev.key==='Escape')closeModal();},true);
  if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',install,{once:true}); else install();
  [120,500,1200,2500,5000,8000].forEach(function(ms){setTimeout(scheduledPass,ms);});

  window.__ZEL_TEAM_DENSE_OVERLAY_FINAL_CHECK__=function(){
    return {
      version:VERSION,
      panel:document.querySelectorAll('#ztdf-team-panel').length,
      modalRoot:document.querySelectorAll('#ztdf-modal-root').length,
      hiddenNative:document.querySelectorAll('.ztdf-hidden-native').length,
      oldInjected:document.querySelectorAll('[data-zui-team-modal],[data-zui-team-overlay],[class*="zel-step3"],[id*="zel-step3"]').length,
      orderbooks:document.querySelectorAll('.zel-v6-book,.zel-btc-v8-card').length
    };
  };
})();
