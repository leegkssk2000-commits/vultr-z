(function(){
  'use strict';
  if (window.__ZEL_TEAM_INJECTION_CLEANUP_GUARD_V1__) return;
  window.__ZEL_TEAM_INJECTION_CLEANUP_GUARD_V1__ = true;

  var BAD = [
    '[class*="zel-step3"]', '[id*="zel-step3"]', '[data-zel-step3]',
    '[class*="team_stack_polish"]', '[id*="team_stack_polish"]',
    '.zui-team-overlay-modal-v4', '#zui-team-overlay-modal-v4',
    '[data-zui-team-modal]', '[data-zui-team-overlay]'
  ];

  function killLegacyTeamResidue(){
    try {
      if (typeof window.__zuiTeamOverlayModalV4Destroy === 'function') {
        window.__zuiTeamOverlayModalV4Destroy();
      }
    } catch(_){ }
    try {
      document.querySelectorAll(BAD.join(',')).forEach(function(el){
        // Do not remove real orderbook cards/streams even if a future class name overlaps.
        var h = (el.outerHTML || '').slice(0, 900);
        if (/zel_live_orderbook_ws_v6|zel_btc_main_orderbook_v8|orderbook|book/i.test(h)) return;
        el.remove();
      });
    } catch(_){ }
    try {
      document.body.classList.remove('modal-open','scroll-lock','zui-scroll-lock','zops-scroll-lock');
      document.documentElement.classList.remove('modal-open','scroll-lock','zui-scroll-lock','zops-scroll-lock');
      document.body.style.overflow = '';
      document.documentElement.style.overflow = '';
    } catch(_){ }
  }

  function install(){
    killLegacyTeamResidue();
    var mo = new MutationObserver(killLegacyTeamResidue);
    mo.observe(document.documentElement, {childList:true, subtree:true});
    window.__ZEL_TEAM_INJECTION_CLEANUP_GUARD_V1_STOP__ = function(){ try{mo.disconnect();}catch(_){} };
    window.setTimeout(killLegacyTeamResidue, 250);
    window.setTimeout(killLegacyTeamResidue, 1000);
  }
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', install, {once:true});
  else install();
})();
