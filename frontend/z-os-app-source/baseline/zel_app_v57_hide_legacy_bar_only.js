/* ZEL APP V57: remove old static card rail only. Does not touch live feed, price, chart, proof, nginx, caddy, or systemd. */
(function(){
  'use strict';

  var SYMBOLS = ['BTCUSDT','ETHUSDT','SOLUSDT','XRPUSDT','LINKUSDT'];
  var LAST = 0;

  function hasSymbolText(el){
    var t = (el && el.innerText || '').slice(0, 1400);
    for (var i=0; i<SYMBOLS.length; i++) if (t.indexOf(SYMBOLS[i]) >= 0) return true;
    return false;
  }

  function isCardLike(el){
    if (!el || el.nodeType !== 1) return false;
    var r = el.getBoundingClientRect();
    if (r.width < 180 || r.height < 120 || r.height > 900) return false;
    if (!hasSymbolText(el)) return false;
    var s = getComputedStyle(el);
    var radius = parseFloat(s.borderRadius || '0') || 0;
    var border = (s.borderColor || '') + ' ' + (s.boxShadow || '');
    return radius >= 8 || /0,\s*255|cyan|0,\s*210|64,\s*220|34,\s*211/i.test(border);
  }

  function nearestCard(el){
    var cur = el;
    for (var depth=0; cur && depth<8; depth++, cur=cur.parentElement){
      if (isCardLike(cur)) return cur;
    }
    return null;
  }

  function looksLikeLegacyRail(el, card){
    if (!el || el.nodeType !== 1 || !card) return false;
    if (el.dataset && el.dataset.zv57Keep === '1') return false;

    var tag = (el.tagName || '').toLowerCase();
    if (tag === 'svg' || tag === 'canvas' || tag === 'path' || tag === 'line' || tag === 'polyline') return false;
    if ((el.innerText || '').trim().length > 0) return false;
    if (el.querySelector && el.querySelector('svg,canvas,path,polyline,input,button,a')) return false;

    var r = el.getBoundingClientRect();
    var cr = card.getBoundingClientRect();
    if (!r.width || !r.height || !cr.width || !cr.height) return false;

    /* The unwanted bar is a long, thin standalone block inside the market card. */
    if (r.height < 2 || r.height > 10) return false;
    if (r.width < Math.max(95, cr.width * 0.38)) return false;
    if (r.width > cr.width * 0.96) return false;
    if (r.left < cr.left - 2 || r.right > cr.right + 2) return false;

    var cs = getComputedStyle(el);
    if (cs.display === 'none' || cs.visibility === 'hidden' || parseFloat(cs.opacity || '1') === 0) return false;
    if (cs.position === 'fixed' || cs.position === 'sticky') return false;

    var bg = (cs.backgroundColor || '') + ' ' + (cs.backgroundImage || '') + ' ' + (cs.borderTopColor || '') + ' ' + (cs.boxShadow || '');
    var cyanOrRail = /rgba?\(\s*(?:0|20|30|40|50|60|70|80)\s*,\s*(?:1[6-9][0-9]|2[0-5][0-9])\s*,\s*(?:1[7-9][0-9]|2[0-5][0-9])/i.test(bg)
      || /rgba?\(\s*(?:25|30|35|40|45|50|55|60)\s*,\s*(?:35|40|45|50|55|60|65)\s*,\s*(?:45|50|55|60|65|70|75)/i.test(bg)
      || /cyan|00e|00f|22d3ee|67e8f9|5eead4|0ea5e9/i.test(bg);
    if (!cyanOrRail) return false;

    var radius = parseFloat(cs.borderRadius || '0') || 0;
    return radius >= 1 || r.height <= 5;
  }

  function hideRail(el){
    if (!el || (el.dataset && el.dataset.zV57HiddenRail === '1')) return;
    try { el.setAttribute('data-z-v57-hidden-rail','1'); } catch(e) {}
    el.style.setProperty('display','none','important');
    el.style.setProperty('visibility','hidden','important');
    el.style.setProperty('height','0','important');
    el.style.setProperty('min-height','0','important');
    el.style.setProperty('max-height','0','important');
    el.style.setProperty('margin','0','important');
    el.style.setProperty('padding','0','important');
    el.style.setProperty('border','0','important');
  }

  function pass(){
    var all = document.body ? document.body.querySelectorAll('body *') : [];
    for (var i=0; i<all.length; i++){
      var el = all[i];
      var card = nearestCard(el);
      if (looksLikeLegacyRail(el, card)) hideRail(el);
    }
  }

  function schedule(){
    var now = Date.now();
    if (now - LAST < 100) return;
    LAST = now;
    requestAnimationFrame(pass);
  }

  function start(){
    pass();
    var n = 0;
    var iv = setInterval(function(){ pass(); if (++n >= 24) clearInterval(iv); }, 250);
    try {
      new MutationObserver(schedule).observe(document.documentElement, {childList:true, subtree:true, attributes:true, attributeFilter:['class','style']});
    } catch(e) {}
  }

  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', start, {once:true});
  else start();
})();
