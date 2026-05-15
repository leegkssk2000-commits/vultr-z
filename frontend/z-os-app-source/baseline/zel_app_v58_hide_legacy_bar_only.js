/* ZEL APP V58 - bar-only patch
 * Scope: hide legacy cyan/gray static horizontal strips inside market cards.
 * Does not remove/replace live feed JS, card title, sparkline, source/proof chips, or server routes.
 */
(function(){
  'use strict';
  var VER='V58_BAR_ONLY_PRESERVE_LIVE';
  var SYMBOLS=['BTCUSDT','ETHUSDT','SOLUSDT','XRPUSDT','LINKUSDT'];
  var ROOT=document.documentElement;
  if(ROOT.classList.contains('zel-v58-bar-only-loaded')) return;
  ROOT.classList.add('zel-v58-bar-only-loaded');

  function txt(el){return (el&&el.textContent||'').replace(/\s+/g,' ').trim();}
  function rect(el){try{return el.getBoundingClientRect();}catch(e){return {width:0,height:0,top:0,left:0,right:0,bottom:0};}}
  function css(el){try{return getComputedStyle(el);}catch(e){return null;}}
  function visible(el){
    if(!el||!el.isConnected) return false;
    var r=rect(el); if(r.width<2||r.height<1) return false;
    var c=css(el); return !c||(c.display!=='none'&&c.visibility!=='hidden'&&Number(c.opacity||1)!==0);
  }
  function hasSymbolText(el){
    var t=txt(el);
    for(var i=0;i<SYMBOLS.length;i++) if(t.indexOf(SYMBOLS[i])>=0) return true;
    return false;
  }
  function isMarketCard(el){
    if(!visible(el)) return false;
    if(!hasSymbolText(el)) return false;
    var t=txt(el);
    if(!/(sig=read_only|risk=hold|proof=missing|source-required|receipt_hash|LIVE|unbound|source-bound)/i.test(t)) return false;
    var r=rect(el);
    return r.width>=140&&r.width<=900&&r.height>=100&&r.height<=900;
  }
  function findCards(){
    var nodes=Array.prototype.slice.call(document.querySelectorAll('article,section,main div,body div'));
    var cards=[];
    nodes.forEach(function(el){
      if(isMarketCard(el)) cards.push(el);
    });
    cards.sort(function(a,b){return (rect(a).width*rect(a).height)-(rect(b).width*rect(b).height);});
    var out=[];
    cards.forEach(function(c){
      if(out.some(function(p){return p.contains(c);})){return;}
      out.push(c);
    });
    return out.slice(0,12);
  }
  function isChartElement(el){
    return !!(el.closest('canvas,svg,.zel-v54-spark-wrap,.zel-v47-spark-wrap,.zel-v51-spark-wrap,.zel-v52-spark-wrap,.zel-v53-spark-wrap,.zel-v54-live-core,.zel-v56-live-core,[data-zel-live-core]'));
  }
  function looksLikeLegacyBar(el,card){
    if(!visible(el)) return false;
    if(isChartElement(el)) return false;
    if(el.matches('canvas,svg,path,line,polyline,rect,circle,img,video')) return false;
    if(el.closest('button,[role="button"],a,input,select,textarea')) return false;
    if(txt(el).length>0) return false;
    var r=rect(el), cr=rect(card);
    if(r.height<1||r.height>12) return false;
    if(r.width<Math.max(85,cr.width*0.32)) return false;
    if(r.width>cr.width+4) return false;
    if(r.top<cr.top+42||r.bottom>cr.bottom-24) return false;
    var c=css(el); if(!c) return false;
    var bg=(c.backgroundColor||'').toLowerCase();
    var br=(c.borderTopColor+' '+c.borderBottomColor+' '+c.borderLeftColor+' '+c.borderRightColor).toLowerCase();
    var shadow=(c.boxShadow||'').toLowerCase();
    var radius=parseFloat(c.borderRadius||'0')||0;
    var colored=/rgb\(|rgba\(/.test(bg)||/rgb\(|rgba\(/.test(br)||/rgb\(|rgba\(/.test(shadow);
    if(!colored) return false;
    var cyanish=/(0,\s*255|95,\s*234|96,\s*245|34,\s*211|58,\s*220|80,\s*220|94,\s*234|5,\s*217|56,\s*189|59,\s*130|31,\s*41|24,\s*34|15,\s*23)/.test(bg+br+shadow);
    var thinRounded=radius>=1||r.height<=6;
    return !!(cyanish&&thinRounded);
  }
  function hideBars(){
    findCards().forEach(function(card){
      Array.prototype.slice.call(card.querySelectorAll('div,span,i,b,em')).forEach(function(el){
        if(looksLikeLegacyBar(el,card)){
          el.setAttribute('data-zel-v58-hidden-bar','1');
          el.setAttribute('aria-hidden','true');
        }
      });
    });
  }
  function boot(){
    hideBars();
    setInterval(hideBars,700);
    try{
      new MutationObserver(function(){setTimeout(hideBars,40);}).observe(document.body||document.documentElement,{childList:true,subtree:true,attributes:true,attributeFilter:['style','class']});
    }catch(e){}
    window.ZEL_APP_V58_BAR_ONLY={version:VER,hide:hideBars};
  }
  if(document.readyState==='loading') document.addEventListener('DOMContentLoaded',boot,{once:true}); else boot();
})();
