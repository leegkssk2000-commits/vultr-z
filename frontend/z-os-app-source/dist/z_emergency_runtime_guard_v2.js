(function(){
  if (window.__Z_EMERGENCY_STABILIZE_V2__) return;
  window.__Z_EMERGENCY_STABILIZE_V2__ = true;
  var started = Date.now();
  var maxPass = 120;
  var pass = 0;
  function mark(k,v){ try{ document.body && document.body.setAttribute(k, String(v).slice(0,180)); }catch(e){} }
  function unlock(){
    try{
      document.documentElement.style.overflow = 'auto';
      document.documentElement.style.pointerEvents = 'auto';
      if (document.body) {
        document.body.style.overflow = 'auto';
        document.body.style.position = '';
        document.body.style.pointerEvents = 'auto';
        document.body.style.touchAction = 'auto';
      }
    }catch(e){}
  }
  function killLegacyTeamPatchNodes(){
    try{
      var sel = [
        '[data-zui-team-modal]',
        '[data-zui-team-overlay]',
        '[data-zui-team-root]',
        '[class*="zel-step3"]',
        '[class*="zuiTeamOverlay"]',
        '[class*="zui-team-overlay"]'
      ].join(',');
      document.querySelectorAll(sel).forEach(function(n){
        if (!n || n.closest('[data-zr-route-teams-panel]')) return;
        n.remove();
      });
    }catch(e){}
  }
  function ensureStyle(){
    try{
      if (document.getElementById('z-emergency-stabilize-v2-style')) return;
      var s = document.createElement('style');
      s.id = 'z-emergency-stabilize-v2-style';
      s.textContent = 'html,body,#root{min-height:100vh!important;background:#020611!important}body{overflow-y:auto!important;overscroll-behavior:auto!important}[data-zui-team-modal],[data-zui-team-overlay],[data-zui-team-root],[class*="zel-step3"],[class*="zuiTeamOverlay"],[class*="zui-team-overlay"]{display:none!important;pointer-events:none!important}';
      document.head && document.head.appendChild(s);
    }catch(e){}
  }
  function clearCachesOnce(){
    try{
      if (sessionStorage.getItem('z_emergency_stabilize_v2_cache_done') === '1') return;
      sessionStorage.setItem('z_emergency_stabilize_v2_cache_done','1');
      if (navigator.serviceWorker && navigator.serviceWorker.getRegistrations) {
        navigator.serviceWorker.getRegistrations().then(function(rs){ rs.forEach(function(r){ try{ r.unregister(); }catch(e){} }); });
      }
      if (window.caches && caches.keys) {
        caches.keys().then(function(keys){ keys.forEach(function(k){ try{ caches.delete(k); }catch(e){} }); });
      }
      mark('data-z-cache-clear','requested');
    }catch(e){ mark('data-z-cache-clear-error', e && e.message || 'cache'); }
  }
  function blackScreenWatch(){
    try{
      var root = document.getElementById('root');
      var txt = root ? String(root.innerText || root.textContent || '').trim() : '';
      if (Date.now() - started > 15000 && (!root || txt.length < 3)) {
        mark('data-z-black-screen','detected');
        if (sessionStorage.getItem('z_emergency_stabilize_v2_reloaded') !== '1') {
          sessionStorage.setItem('z_emergency_stabilize_v2_reloaded','1');
          var sep = location.search ? '&' : '?';
          location.replace(location.origin + location.pathname + location.search + sep + 'zfix=' + Date.now() + location.hash);
        }
      }
    }catch(e){ mark('data-z-black-screen-error', e && e.message || 'watch'); }
  }
  window.addEventListener('error', function(e){ mark('data-z-last-runtime-error', e && e.message || 'error'); });
  window.addEventListener('unhandledrejection', function(e){ mark('data-z-last-runtime-error', e && e.reason || 'promise'); });
  ensureStyle();
  clearCachesOnce();
  unlock();
  killLegacyTeamPatchNodes();
  var id = setInterval(function(){
    pass += 1;
    ensureStyle();
    unlock();
    killLegacyTeamPatchNodes();
    blackScreenWatch();
    if (pass >= maxPass) clearInterval(id);
  }, 1000);
})();
