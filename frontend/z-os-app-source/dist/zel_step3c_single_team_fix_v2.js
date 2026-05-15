(function(){
  'use strict';
  var KEY='__ZEL_STEP3C_SINGLE_TEAM_FIX_V2__';
  if (window[KEY] && window[KEY].installed) return;
  var state = window[KEY] = {
    installed: true,
    version: '20260515c2single',
    removed: 0,
    lastSweep: 0,
    note: 'removes failed Step3-C injected team route board; leaves native team cards/overlays intact'
  };

  function txt(n){ return ((n && n.textContent) || '').replace(/\s+/g,' ').trim(); }
  function isOldInjectedBoard(el){
    if (!el || el.nodeType !== 1) return false;
    if (el.classList && (el.classList.contains('zel-team-board-c') || el.classList.contains('zel-step3c-route-board'))) return true;
    if (el.getAttribute && el.getAttribute('data-zel-step3c') === 'route-board') return true;
    var t = txt(el).slice(0,260);
    return /ZEL TEAM ROUTE BOARD/i.test(t) && /Step3-C overlay-only/i.test(t);
  }
  function removeOldInjectedBoards(root){
    var base = (root && root.querySelectorAll) ? root : document;
    var list = [];
    try {
      list = Array.prototype.slice.call(base.querySelectorAll('.zel-team-board-c,.zel-step3c-route-board,[data-zel-step3c="route-board"]'));
    } catch(e) {}
    // Text fallback for cached DOM where class was altered by minification or copied nodes.
    try {
      var candidates = Array.prototype.slice.call(base.querySelectorAll('div,section,article,aside'));
      for (var i=0;i<candidates.length;i++) {
        if (isOldInjectedBoard(candidates[i])) list.push(candidates[i]);
      }
    } catch(e) {}
    var seen = new Set();
    for (var j=0;j<list.length;j++) {
      var el = list[j];
      if (!el || seen.has(el) || !isOldInjectedBoard(el)) continue;
      seen.add(el);
      try { el.remove(); state.removed++; } catch(e) {
        try { el.parentNode && el.parentNode.removeChild(el); state.removed++; } catch(_e) {}
      }
    }
    state.lastSweep = Date.now();
    return state.removed;
  }

  function sweep(){ removeOldInjectedBoards(document); }
  function schedule(){
    if (state.timer) return;
    state.timer = setTimeout(function(){ state.timer=0; sweep(); }, 40);
  }

  function bindTeamClicks(){
    if (state.boundClicks) return;
    state.boundClicks = true;
    document.addEventListener('click', function(ev){
      var el = ev.target && ev.target.closest ? ev.target.closest('button,[role="button"],a,div,section,article') : null;
      if (!el) return;
      var t = txt(el).slice(0,160);
      if (/\b(Alpha|Beta|Gamma|Delta)\b/i.test(t) || /TEAM OVERLAY|Lane\s*\/\s*Team/i.test(t)) {
        setTimeout(sweep, 0);
        setTimeout(sweep, 80);
        setTimeout(sweep, 240);
      }
    }, true);
  }

  function scan(){
    sweep();
    var boards = document.querySelectorAll ? document.querySelectorAll('.zel-team-board-c,.zel-step3c-route-board,[data-zel-step3c="route-board"]').length : -1;
    var oldText = 0;
    try {
      oldText = Array.prototype.slice.call(document.querySelectorAll('div,section,article,aside')).filter(isOldInjectedBoard).length;
    } catch(e) {}
    return {
      installed: true,
      version: state.version,
      removedTotal: state.removed,
      badBoardClassCount: boards,
      badBoardTextCount: oldText,
      ok: boards === 0 && oldText === 0,
      lastSweep: state.lastSweep
    };
  }

  window.__ZEL_STEP3C_SINGLE_TEAM_FIX_SCAN__ = scan;
  window.__ZEL_STEP3C_SINGLE_TEAM_FIX_SWEEP__ = sweep;

  bindTeamClicks();
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', sweep, {once:true});
  sweep();
  setTimeout(sweep, 120);
  setTimeout(sweep, 600);
  try {
    var mo = new MutationObserver(function(muts){
      for (var i=0;i<muts.length;i++) {
        if (muts[i].addedNodes && muts[i].addedNodes.length) { schedule(); break; }
      }
    });
    mo.observe(document.documentElement || document.body, {childList:true, subtree:true});
    state.observer = true;
  } catch(e) { state.observer = false; }
})();
