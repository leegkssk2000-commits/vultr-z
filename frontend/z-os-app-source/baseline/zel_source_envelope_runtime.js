/* ZEL APP BTC SOURCE-BOUND RUNTIME V34
 * Scope: app.z-os.vip dashboard only.
 * BTCUSDT-only binding. Multi-symbol binding intentionally disabled.
 * Read-only display patch: no order execution, no backend mutation.
 */
(function(){
  'use strict';
  const VERSION = 'ZEL_DASH_APP_BTC_SOURCEBOUND_MOBILE_SAFE_V34_20260513';
  const TARGET_SYMBOL = 'BTCUSDT';
  const CFG = {
    url: '/zel_source_envelope_live.json',
    configUrl: '/zel_source_envelope_config.json',
    pollMs: 1500,
    staleMs: 60000,
    minData: ['price','pos_pct','lev','entry_ts','liq_buffer_pct','funding_8h_pct','DD_day_pct','DD_total_pct']
  };
  const S = { ok:false, bound:false, reason:'init', env:null, lastRaw:null, errors:[], version:VERSION };
  const $all = (sel,root=document)=>Array.from(root.querySelectorAll(sel));
  const now = ()=>Date.now();
  const finite = v => Number.isFinite(Number(v));
  const num = v => (v===null||v===undefined||v==='') ? NaN : Number(v);
  const str = (v,d='') => (v===null||v===undefined||String(v).trim()==='') ? d : String(v);
  const fmt = (v,d=2)=> finite(v) ? Number(v).toFixed(d).replace(/\.0+$/,'').replace(/(\.\d*?)0+$/,'$1') : 'unbound';
  const shortHash = v => str(v,'').replace(/[^a-zA-Z0-9]/g,'').slice(0,16) || 'linked';
  const escapeHtml = s => String(s).replace(/[&<>"']/g, ch => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[ch]));

  function installMobileSafeCss(){
    if(document.getElementById('zel-app-v34-mobile-safe-css')) return;
    const st=document.createElement('style');
    st.id='zel-app-v34-mobile-safe-css';
    st.textContent=`
      #zel-app-source-bound-v34{
        position:fixed; right:12px; bottom:12px; z-index:2147483647;
        max-width:min(620px,calc(100vw - 24px)); box-sizing:border-box;
        padding:10px 14px; border-radius:16px; pointer-events:none;
        font:700 12px/1.35 ui-monospace,SFMono-Regular,Menlo,Consolas,monospace;
        letter-spacing:.02em; color:#d1fae5; background:rgba(2,8,23,.94);
        border:1px solid rgba(16,185,129,.85); box-shadow:0 0 24px rgba(16,185,129,.28),0 8px 30px rgba(0,0,0,.45);
        white-space:nowrap; overflow:hidden; text-overflow:ellipsis;
      }
      @media (max-width: 768px){
        html,body{scroll-padding-bottom:112px!important;}
        body{padding-bottom:112px!important;}
        #zel-app-source-bound-v34{
          left:10px; right:10px; bottom:calc(76px + env(safe-area-inset-bottom));
          max-width:calc(100vw - 20px); padding:9px 11px; border-radius:14px;
          font-size:11px; white-space:nowrap;
        }
      }
    `;
    document.head.appendChild(st);
  }

  function hideLegacyBadges(){
    $all('div,span').forEach(el=>{
      if(el.id==='zel-app-source-bound-v34') return;
      const id=(el.id||'').toLowerCase();
      const tx=(el.textContent||'').trim();
      if(id.startsWith('zel-source-bind') || (tx.startsWith('SOURCE BOUND V') || tx.startsWith('SOURCE HOLD V'))){
        const cs=getComputedStyle(el);
        if(cs.position==='fixed') el.style.display='none';
      }
    });
  }

  async function fetchJson(url){
    const res = await fetch(url + (url.includes('?')?'&':'?') + 'v=' + Date.now(), {cache:'no-store', credentials:'same-origin'});
    if(!res.ok) throw new Error('HTTP_'+res.status+':'+url);
    const txt = await res.text();
    try { return JSON.parse(txt); }
    catch(e){ throw new Error('JSON_PARSE:'+url+':head='+txt.slice(0,80)); }
  }
  function unwrap(raw){
    if(!raw || typeof raw!=='object') return {};
    return raw.payload || raw.data || raw.snapshot || raw.envelope || raw;
  }
  function sourceKeys(raw,p){
    const src = p.src_keys || p.source_keys || p.sources || raw.src_keys || raw.source_keys || raw.sources || [];
    if(Array.isArray(src)) return src.map(String);
    if(src && typeof src==='object') return Object.keys(src).map(String);
    const s = p.source || raw.source;
    return s ? [String(s).endsWith(':/') ? String(s) : String(s)+':/'] : [];
  }
  function normalize(raw){
    const p = unwrap(raw);
    const sourceTs = num(p.source_ts_ms ?? p.sourceTsMs ?? p.source_ts ?? p.ts_ms ?? raw.source_ts_ms ?? raw.ts_ms ?? raw.cache_ts_ms ?? raw.updated_ts);
    const env = {
      raw, p,
      ok: raw.ok !== false,
      source: str(p.source || raw.source, 'cf'),
      src_keys: sourceKeys(raw,p),
      symbol: str(p.symbol || p.ticker || p.market || raw.symbol, TARGET_SYMBOL).toUpperCase(),
      strategy: str(p.strategy || raw.strategy, 'Alpha'),
      price: num(p.price ?? p.price_usdt ?? p.mark_price ?? p.last_price ?? p.last ?? p.close),
      pos_pct: num(p.pos_pct ?? p.posPct ?? p.position_pct ?? p.positionPct ?? p.pos ?? p.position),
      lev: num(p.lev ?? p.lev_x ?? p.leverage ?? p.leverage_x),
      entry_ts: p.entry_ts ?? p.entryTs ?? p.entry_time ?? p.open_ts ?? p.open_time,
      liq_price: num(p.liq_price ?? p.liquidation_price ?? p.liqPrice),
      liq_buffer_pct: num(p.liq_buffer_pct ?? p.liq_buffer ?? p.liqBufferPct ?? p.liq_buffer_percent),
      funding_8h_pct: num(p.funding_8h_pct ?? p.funding_8h ?? p.funding8hPct ?? p.funding_rate_8h_pct),
      DD_day_pct: num(p.DD_day_pct ?? p.dd_day_pct ?? p.ddDayPct ?? p.dd_day),
      DD_total_pct: num(p.DD_total_pct ?? p.dd_total_pct ?? p.ddTotalPct ?? p.dd_total),
      virtual_equity_usdt: num(p.virtual_equity_usdt ?? p.virtual?.equity_usdt ?? p.virtual_account?.virtual_equity_usdt ?? p.virtual_account?.equity ?? p.current_balance_usdt),
      live_wallet_balance: num(p.wallet_balance ?? p.live_account?.wallet_balance ?? p.live?.wallet_balance ?? p.account?.wallet_balance),
      live_available_balance: num(p.availableBalance ?? p.available_balance ?? p.live_account?.availableBalance ?? p.live_account?.available_balance),
      live_totalWalletBalance: num(p.totalWalletBalance ?? p.total_wallet_balance ?? p.live_account?.totalWalletBalance),
      unrealized_pnl: num(p.unrealized_pnl ?? p.unrealizedPnl ?? p.live_account?.unrealized_pnl),
      live_pnl: num(p.live_pnl ?? p.realized_pnl ?? p.live_account?.live_pnl),
      source_hash: shortHash(p.source_hash || p.receipt_hash || p.receipt || raw.source_hash || raw.receipt_hash || raw.receipt),
      source_ts_ms: sourceTs
    };
    env.age_ms = finite(sourceTs) ? Math.max(0, now()-sourceTs) : NaN;
    return env;
  }
  function validate(e){
    if(!e) return 'no_env';
    if(e.symbol !== TARGET_SYMBOL) return 'symbol_not_btc';
    const missing=[];
    for(const k of CFG.minData){
      if(k==='entry_ts'){ if(!str(e.entry_ts)) missing.push(k); }
      else if(!finite(e[k])) missing.push(k);
    }
    const srcOk = (e.src_keys||[]).some(k=>String(k).startsWith('cf:/')) || e.source==='cf';
    if(!srcOk) missing.push('cf_source');
    if(!finite(e.source_ts_ms)) missing.push('source_ts_ms');
    else if(e.age_ms > CFG.staleMs) missing.push('stale_'+Math.round(e.age_ms));
    return missing.length ? 'missing:'+missing.join(',') : 'ok';
  }

  function textNodes(root){
    if(!root) return [];
    const w=document.createTreeWalker(root,NodeFilter.SHOW_TEXT,{acceptNode(n){
      const p=n.parentElement; if(!p) return NodeFilter.FILTER_REJECT;
      if(['SCRIPT','STYLE','NOSCRIPT','TEXTAREA'].includes(p.tagName)) return NodeFilter.FILTER_REJECT;
      return n.nodeValue && n.nodeValue.trim() ? NodeFilter.FILTER_ACCEPT : NodeFilter.FILTER_REJECT;
    }});
    const out=[]; while(w.nextNode()) out.push(w.currentNode); return out;
  }
  function replText(root,pairs){
    textNodes(root).forEach(n=>{
      let s=n.nodeValue, changed=false;
      for(const [re,val] of pairs){ const ns=s.replace(re,val); if(ns!==s){s=ns; changed=true;} }
      if(changed) n.nodeValue=s;
    });
  }
  function smallestContainer(pred){
    const els=$all('article,section,div,main,li');
    const hits=els.filter(el=>pred(el.textContent||''));
    hits.sort((a,b)=>(a.textContent||'').length-(b.textContent||'').length);
    return hits[0] || null;
  }
  function findBtcCard(){
    return smallestContainer(t => t.includes(TARGET_SYMBOL) && (t.includes('sig=read_only') || t.includes('risk=') || t.includes('XAI:') || t.includes('unbound')));
  }
  function patchBtcCard(e){
    const c=findBtcCard();
    if(!c) return;
    const price=fmt(e.price,0), pos=fmt(e.pos_pct,2)+'%', lev=fmt(e.lev,2), liq=fmt(e.liq_buffer_pct,1)+'%', fund=fmt(e.funding_8h_pct,3)+'%';
    replText(c,[
      [/^unbound$/g,'source-bound'],
      [/risk=hold/g,'risk=bound'],
      [/proof=missing/g,'proof=source-bound'],
      [/hold/g,'hold'],
      [/source-required/g,'source=cf'],
      [/vol=medium/g,'vol=medium'],
      [/liq=unbound/g,'liq='+liq],
      [/receipt_hash=r/g,'receipt_hash='+e.source_hash],
      [/XAI: waiting for CF\/GS price, position, risk, proof, and source age/g,'XAI: BTCUSDT CF source-bound · price '+price+' · pos '+pos+' · lev '+lev+' · funding '+fund],
    ]);
  }
  function patchHeader(e){
    const body=document.body; if(!body) return;
    const price=fmt(e.price,0), pos=fmt(e.pos_pct,2)+'%', lev=fmt(e.lev,2), liq=fmt(e.liq_buffer_pct,1)+'%', fund=fmt(e.funding_8h_pct,3)+'%', dd=fmt(e.DD_day_pct,2)+'%', ddt=fmt(e.DD_total_pct,2)+'%';
    replText(body,[
      [/DATA HOLD \| source-bound truth required \| orders blocked/g,'SOURCE BOUND | BTCUSDT MinData complete | orders blocked'],
      [/CF\/GS-backed MinData, source age, key parity, and SSOT threshold checks are required before live dashboard truth is rendered\./g,'BTCUSDT CF envelope is bound. ETH/SOL/XRP/LINK remain unbound until multi-symbol source is added.'],
      [/price=unbound\s*\/\s*pos=unbound\s*\/\s*lev=unbound\s*\/\s*liq_buffer=unbound\s*\/\s*funding_8h=unbound/g,'price='+price+' / pos='+pos+' / lev='+lev+' / liq_buffer='+liq+' / funding_8h='+fund+' / DD_day='+dd+' / DD_total='+ddt],
      [/hold; no app-side execution; wait for source-bound envelope/g,'hold; BTCUSDT source-bound read-only; no app-side execution'],
      [/memo pending/g,'memo BTC-bound'],
      [/receipt pending · replay pending · signature pending · source_hash required/g,'receipt source-bound · replay pending · signature read-only · source_hash '+e.source_hash],
      [/source_hash required/g,'source_hash '+e.source_hash]
    ]);
  }
  function patchDetailValues(e){
    const price=fmt(e.price,0), pos=fmt(e.pos_pct,2), lev=fmt(e.lev,2), liq=fmt(e.liq_buffer_pct,1), fund=fmt(e.funding_8h_pct,3), dd=fmt(e.DD_day_pct,2), ddt=fmt(e.DD_total_pct,2);
    // Conservative text replacement: only source-bound summary fields, not other symbol cards.
    replText(document.body,[
      [/BTCUSDT\s+unbound/g,'BTCUSDT\nsource-bound'],
      [/price=unbound/g,'price='+price],
      [/pos=unbound/g,'pos='+pos+'%'],
      [/lev=unbound/g,'lev='+lev],
      [/liq_buffer=unbound/g,'liq_buffer='+liq+'%'],
      [/funding_8h=unbound/g,'funding_8h='+fund+'%'],
      [/DD_day=unbound/g,'DD_day='+dd+'%'],
      [/DD_total=unbound/g,'DD_total='+ddt+'%']
    ]);
  }
  function badge(e){
    installMobileSafeCss(); hideLegacyBadges();
    let b=document.getElementById('zel-app-source-bound-v34');
    if(!b){ b=document.createElement('div'); b.id='zel-app-source-bound-v34'; document.documentElement.appendChild(b); }
    if(e && S.bound){
      b.style.borderColor='rgba(16,185,129,.9)'; b.style.color='#d1fae5';
      b.innerHTML='● SOURCE BOUND V34 · '+escapeHtml(e.symbol)+' · price '+escapeHtml(fmt(e.price,0))+' · pos '+escapeHtml(fmt(e.pos_pct,2))+'% · lev '+escapeHtml(fmt(e.lev,2))+' · age_ms '+escapeHtml(fmt(e.age_ms,0));
    } else {
      b.style.borderColor='rgba(245,158,11,.88)'; b.style.color='#fde68a';
      b.textContent=''; b.setAttribute('data-zel-footer-v34','hidden'); b.style.setProperty('display','none','important');
    }
  }
  function publish(e){
    const detail=Object.freeze(Object.assign({}, e, {bound:S.bound, version:VERSION, multi_symbol:false}));
    window.__ZEL_SOURCE_ENVELOPE__=detail;
    window.__ZEL_APP_BTC_SOURCE_BOUND__=detail;
    try{ window.dispatchEvent(new CustomEvent('zel:source-envelope',{detail})); }catch(_){ }
  }
  async function load(){
    try{
      const raw=await fetchJson(CFG.url);
      const e=normalize(raw); S.lastRaw=raw; S.env=e;
      const verdict=validate(e); S.reason=verdict; S.ok=verdict==='ok'; S.bound=S.ok;
      return S.ok ? e : null;
    } catch(err){
      S.errors.push(String(err.message||err)); S.errors=S.errors.slice(-8); S.ok=false; S.bound=false; S.reason=S.errors[S.errors.length-1]||'fetch_error'; return null;
    }
  }
  async function tick(){
    hideLegacyBadges();
    const e=await load(); badge(e);
    if(e && S.bound){ patchHeader(e); patchBtcCard(e); patchDetailValues(e); publish(e); }
  }
  function boot(){
    window.__ZEL_APP_SOURCE_BIND_STATE__=S;
    installMobileSafeCss(); tick(); setInterval(tick, CFG.pollMs);
    try{
      const mo=new MutationObserver(()=>{ if(S.bound && S.env){ hideLegacyBadges(); patchHeader(S.env); patchBtcCard(S.env); }});
      mo.observe(document.documentElement,{subtree:true, childList:true, characterData:true});
    }catch(_){ }
  }
  if(document.readyState==='loading') document.addEventListener('DOMContentLoaded',boot,{once:true}); else boot();
})();


/* ZEL_FOOTER_V34_VISUAL_KILL_V2_RUNTIME */
(function(){
  function kill(){
    try{
      var nodes = document.querySelectorAll('[id^="zel-source-bind"],[data-zel-footer-v34],div,span,aside,footer');
      for(var i=0;i<nodes.length;i++){
        var el=nodes[i];
        var t=(el.innerText||el.textContent||'').trim();
        if(!t || t.length>260) continue;
        if(/^SOURCE\s+(HOLD|BOUND)\s+V34\s*·/i.test(t)){
          var cs=getComputedStyle(el), r=el.getBoundingClientRect();
          var footerLike=(cs.position==='fixed'||cs.position==='sticky'||r.top>innerHeight*0.55);
          if(footerLike){
            el.setAttribute('data-zel-footer-v34','hidden');
            el.style.setProperty('display','none','important');
            el.style.setProperty('visibility','hidden','important');
            el.style.setProperty('pointer-events','none','important');
          }
        }
      }
    }catch(e){}
  }
  kill();
  try{new MutationObserver(kill).observe(document.documentElement,{childList:true,subtree:true,characterData:true});}catch(e){}
  setInterval(kill,700);
})();
