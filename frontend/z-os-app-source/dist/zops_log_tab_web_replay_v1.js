(function zopsLogTabWebReplayV1(){
  if (window.__ZOPS_LOG_TAB_WEB_REPLAY_V1__ && window.__ZOPS_LOG_TAB_WEB_REPLAY_V1__.installed) return;
  const VERSION = 'zops_log_tab_web_replay_v1';
  const state = window.__ZOPS_LOG_TAB_WEB_REPLAY_V1__ = {installed:true, version:VERSION, ticks:0, hidden:0, mounted:false, last:null};
  const nativeFetch = window.fetch ? window.fetch.bind(window) : null;
  const ttl = 30000;
  const cache = new Map();
  const endpoints = [
    ['/api/replay/health','replay'],
    ['/api/replay/status','replay_status'],
    ['/api/ledger/health','ledger'],
    ['/api/harness/visual/status','harness'],
    ['/api/contract/smoke/status','smoke']
  ];

  function now(){ return Date.now(); }
  function txt(x){ return String(x == null ? '' : x); }
  function low(x){ return txt(x).toLowerCase(); }
  function safeText(el){ try { return (el && el.textContent || '').replace(/\s+/g,' ').trim(); } catch(e){ return ''; } }
  function clsStatus(v){ const s=low(v); if(!s || s==='n/a') return 'muted'; if(s.includes('pass')||s.includes('ok')||s.includes('ready')||s.includes('active')||s.includes('true')) return 'ok'; if(s.includes('fail')||s.includes('error')||s.includes('missing')) return 'bad'; return 'warn'; }
  function api(url, opts){
    if(!nativeFetch) return Promise.resolve({ok:false,status:'no_fetch'});
    const key = (opts && opts.method || 'GET') + ':' + url;
    const c = cache.get(key);
    if(c && now()-c.t < ttl) return Promise.resolve(c.v);
    return nativeFetch(url, Object.assign({headers:{'accept':'application/json'}}, opts || {}))
      .then(r => r.text().then(t => {
        let j=null; try{ j=t ? JSON.parse(t) : null; }catch(e){ j={raw:t.slice(0,240), parse_error:true}; }
        const v={ok:r.ok,status:r.status,json:j,url:url}; cache.set(key,{t:now(),v:v}); return v;
      }))
      .catch(e => ({ok:false,status:'fetch_error',error:String(e),url:url}));
  }
  function summarize(res){
    const j = res && res.json || {};
    if(!res || !res.ok) return 'down';
    return j.status || j.ok || j.component || j.service || 'ok';
  }
  function isLikelyBottomResidue(el){
    if(!el || el.closest('.zops-log-web-replay-card')) return false;
    const t = low(safeText(el));
    if(!(t.includes('web') && t.includes('audit') && t.includes('replay'))) return false;
    let node = el;
    for(let i=0;i<5 && node && node !== document.body;i++,node=node.parentElement){
      const st = getComputedStyle(node);
      const r = node.getBoundingClientRect();
      const fixedish = st.position === 'fixed' || st.position === 'sticky' || st.position === 'absolute';
      const bottomish = r.bottom > window.innerHeight - 115 || r.top > window.innerHeight - 130;
      const offLeft = r.left < Math.max(32, window.innerWidth * 0.08);
      const smallPill = r.width > 40 && r.width < 220 && r.height > 20 && r.height < 80;
      if(smallPill && (fixedish || bottomish) && offLeft) return node;
    }
    return false;
  }
  function hideResidue(){
    let n=0;
    const nodes = Array.prototype.slice.call(document.querySelectorAll('button,a,[role="button"],div,span'));
    for(const el of nodes){
      const holder = isLikelyBottomResidue(el);
      if(holder && !holder.dataset.zopsWebReplayResidueHidden){
        holder.dataset.zopsWebReplayResidueHidden = VERSION;
        holder.classList.add('zops-web-replay-residue-hidden');
        holder.setAttribute('aria-hidden','true');
        n++;
      }
    }
    state.hidden += n;
    return n;
  }
  function findLogAnchor(){
    const bodyText = safeText(document.body);
    const hashLog = low(location.hash).includes('log');
    const hasReplayTimeline = bodyText.includes('REPLAY TIMELINE') || bodyText.includes('Replay Timeline') || bodyText.includes('replay timeline');
    const hasLogNav = /\bLog\b/.test(bodyText) || /로그/.test(bodyText);
    if(!hashLog && !hasReplayTimeline && !hasLogNav) return null;

    let best = null;
    const all = Array.prototype.slice.call(document.querySelectorAll('section,main,article,div'));
    for(const el of all){
      if(el.closest('.zops-log-web-replay-card')) continue;
      const t = safeText(el);
      if(!t) continue;
      const hit = t.includes('REPLAY TIMELINE') || t.includes('Replay Timeline') || t.includes('receipt archived') || t.includes('decision envelope received');
      if(!hit) continue;
      const r = el.getBoundingClientRect();
      if(r.width < 240 || r.height < 160 || r.width > Math.min(window.innerWidth, 880)) continue;
      if(!best || (r.width*r.height) < (best.getBoundingClientRect().width*best.getBoundingClientRect().height)) best = el;
    }
    if(best) return best;

    const visible = all.filter(el => {
      const r = el.getBoundingClientRect();
      return r.width >= 280 && r.width <= Math.min(window.innerWidth,760) && r.height >= 180 && r.top < window.innerHeight-120 && r.bottom > 100;
    }).sort((a,b)=>(a.getBoundingClientRect().width*a.getBoundingClientRect().height)-(b.getBoundingClientRect().width*b.getBoundingClientRect().height));
    return visible[0] || null;
  }
  function ensureCard(anchor){
    let card = document.getElementById('zops-log-web-replay-card');
    if(card && document.body.contains(card)) return card;
    card = document.createElement('section');
    card.id = 'zops-log-web-replay-card';
    card.className = 'zops-log-web-replay-card';
    card.setAttribute('data-zops-version', VERSION);
    card.innerHTML = ''+
      '<div class="zops-log-web-replay-head">'+
        '<div><div class="zops-log-web-replay-title">Web Replay · Log Tab</div><div class="zops-log-web-replay-sub">audit replay is anchored here; off-canvas residue is hidden by harness-compatible guard</div></div>'+
        '<div class="zops-log-web-replay-state"><span class="zops-log-web-replay-dot"></span><span data-zwr="overall">checking</span></div>'+
      '</div>'+
      '<div class="zops-log-web-replay-grid">'+
        '<div class="zops-log-web-replay-kv"><div class="zops-log-web-replay-k">replay</div><div class="zops-log-web-replay-v" data-zwr="replay">n/a</div></div>'+
        '<div class="zops-log-web-replay-kv"><div class="zops-log-web-replay-k">ledger</div><div class="zops-log-web-replay-v" data-zwr="ledger">n/a</div></div>'+
        '<div class="zops-log-web-replay-kv"><div class="zops-log-web-replay-k">harness</div><div class="zops-log-web-replay-v" data-zwr="harness">n/a</div></div>'+
        '<div class="zops-log-web-replay-kv"><div class="zops-log-web-replay-k">api smoke</div><div class="zops-log-web-replay-v" data-zwr="smoke">n/a</div></div>'+
      '</div>'+
      '<div class="zops-log-web-replay-actions">'+
        '<button class="zops-log-web-replay-btn" type="button" data-zwr-action="refresh">refresh</button>'+
        '<button class="zops-log-web-replay-btn" type="button" data-zwr-action="sample">sample replay</button>'+
        '<button class="zops-log-web-replay-btn" type="button" data-zwr-action="smoke">smoke status</button>'+
      '</div>'+
      '<div class="zops-log-web-replay-log" data-zwr="log">mounted</div>';
    const insertAfterTitle = Array.prototype.slice.call(anchor.children).find(ch => /REPLAY TIMELINE|Replay Timeline/i.test(safeText(ch)));
    if(insertAfterTitle && insertAfterTitle.parentNode){ insertAfterTitle.parentNode.insertBefore(card, insertAfterTitle.nextSibling); }
    else { anchor.appendChild(card); }
    card.addEventListener('click', function(ev){
      const b = ev.target && ev.target.closest('[data-zwr-action]'); if(!b) return;
      const action = b.getAttribute('data-zwr-action');
      if(action === 'refresh') refresh(card, true);
      if(action === 'sample') runSample(card);
      if(action === 'smoke') runSmoke(card);
    });
    state.mounted = true;
    return card;
  }
  function setCard(card, key, value){
    const el = card.querySelector('[data-zwr="'+key+'"]');
    if(!el) return;
    const v = txt(value);
    el.textContent = v;
    el.className = 'zops-log-web-replay-v ' + clsStatus(v);
  }
  function logCard(card, msg, obj){
    const el = card.querySelector('[data-zwr="log"]'); if(!el) return;
    const line = new Date().toISOString().slice(11,19)+' '+msg+(obj ? ' '+JSON.stringify(obj).slice(0,700) : '');
    el.textContent = line + '\n' + el.textContent.slice(0,1600);
  }
  function refresh(card, force){
    if(force) cache.clear();
    Promise.all(endpoints.map(e => api(e[0]).then(r => [e[1], r]))).then(rows => {
      const map = {}; rows.forEach(([k,r]) => map[k]=r);
      const replay = summarize(map.replay_status && map.replay_status.ok ? map.replay_status : map.replay);
      const ledger = summarize(map.ledger);
      const harness = summarize(map.harness);
      const smoke = summarize(map.smoke);
      setCard(card,'replay', replay);
      setCard(card,'ledger', ledger);
      setCard(card,'harness', harness);
      setCard(card,'smoke', smoke);
      const okCount = [replay,ledger,harness,smoke].filter(x => clsStatus(x)==='ok').length;
      const overall = okCount >= 3 ? 'active' : (okCount ? 'partial' : 'check');
      const ov = card.querySelector('[data-zwr="overall"]'); if(ov) ov.textContent = overall;
      state.last = {replay,ledger,harness,smoke,okCount,ts_ms:now()};
      logCard(card,'refresh',{replay,ledger,harness,smoke,hidden:state.hidden});
    });
  }
  function runSample(card){
    cache.clear();
    api('/api/replay/sample').then(r => logCard(card, 'sample', r.json || {status:r.status}));
  }
  function runSmoke(card){
    cache.clear();
    api('/api/contract/smoke/status').then(r => logCard(card, 'smoke', r.json || {status:r.status}));
  }
  function tick(){
    state.ticks++;
    hideResidue();
    const anchor = findLogAnchor();
    if(anchor){
      const card = ensureCard(anchor);
      if(!state.last || now()-state.last.ts_ms > ttl) refresh(card, false);
    }
  }
  function boot(){ tick(); setInterval(tick, 1200); }
  if(document.readyState === 'loading') document.addEventListener('DOMContentLoaded', boot, {once:true}); else boot();
})();
