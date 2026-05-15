(()=>{
  'use strict';
  const SYMBOLS=['BTCUSDT','ETHUSDT','SOLUSDT','XRPUSDT','LINKUSDT'];
  const state=window.__ZEL_OBX_V3__={version:'v3.exchange-ticket',focus:window.__ZEL_OBX_FOCUS__||'BTCUSDT',cards:{},market:{},portfolio:{},rendered:0};
  const nf0=new Intl.NumberFormat('en-US',{maximumFractionDigits:0});
  const nf2=new Intl.NumberFormat('en-US',{maximumFractionDigits:2});
  const nf4=new Intl.NumberFormat('en-US',{maximumFractionDigits:4});
  const $=(tag,cls,txt)=>{const el=document.createElement(tag); if(cls)el.className=cls; if(txt!==undefined)el.textContent=txt; return el;};
  const num=v=>{const n=Number(String(v??'').replace(/[,%]/g,'')); return Number.isFinite(n)?n:null;};
  const fmtP=v=>{v=num(v); if(v===null)return'--'; if(v>=10000)return nf0.format(v); if(v>=100)return nf2.format(v); return nf4.format(v);};
  const fmtQ=v=>{v=num(v); if(v===null)return'--'; if(v>=1000)return nf0.format(v); if(v>=10)return nf2.format(v); return nf4.format(v);};
  const fmtPct=v=>{v=num(v); return v===null?'--':`${nf2.format(v)}%`;};
  const fmtMoney=(v,unit)=>{v=num(v); if(v===null)return`-- ${unit}`; const sign=v>0?'+':''; return `${sign}${nf2.format(v)} ${unit}`;};
  const timeout=(ms)=>new Promise((_,rej)=>setTimeout(()=>rej(new Error('timeout')),ms));
  async function jget(url,ms=2600){const r=await Promise.race([fetch(url,{cache:'no-store',credentials:'same-origin'}),timeout(ms)]); if(!r.ok)throw new Error(`${r.status} ${url}`); return r.json();}
  function arrays(x){if(!x)return[]; if(Array.isArray(x))return x; if(typeof x==='object')return Object.values(x).flatMap(arrays); return[];}
  function pick(o,keys){if(!o||typeof o!=='object')return undefined; for(const k of keys){if(o[k]!==undefined&&o[k]!==null&&o[k]!=='')return o[k];} return undefined;}
  function symOf(o){return String(pick(o,['symbol','pair','market','s'])||'').toUpperCase().replace(/[^A-Z0-9]/g,'');}
  function normalizeBook(raw,s,source){
    const asks=(raw.asks||[]).slice(0,8).map(x=>[num(x[0]??x.price),num(x[1]??x.qty??x.size)]).filter(x=>x[0]!==null);
    const bids=(raw.bids||[]).slice(0,8).map(x=>[num(x[0]??x.price),num(x[1]??x.qty??x.size)]).filter(x=>x[0]!==null);
    const last=num(raw.lastPrice??raw.price??raw.last??raw.markPrice)??num(bids[0]?.[0])??num(asks[0]?.[0]);
    const spread=(asks[0]&&bids[0]&&last)?((asks[0][0]-bids[0][0])/last*100):null;
    return {symbol:s,asks,bids,last,spread_pct:spread,source,bound:!!last,age_ms:num(raw.age_ms??raw.ageMs)};
  }
  async function loadBinance(s){
    const [d,t]=await Promise.all([
      jget(`https://fapi.binance.com/fapi/v1/depth?symbol=${encodeURIComponent(s)}&limit=10`,3200),
      jget(`https://fapi.binance.com/fapi/v1/ticker/price?symbol=${encodeURIComponent(s)}`,3200).catch(()=>({}))
    ]);
    d.lastPrice=t.price;
    return normalizeBook(d,s,'binance:visual');
  }
  async function loadInternalMarket(s){
    const urls=[`/api/market/depth?symbol=${s}`,`/api/orderbook?symbol=${s}`,`/api/state?symbol=${s}`,`/api/portfolio/state?symbol=${s}`];
    for(const u of urls){try{const j=await jget(u,1600); const hit=findSymbolPayload(j,s); if(hit){const b=normalizeBook(hit,s,'cf/gs'); if(b.bound)return b;}}catch(e){}}
    throw new Error('no internal market');
  }
  function findSymbolPayload(x,s){
    if(!x)return null;
    if(Array.isArray(x)){for(const it of x){const h=findSymbolPayload(it,s); if(h)return h;} return null;}
    if(typeof x==='object'){
      if(symOf(x)===s || x[s] || x.symbol===s) return x[s]||x;
      for(const v of Object.values(x)){const h=findSymbolPayload(v,s); if(h)return h;}
    }
    return null;
  }
  async function loadMarket(s){try{return await loadInternalMarket(s);}catch(e){} try{return await loadBinance(s);}catch(e){return{symbol:s,asks:[],bids:[],last:null,spread_pct:null,source:'unbound',bound:false};}}
  async function loadPortfolio(){
    const urls=['/api/portfolio/state','/api/state','/api/alimi/state','/api/truth/state','/api/dashboard/state'];
    const out=[];
    for(const u of urls){try{out.push(await jget(u,1700));}catch(e){}}
    state.portfolio={raw:out};
  }
  function normPos(o,s,mode){
    const side=String(pick(o,['side','position_side','pos_side'])||'flat').toLowerCase();
    const qty=num(pick(o,['qty','position_amt','positionAmt','size','amount']));
    const pos_pct=num(pick(o,['pos_pct','position_pct','allocation_pct','pos_percent']));
    const flat=(!side||side==='flat'||side==='none')&&(qty===null||qty===0)&&(pos_pct===null||pos_pct===0);
    return {status:'bound',symbol:s,mode,side:flat?'flat':side,pos_pct,lev:num(pick(o,['lev','leverage'])),entry:num(pick(o,['entry','entry_price','avg_entry_price','entryPrice'])),upnl_usdt:num(pick(o,['upnl_usdt','unrealized_pnl','unrealizedPnl','unrealizedProfit','pnl','live_pnl','virtual_pnl_usdt'])),upnl_pct:num(pick(o,['upnl_pct','pnl_pct','roe','roe_pct','virtual_pnl_pct'])),liq_buffer_pct:num(pick(o,['liq_buffer_pct','liquidation_buffer_pct','liq_buffer'])),funding_8h_pct:num(pick(o,['funding_8h_pct','funding_rate_8h_pct','funding_8h'])),action:String(pick(o,['action','final_action','decision_action','current_action'])||'hold')};
  }
  function findPos(s,mode){
    const all=arrays(state.portfolio.raw||[]);
    const modeHits=all.filter(x=>typeof x==='object' && (!mode || String(x.mode||x.account||x.kind||'').toLowerCase().includes(mode)));
    const hit=[...modeHits,...all].find(x=>typeof x==='object'&&symOf(x)===s);
    if(hit)return normPos(hit,s,mode);
    const any=(state.portfolio.raw||[]).length>0;
    return {status:any?'bound':'unbound',symbol:s,mode,side:any?'flat':'unbound',action:'hold'};
  }
  function posText(p,unit){
    if(!p||p.status==='unbound'||p.side==='unbound')return 'unbound';
    if(p.side==='flat')return 'flat';
    const a=[p.side];
    if(p.pos_pct!==null)a.push(`pos ${nf2.format(p.pos_pct)}%`);
    if(p.lev!==null)a.push(`${nf2.format(p.lev).replace(/\.00$/,'')}x`);
    if(p.entry!==null)a.push(`entry ${fmtP(p.entry)}`);
    a.push(`uPNL ${fmtMoney(p.upnl_usdt,unit)} / ${fmtPct(p.upnl_pct)}`);
    if(p.liq_buffer_pct!==null)a.push(`liq ${fmtPct(p.liq_buffer_pct)}`);
    if(p.funding_8h_pct!==null)a.push(`fund ${fmtPct(p.funding_8h_pct)}`);
    a.push(p.action||'hold');
    return a.join(' · ');
  }
  function knownCount(t){const u=t.toUpperCase();return SYMBOLS.reduce((n,s)=>n+(u.includes(s)?1:0),0);}
  function visible(el){const r=el.getBoundingClientRect();const cs=getComputedStyle(el);return r.width>40&&r.height>30&&cs.display!=='none'&&cs.visibility!=='hidden'&&cs.opacity!=='0';}
  function score(el,s){
    const r=el.getBoundingClientRect(),t=(el.textContent||'').toUpperCase();
    if(!t.includes(s)||knownCount(t)>1||!visible(el))return-1;
    if(r.width<140||r.height<70||r.width>920||r.height>780)return-1;
    if(['HTML','BODY','SCRIPT','STYLE','HEAD'].includes(el.tagName))return-1;
    let sc=1000000-(r.width*r.height);
    if(/card|market|tile|panel/i.test(el.className||''))sc+=50000;
    if(/UNBOUND|SIG=READ_ONLY|RISK=HOLD|XAI|PROOF|SOURCE-REQUIRED/.test(t))sc+=40000;
    if(el.closest('.zel-obx-v3-card'))sc-=100000;
    return sc;
  }
  function findCard(s){
    if(state.cards[s]&&document.contains(state.cards[s]))return state.cards[s];
    const owned=document.querySelector(`[data-zel-obx-v3-card="1"][data-symbol="${s}"]`);
    if(owned){state.cards[s]=owned;return owned;}
    const pool=Array.from(document.querySelectorAll('[data-symbol],[data-pair],[data-market],article,section,div,li'));
    let best=null,b=-1; for(const el of pool){const sc=score(el,s); if(sc>b){best=el;b=sc;}}
    if(best){state.cards[s]=best;return best;} return null;
  }
  function barWidth(q,max){q=num(q);max=num(max); if(!q||!max)return'0%'; return `${Math.max(5,Math.min(100,q/max*100))}%`;}
  function ladderRow(price,qty,kind,max){const r=$('div',`zel-obx-v3-r zel-obx-v3-${kind}`); const em=$('em'); em.style.width=barWidth(qty,max); const p=$('span','p',fmtP(price)); const q=$('span','q',fmtQ(qty)); r.append(em,p,q); return r;}
  function ticket(m,focus){
    const box=$('div','zel-obx-v3-ticket');
    box.append(Object.assign($('div','zel-obx-v3-colhead'),{innerHTML:'<span>Price</span><span style="text-align:right">Amount</span>'}));
    const ladder=$('div','zel-obx-v3-ladder');
    const asks=(m.asks||[]).slice(0,focus?5:3).reverse();
    const bids=(m.bids||[]).slice(0,focus?5:3);
    const max=Math.max(1,...asks.map(x=>num(x[1])||0),...bids.map(x=>num(x[1])||0));
    asks.forEach(x=>ladder.append(ladderRow(x[0],x[1],'ask',max)));
    const last=$('div','zel-obx-v3-last'); last.append($('b','',fmtP(m.last)),$('span','',m.bound?'LAST':'NO SOURCE')); ladder.append(last);
    bids.forEach(x=>ladder.append(ladderRow(x[0],x[1],'bid',max)));
    if(!asks.length&&!bids.length){ladder.append(ladderRow(null,null,'ask',1));ladder.append(last);ladder.append(ladderRow(null,null,'bid',1));}
    box.append(ladder); return box;
  }
  function pill(label,val){const d=$('div','zel-obx-v3-pill'); d.append($('span','',label),$('b','',val)); return d;}
  function posLine(label,txt,cls){const d=$('div',`zel-obx-v3-pos ${cls}`); d.append($('span','',label),$('b','',txt)); return d;}
  function renderCard(el,s){
    const m=state.market[s]||{symbol:s,asks:[],bids:[],last:null,spread_pct:null,source:'unbound',bound:false};
    const live=findPos(s,'live'), virt=findPos(s,'virtual'), focus=state.focus===s;
    el.dataset.zelObxV3Card='1'; el.dataset.symbol=s;
    el.classList.remove('zel-mb-v2-card','zel-mb-v2-focus','zel-mb-v2-mini');
    el.classList.add('zel-obx-v3-card'); el.classList.toggle('zel-obx-v3-focus',focus); el.classList.toggle('zel-obx-v3-mini',!focus);
    el.replaceChildren();
    const top=$('div','zel-obx-v3-top'), pair=$('div','zel-obx-v3-pair'), btn=$('button','zel-obx-v3-view',focus?'FOCUS':'VIEW');
    btn.type='button'; btn.onclick=()=>{state.focus=s;window.__ZEL_OBX_FOCUS__=s;renderAll();};
    pair.append($('strong','',s),$('small','',m.source||'unbound')); top.append(pair,btn); el.append(top);
    const tb=$('div','zel-obx-v3-toolbar'); tb.append(pill('last',fmtP(m.last)),pill('spread',fmtPct(m.spread_pct))); el.append(tb);
    const ratio=m.asks?.[0]&&m.bids?.[0]?50:50; const bl=$('div','zel-obx-v3-buyline'); bl.append(Object.assign($('i'),{style:`width:${ratio}%`}),Object.assign($('i'),{style:`width:${100-ratio}%`})); el.append(bl);
    el.append(ticket(m,focus));
    const pg=$('div','zel-obx-v3-posgrid'); pg.append(posLine('LIVE',posText(live,'USDT'),'zel-obx-v3-live'),posLine('VIRTUAL',posText(virt,'vUSDT'),'zel-obx-v3-virtual')); el.append(pg);
    const foot=$('div','zel-obx-v3-foot'); foot.append($('span','zel-obx-v3-chip',`action ${live.action||virt.action||'hold'}`),$('span',`zel-obx-v3-chip ${m.bound?'':'warn'}`,m.bound?'market-bound':'market-unbound')); el.append(foot);
  }
  function compactSourceHold(){
    for(const el of document.querySelectorAll('div,span,section,aside,footer')){
      const t=(el.textContent||'').trim(); if(!t||t.length>560)continue;
      if(t.includes('SOURCE HOLD V34')||t.includes('missing:price')||t.includes('MinData missing')){el.classList.add('zel-obx-v3-source-compact'); el.textContent='SOURCE HOLD · DATA_HOLD · MinData missing · no execution';}
    }
  }
  function note(msg){let n=document.getElementById('zel-obx-v3-note'); if(!n){n=$('div','zel-obx-v3-note'); n.id='zel-obx-v3-note'; document.body.append(n);} n.textContent=msg; setTimeout(()=>{if(n&&n.parentNode)n.remove();},5600);}
  function renderAll(){let c=0; for(const s of SYMBOLS){const card=findCard(s); if(card){renderCard(card,s);c++;}} state.rendered=c; compactSourceHold(); note(c?`ZEL OBX V3 active · exchange style · cards=${c}`:'ZEL OBX V3 loaded · cards=0');}
  async function refresh(){await Promise.all([Promise.all(SYMBOLS.map(async s=>{state.market[s]=await loadMarket(s);})),loadPortfolio()]); renderAll();}
  function boot(){let tries=0; const timer=setInterval(()=>{tries++; renderAll(); if(state.rendered>=5||tries>18)clearInterval(timer);},420); refresh(); setInterval(refresh,10000); setInterval(compactSourceHold,2500);}
  if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',boot,{once:true}); else boot();
})();
