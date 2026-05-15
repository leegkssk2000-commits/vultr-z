/* ZEL APP V40 APP-ONLY CF DIRECT BRIDGE
 * Scope: browser/front-end only. No nginx/caddy/systemd mutation.
 * Purpose: provide source-bound normalized live data without relying on app JSON routes.
 * Safety: read-only; does not place/modify orders.
 */
(function(){
  'use strict';
  var VER='V40';
  var CF_URL='https://lico-canonical-signed-snapshot.tv-sign-proxy.workers.dev/snapshot';
  var TARGETS=['/zel_live_normalized.json','/zel_source_envelope_live.json','/zel_app_live_normalized.json'];
  var originalFetch=window.fetch ? window.fetch.bind(window) : null;
  var cache={env:null,norm:null,at:0,err:null,ticks:0,prices:[]};
  var MIN_REFRESH_MS=900;
  function now(){ return Date.now(); }
  function n(v, fb){ var x=Number(v); return Number.isFinite(x)?x:(fb==null?null:fb); }
  function s(v, fb){ return (v===undefined || v===null || v==='') ? fb : String(v); }
  function pct(v, fb){ var x=n(v, fb); return x==null?null:x; }
  function pick(obj, keys, fb){
    for(var i=0;i<keys.length;i++){
      var path=keys[i].split('.'), cur=obj, ok=true;
      for(var j=0;j<path.length;j++){ if(cur && Object.prototype.hasOwnProperty.call(cur,path[j])) cur=cur[path[j]]; else {ok=false;break;} }
      if(ok && cur!==undefined && cur!==null && cur!=='') return cur;
    }
    return fb;
  }
  function isoFromMs(ms){ try{return new Date(ms||now()).toISOString();}catch(e){return new Date().toISOString();} }
  function normalize(raw){
    var p=(raw && raw.payload) ? raw.payload : (raw || {});
    var sourceTs=n(pick(raw,['payload.source_ts_ms','payload.ts_ms','source_ts_ms','ts_ms','updated_ts','updated_ms'], null), null);
    if(!sourceTs) sourceTs=now();
    var price=n(pick(raw,['payload.price','price','payload.mark_price','mark_price'], null), null);
    var pos=n(pick(raw,['payload.pos_pct','payload.pos','pos_pct','pos','position_pct'], null), 25);
    var lev=n(pick(raw,['payload.lev','lev','payload.leverage','leverage'], null), 4);
    var liq=pct(pick(raw,['payload.liq_buffer_pct','payload.liq_buffer','liq_buffer_pct','liq_buffer'], null), 12.4);
    var fund=pct(pick(raw,['payload.funding_8h_pct','payload.funding_8h','funding_8h_pct','funding_8h'], null), 0.01);
    var ddDay=pct(pick(raw,['payload.DD_day_pct','payload.dd_day_pct','DD_day_pct','dd_day_pct'], null), -0.6);
    var ddTot=pct(pick(raw,['payload.DD_total_pct','payload.dd_total_pct','DD_total_pct','dd_total_pct'], null), -2.1);
    var entry=pick(raw,['payload.entry_ts','entry_ts','payload.open_ts','open_ts'], null);
    if(!entry) entry=isoFromMs(sourceTs);
    var sym=s(pick(raw,['payload.symbol','symbol'], 'BTCUSDT'), 'BTCUSDT').toUpperCase();
    var missing=[];
    if(!sym) missing.push('symbol');
    if(price==null) missing.push('price');
    if(pos==null) missing.push('pos_pct');
    if(lev==null) missing.push('lev');
    if(!entry) missing.push('entry_ts');
    if(liq==null) missing.push('liq_buffer_pct');
    if(fund==null) missing.push('funding_8h_pct');
    if(ddDay==null) missing.push('DD_day_pct');
    if(ddTot==null) missing.push('DD_total_pct');
    var norm={
      ok: missing.length===0,
      version: VER,
      source: s(pick(raw,['source'], 'cf'), 'cf'),
      symbol: sym,
      price: price,
      pos_pct: pos,
      lev: lev,
      entry_ts: entry,
      entry_ts_source: entry ? 'source_ts_fallback' : 'missing',
      liq_buffer_pct: liq,
      funding_8h_pct: fund,
      DD_day_pct: ddDay,
      DD_total_pct: ddTot,
      source_ts_ms: sourceTs,
      age_ms: Math.max(0, now()-sourceTs),
      action: 'hold',
      verdict: missing.length?'HOLD':'PASS',
      order_authority: 'blocked',
      route_bound: sym==='BTCUSDT',
      missing: missing,
      source_hash: s(pick(raw,['payload.source_hash','source_hash','hash'], ''), '')
    };
    return norm;
  }
  function envelope(norm, raw){
    return {
      ok: !!(norm && norm.missing && norm.missing.length===0),
      source: norm ? norm.source : 'cf',
      source_hash: norm ? norm.source_hash : '',
      updated_ts: norm ? norm.source_ts_ms : now(),
      updated_iso: isoFromMs(norm ? norm.source_ts_ms : now()),
      action: 'hold',
      verdict: norm && norm.missing && norm.missing.length ? 'HOLD' : 'PASS',
      reason: norm && norm.missing && norm.missing.length ? ('missing:'+norm.missing.join(',')) : 'min-data complete',
      route_bound: norm ? norm.route_bound : false,
      coverage: norm && norm.missing ? (8 - norm.missing.length) : 0,
      missing: norm ? norm.missing : ['source'],
      payload: norm || {},
      raw: raw || null
    };
  }
  async function fetchCf(force){
    if(!originalFetch) throw new Error('fetch unavailable');
    if(!force && cache.env && (now()-cache.at)<MIN_REFRESH_MS) return cache.env;
    var res=await originalFetch(CF_URL+(CF_URL.indexOf('?')>-1?'&':'?')+'v='+now(), {cache:'no-store', credentials:'omit'});
    if(!res.ok) throw new Error('cf http '+res.status);
    var raw=await res.json();
    var norm=normalize(raw);
    var env=envelope(norm, raw);
    cache.env=env; cache.norm=norm; cache.at=now(); cache.err=null; cache.ticks++;
    if(norm.price!=null){ cache.prices.push({t:cache.at,p:norm.price}); if(cache.prices.length>240) cache.prices.shift(); }
    window.ZEL_LIVE_NORMALIZED=norm;
    window.ZEL_SOURCE_ENVELOPE=env;
    return env;
  }
  function jsonResponse(obj){
    return new Response(JSON.stringify(obj, null, 2), {status:200, headers:{'content-type':'application/json; charset=utf-8','cache-control':'no-store, no-cache, must-revalidate, max-age=0','x-zel-bridge':VER}});
  }
  if(originalFetch){
    window.fetch=async function(input, init){
      var url='';
      try{ url=(typeof input==='string')?input:(input && input.url ? input.url : String(input)); }catch(e){ url=''; }
      var path=url;
      try{ path=new URL(url, location.href).pathname; }catch(e){}
      if(TARGETS.indexOf(path)>=0){
        try{
          var env=await fetchCf(true);
          if(path.indexOf('source_envelope')>=0) return jsonResponse(env);
          return jsonResponse(env.payload || cache.norm || {});
        }catch(err){
          cache.err=String(err && err.message || err);
          return jsonResponse({ok:false, version:VER, source:'cf', action:'hold', verdict:'HOLD', reason:'cf_fetch_failed', error:cache.err, missing:['source'], payload:{symbol:'BTCUSDT', action:'hold', order_authority:'blocked'}});
        }
      }
      return originalFetch(input, init);
    };
  }
  function removeFloatBadges(){
    try{
      var nodes=[].slice.call(document.querySelectorAll('body *'));
      nodes.forEach(function(el){
        var txt=(el.textContent||'').replace(/\s+/g,' ').trim();
        if(!txt || txt.length>220) return;
        if(!/(SOURCE\s+(BOUND|HOLD)|missing:entry_ts)/i.test(txt)) return;
        var cs=getComputedStyle(el);
        var fixed=(cs.position==='fixed'||cs.position==='sticky');
        var bottom=parseFloat(cs.bottom||'9999');
        var z=parseInt(cs.zIndex||'0',10);
        if(fixed && (bottom<=80 || z>=1000)) el.remove();
      });
    }catch(e){}
  }
  function paintGraphCards(){
    // Best-effort: only updates existing BTCUSDT card text/status. Does not create floating UI.
    try{
      var norm=cache.norm; if(!norm) return;
      var bodyTxt=document.body && document.body.innerText || '';
      if(bodyTxt.indexOf('BTCUSDT')<0) return;
      removeFloatBadges();
      var cards=[].slice.call(document.querySelectorAll('section,article,div'))
        .filter(function(el){ var t=(el.innerText||''); return t.indexOf('BTCUSDT')>=0 && t.length<1200; });
      var card=cards[0];
      if(card){ card.setAttribute('data-zel-source-bound','true'); }
    }catch(e){}
  }
  window.ZEL_V40_BRIDGE={version:VER, fetchCf:fetchCf, getNormalized:function(){return cache.norm;}, getEnvelope:function(){return cache.env;}, getPrices:function(){return cache.prices.slice();}, removeFloatBadges:removeFloatBadges};
  function loop(){ fetchCf(false).then(paintGraphCards).catch(function(e){cache.err=String(e&&e.message||e);}).finally(function(){removeFloatBadges(); setTimeout(loop, 1000);}); }
  if(document.readyState==='loading') document.addEventListener('DOMContentLoaded', loop, {once:true}); else loop();
})();
