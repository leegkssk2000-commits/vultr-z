/* ZEL_APP_V34_3_NO_FLOAT_BADGE_MOBILE_SAFE
   Removes duplicate SOURCE BOUND floating badges only. Keeps source JSON/runtime binding intact. */
(function(){
  'use strict';
  var PATCH='ZEL_APP_V34_3_NO_FLOAT_BADGE_MOBILE_SAFE';
  var badgeText=/SOURCE\s+(BOUND|HOLD)\s+V\d+/i;
  var statusText=/(BTCUSDT|ETHUSDT|SOLUSDT|XRPUSDT|LINKUSDT).*(price|pos|lev|age_ms)|(price|pos|lev|age_ms).*(BTCUSDT|ETHUSDT|SOLUSDT|XRPUSDT|LINKUSDT)/i;
  var directSelectors=[
    '#zel-v34-source-badge',
    '#zel-source-runtime-badge',
    '#zel-runtime-source-badge',
    '.zel-source-runtime-badge',
    '.zel-runtime-source-badge',
    '.zel-v34-source-badge',
    '[data-zel-patch*="BADGE_MOBILE_CLEAN"]',
    '[data-zel-patch="ZEL_APP_V34_2_BADGE_MOBILE_CLEAN"]'
  ];
  function txt(el){try{return (el.innerText||el.textContent||'').replace(/\s+/g,' ').trim();}catch(e){return '';}}
  function isDiagBadge(el){
    if(!el||el===document.body||el===document.documentElement) return false;
    var idc=((el.id||'')+' '+(el.className||'')+' '+(el.getAttribute('data-zel-patch')||'')).toLowerCase();
    if(/zel-v34-source-badge|source-runtime-badge|runtime-source-badge|badge_mobile_clean/.test(idc)) return true;
    var t=txt(el);
    if(!badgeText.test(t) || !statusText.test(t)) return false;
    try{
      var cs=getComputedStyle(el), r=el.getBoundingClientRect();
      var fixed=(cs.position==='fixed'||cs.position==='sticky');
      var nearBottom=(r.top>(window.innerHeight-190) || r.bottom>(window.innerHeight-8));
      var small=(r.width<=Math.min(980,window.innerWidth) && r.height<=120);
      var childLight=(el.children?el.children.length:0)<=12;
      return (fixed||nearBottom) && small && childLight;
    }catch(e){return false;}
  }
  function kill(el){
    try{
      el.setAttribute('data-zel-hidden-by',PATCH);
      el.style.setProperty('display','none','important');
      el.style.setProperty('visibility','hidden','important');
      el.style.setProperty('opacity','0','important');
      el.style.setProperty('pointer-events','none','important');
      if(el.id==='zel-v34-source-badge') el.remove();
    }catch(e){}
  }
  function cleanup(){
    try{directSelectors.forEach(function(s){document.querySelectorAll(s).forEach(kill);});}catch(e){}
    try{
      var nodes=document.querySelectorAll('body *');
      for(var i=0;i<nodes.length;i++){ if(isDiagBadge(nodes[i])) kill(nodes[i]); }
    }catch(e){}
  }
  function boot(){
    cleanup();
    setInterval(cleanup,500);
    try{
      new MutationObserver(cleanup).observe(document.body,{childList:true,subtree:true,attributes:true,attributeFilter:['class','id','style','data-zel-patch']});
    }catch(e){}
    window.__ZEL_APP_NO_FLOAT_BADGE__={patch:PATCH,active:true,reason:'floating diagnostic badge hidden; source binding unchanged'};
  }
  if(document.readyState==='loading') document.addEventListener('DOMContentLoaded',boot,{once:true}); else boot();
})();
