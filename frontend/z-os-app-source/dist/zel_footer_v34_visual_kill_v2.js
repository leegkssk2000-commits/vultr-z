(function(){
  'use strict';
  if(window.__ZEL_FOOTER_V34_VISUAL_KILL_V2__) return;
  window.__ZEL_FOOTER_V34_VISUAL_KILL_V2__ = true;

  var RX = /^SOURCE\s+(HOLD|BOUND)\s+V34\s*·/i;

  function isFooterLike(el){
    try{
      var cs = getComputedStyle(el);
      var r = el.getBoundingClientRect();
      return cs.position === 'fixed' || cs.position === 'sticky' || r.top > innerHeight * 0.55 || r.bottom > innerHeight * 0.70;
    }catch(e){ return false; }
  }

  function hide(el){
    try{
      el.classList.add('zel-footer-v34-hidden');
      el.setAttribute('data-zel-footer-v34','hidden');
      el.style.setProperty('display','none','important');
      el.style.setProperty('visibility','hidden','important');
      el.style.setProperty('pointer-events','none','important');
      return 1;
    }catch(e){ return 0; }
  }

  function scan(){
    var n = 0;
    try{
      var nodes = document.querySelectorAll('[id^="zel-source-bind"],[data-zel-footer-v34],div,span,aside,footer');
      for(var i=0;i<nodes.length;i++){
        var el = nodes[i];
        var t = (el.innerText || el.textContent || '').trim();
        if(!t || t.length > 260) continue;
        if(RX.test(t) && isFooterLike(el)) n += hide(el);
      }
    }catch(e){}
    return n;
  }

  window.ZEL_FOOTER_V34_VISUAL_KILL_V2_SCAN = scan;
  scan();
  try{ new MutationObserver(scan).observe(document.documentElement,{childList:true,subtree:true,characterData:true}); }catch(e){}
  setInterval(scan, 500);
  setTimeout(scan, 50);
  setTimeout(scan, 250);
  setTimeout(scan, 1000);
})();
