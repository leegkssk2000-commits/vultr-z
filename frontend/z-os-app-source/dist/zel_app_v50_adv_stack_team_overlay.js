/* ZEL APP V50: Advanced ZEL Stack compact team overlay. Does not mutate market/orderbook cards. */
(function(){
  'use strict';
  var VER='V50';
  var SYMBOLS=['BTCUSDT','ETHUSDT','SOLUSDT','XRPUSDT','LINKUSDT'];
  var state={root:null,lastHtml:'',lastAt:0,seq:0};

  function ready(fn){ if(document.readyState==='loading') document.addEventListener('DOMContentLoaded',fn,{once:true}); else fn(); }
  function txt(el){ return (el && (el.textContent||'') || '').replace(/\s+/g,' ').trim(); }
  function esc(s){ return String(s==null?'':s).replace(/[&<>"']/g,function(c){return {'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c];}); }
  function fmt(n, digits){
    var x=Number(n); if(!Number.isFinite(x)) return '—';
    var d=digits==null ? (Math.abs(x)>=1000?1:Math.abs(x)>=10?3:4) : digits;
    return x.toLocaleString('en-US',{maximumFractionDigits:d,minimumFractionDigits:0});
  }
  function pickNumber(s){
    var m=String(s||'').replace(/,/g,'').match(/-?\d+(?:\.\d+)?/);
    return m ? Number(m[0]) : null;
  }
  function pct(s){
    if(s==null || s==='') return '—';
    if(typeof s==='number') return (Math.abs(s)<=1 ? (s*100) : s).toFixed(2).replace(/\.00$/,'')+'%';
    var str=String(s); if(str.indexOf('%')>=0) return str; var n=pickNumber(str); return n==null?'—':pct(n);
  }

  function installLegacySink(){
    var id='zel-v50-legacy-sink';
    var sink=document.getElementById(id);
    if(!sink){
      sink=document.createElement('div');
      sink.id=id;
      sink.setAttribute('data-zel-v50-legacy-sink','1');
      sink.setAttribute('aria-hidden','true');
      sink.style.cssText='display:none!important;position:absolute!important;left:-99999px!important;top:-99999px!important;width:0!important;height:0!important;overflow:hidden!important;';
      if(document.body.firstChild) document.body.insertBefore(sink,document.body.firstChild); else document.body.appendChild(sink);
    }
    ['data-zel-v49-adv-root','data-zel-v48-adv-root','data-zel-v47-adv-root'].forEach(function(a){ sink.setAttribute(a,'1'); });
  }

  function hasMarketCardSignature(el){
    var t=txt(el).slice(0,400);
    return /LIVE FUTURES|ORDER RO|ticks \d+|spr\s/.test(t) && /BTCUSDT|ETHUSDT|SOLUSDT|XRPUSDT|LINKUSDT/.test(t);
  }
  function candidateScore(el){
    if(!el || el===document.body || el===document.documentElement) return -1;
    if(el.id==='zel-v50-legacy-sink' || el.closest('[data-zel-v50-legacy-sink]')) return -1;
    var t=txt(el);
    if(!/Advanced ZEL stack/i.test(t)) return -1;
    if(hasMarketCardSignature(el) && !/ZEL DECISION STACK|LIVE \/ REAL|Virtual \/ Strategy|Lane \/ Team|Advisor Context|Live \/ Virtual \/ Guard/i.test(t)) return -1;
    var r=el.getBoundingClientRect();
    if(r.width<240 || r.height<35) return -1;
    var score=0;
    if(/^Advanced ZEL stack/i.test(t)) score+=80;
    if(/Advanced ZEL stack/i.test(t.slice(0,220))) score+=60;
    if(/ZEL DECISION STACK|LIVE \/ REAL|Virtual \/ Strategy|Lane \/ Team|Advisor Context|Live \/ Virtual \/ Guard/i.test(t)) score+=40;
    if(r.width>=300 && r.width<=900) score+=20;
    if(r.height>=160) score+=20;
    // Prefer compact panel, not whole app shell.
    score -= Math.max(0,(r.width-920))/10;
    score -= Math.max(0,(r.height-1800))/20;
    return score;
  }
  function findAdvRoot(){
    var current=document.querySelector('[data-zel-v50-adv-root="1"]');
    if(current && document.body.contains(current)) return current;
    var nodes=Array.prototype.slice.call(document.querySelectorAll('section,article,div,main'));
    var best=null, bestScore=-1;
    nodes.forEach(function(el){
      var sc=candidateScore(el);
      if(sc>bestScore){ bestScore=sc; best=el; }
    });
    if(bestScore<0) return null;
    return best;
  }

  function symbolCard(symbol){
    var all=Array.prototype.slice.call(document.querySelectorAll('section,article,div'));
    var best=null, bestScore=-1;
    all.forEach(function(el){
      if(el.closest('[data-zel-v50-adv-root="1"],#zel-v50-legacy-sink')) return;
      var t=txt(el);
      if(t.indexOf(symbol)<0) return;
      var r=el.getBoundingClientRect();
      if(r.width<140 || r.height<80 || r.height>900) return;
      var sc=0;
      if(new RegExp('^'+symbol+'\\b').test(t)) sc+=40;
      if(/LIVE FUTURES|ORDER RO|ticks|spr|unbound|source-bound/.test(t)) sc+=35;
      if(r.width>=180 && r.width<=720) sc+=15;
      sc-=Math.max(0,t.length-1600)/80;
      if(sc>bestScore){bestScore=sc;best=el;}
    });
    return best;
  }
  function readCard(symbol){
    var el=symbolCard(symbol), t=txt(el), price=null, chg=null;
    if(el){
      var priceNode=el.querySelector('.z46-price,.z47-price,.z49-price,[data-price],.price');
      if(priceNode) price=pickNumber(priceNode.textContent);
      if(price==null){
        var after=t.replace(symbol,'');
        price=pickNumber(after);
      }
      var cm=t.match(/[-+]?\d+(?:\.\d+)?%/); if(cm) chg=cm[0];
    }
    return {symbol:symbol,price:price,chg:chg||'—',text:t,card:el};
  }
  function readExchange(){
    var out={}; SYMBOLS.forEach(function(s){out[s]=readCard(s);}); return out;
  }
  function readLiveAccount(symText){
    var s=symText||'';
    function rx(label){ var m=s.match(new RegExp(label+'\\s*([—\\-]|[-+]?\\d+(?:\\.\\d+)?%?)','i')); return m?m[1]:'—'; }
    var pos=rx('LIVE POS');
    var lev=rx('LEV');
    var upnl=rx('UPNL|uPNL');
    var liq=rx('LIQ');
    return {pos:pos||'—', lev:lev||'—', upnl:upnl||'—', liq:liq||'—'};
  }
  function readVirtual(){
    var t=txt(document.body);
    function first(re){ var m=t.match(re); return m?m[1]:'—'; }
    return {
      pos:first(/VIRT(?:UAL)?\s+POS\s*([—\-]|[-+]?\d+(?:\.\d+)?%?)/i),
      lev:first(/V\.?(?:IRT)?\s*LEV\s*([—\-]|[-+]?\d+(?:\.\d+)?x?)/i),
      upnl:first(/V\.?PNL\s*([—\-]|[-+]?\d+(?:\.\d+)?%?)/i),
      dd:first(/\bDD\s*([—\-]|[-+]?\d+(?:\.\d+)?%?)/i)
    };
  }
  function deriveGuard(){
    var t=txt(document.body);
    if(/orders?\s+blocked|ORDER RO|read-only|no app-side execution/i.test(t)) return {mode:'ORDER RO · DATA HOLD',proof:/proof\s*(pending|missing)/i.test(t)?'pending':'required'};
    return {mode:'READ-ONLY HOLD',proof:'pending'};
  }
  function teamStatus(){
    return [
      {key:'alpha',name:'Alpha',role:'primary',desc:'주 경로. 추세 유지 시 우선, proof stale이면 자동 감속.',mode:'ACTIVE',score:'pending',guard:'clear'},
      {key:'beta',name:'Beta',role:'standby',desc:'횡보·범위장 대비. Alpha 감속 시 fallback 후보.',mode:'READY',score:'pending',guard:'watch'},
      {key:'gamma',name:'Gamma',role:'probe',desc:'변동성·돌파 탐색. 소량 검증용 보조 경로.',mode:'PROBE',score:'pending',guard:'watch'},
      {key:'delta',name:'Delta',role:'guard',desc:'위험 차단·거부권. DD/liq/proof 위반 우선 감시.',mode:'GUARD',score:'pending',guard:'clear'}
    ];
  }

  function html(){
    var ex=readExchange(), btc=ex.BTCUSDT || {}, live=readLiveAccount(btc.text||''), virt=readVirtual(), guard=deriveGuard();
    var price=fmt(btc.price,1);
    var cards=teamStatus().map(function(tm){return ''+
      '<div class="zel-v50-team-card '+tm.key+'">'+
        '<div class="zel-v50-team-row"><div class="zel-v50-team-name">'+esc(tm.name)+'</div><div class="zel-v50-team-role">'+esc(tm.role)+'</div></div>'+
        '<div class="zel-v50-team-desc">'+esc(tm.desc)+'</div>'+
        '<div class="zel-v50-team-metrics">'+
          '<div class="zel-v50-mini"><b>mode</b><span>'+esc(tm.mode)+'</span></div>'+
          '<div class="zel-v50-mini"><b>score</b><span>'+esc(tm.score)+'</span></div>'+
          '<div class="zel-v50-mini"><b>guard</b><span>'+esc(tm.guard)+'</span></div>'+
          '<div class="zel-v50-mini"><b>route</b><span>locked</span></div>'+
        '</div>'+
      '</div>';}).join('');
    var feedCount=SYMBOLS.filter(function(s){return ex[s] && Number.isFinite(ex[s].price);}).length;
    return ''+
    '<div class="zel-v50-adv" data-zel-v50-panel="1">'+
      '<div class="zel-v50-top">'+
        '<div><div class="zel-v50-kicker">Advanced ZEL stack</div><div class="zel-v50-title">Live / Virtual / Team Guard</div><div class="zel-v50-sub">시장카드 호가창은 유지. 이 영역은 계좌·가상·팀 경로·감사 상태만 압축 표시.</div></div>'+
        '<button class="zel-v50-close" type="button" data-zel-v50-close="1">close</button>'+ 
      '</div>'+
      '<div class="zel-v50-grid">'+
        '<section class="zel-v50-box live"><div class="zel-v50-label">live account · BTCUSDT</div><div class="zel-v50-price">'+esc(price)+'</div><div class="zel-v50-pair">'+
          '<div class="zel-v50-stat"><b>pos</b><span>'+esc(live.pos)+'</span></div>'+
          '<div class="zel-v50-stat"><b>lev</b><span>'+esc(live.lev)+'</span></div>'+ 
          '<div class="zel-v50-stat"><b>uPNL</b><span>'+esc(live.upnl)+'</span></div>'+ 
          '<div class="zel-v50-stat"><b>liq</b><span>'+esc(live.liq)+'</span></div>'+ 
        '</div></section>'+ 
        '<section class="zel-v50-box virtual"><div class="zel-v50-label">virtual / paper</div><div class="zel-v50-price">'+esc(virt.upnl!=='—'?virt.upnl:'—')+'</div><div class="zel-v50-pair">'+
          '<div class="zel-v50-stat"><b>v.pos</b><span>'+esc(virt.pos)+'</span></div>'+ 
          '<div class="zel-v50-stat"><b>v.lev</b><span>'+esc(virt.lev)+'</span></div>'+ 
          '<div class="zel-v50-stat"><b>v.uPNL</b><span>'+esc(virt.upnl)+'</span></div>'+ 
          '<div class="zel-v50-stat"><b>DD</b><span>'+esc(virt.dd)+'</span></div>'+ 
        '</div></section>'+ 
      '</div>'+ 
      '<div class="zel-v50-grid">'+
        '<section class="zel-v50-box guard"><div class="zel-v50-label">execution guard</div><div class="zel-v50-price" style="font-size:22px;letter-spacing:-.02em">'+esc(guard.mode)+'</div><div class="zel-v50-pair">'+
          '<div class="zel-v50-stat"><b>proof</b><span>'+esc(guard.proof)+'</span></div>'+ 
          '<div class="zel-v50-stat"><b>uPNL source</b><span>pending</span></div>'+ 
        '</div></section>'+ 
        '<section class="zel-v50-box"><div class="zel-v50-label">5-card live feed</div><div class="zel-v50-price" style="font-size:22px;letter-spacing:-.02em">'+feedCount+'/5 symbols</div><div class="zel-v50-pair">'+
          '<div class="zel-v50-stat"><b>BTC</b><span>'+esc(fmt(ex.BTCUSDT.price,1))+'</span></div>'+ 
          '<div class="zel-v50-stat"><b>ETH</b><span>'+esc(fmt(ex.ETHUSDT.price,1))+'</span></div>'+ 
          '<div class="zel-v50-stat"><b>SOL</b><span>'+esc(fmt(ex.SOLUSDT.price,3))+'</span></div>'+ 
          '<div class="zel-v50-stat"><b>XRP/LINK</b><span>'+esc(fmt(ex.XRPUSDT.price,4))+' / '+esc(fmt(ex.LINKUSDT.price,3))+'</span></div>'+ 
        '</div></section>'+ 
      '</div>'+ 
      '<section class="zel-v50-team"><div class="zel-v50-team-head"><div><h3>Team route overlay</h3><p>Alpha/Beta/Gamma/Delta를 한 오버레이 규격으로 통일. 실제 주문 경로는 계속 read-only.</p></div><span class="zel-v50-pill">single overlay</span></div><div class="zel-v50-teams">'+cards+'</div></section>'+ 
      '<div class="zel-v50-audit">exchange feed live · CF/GS proof pending · source_hash pending · source-bound gate keeps final ZEL action read-only</div>'+ 
    '</div>';
  }

  function hideLegacyNear(root){
    if(!root) return;
    root.removeAttribute('data-zel-v49-adv-root');
    root.removeAttribute('data-zel-v48-adv-root');
    root.removeAttribute('data-zel-v47-adv-root');
    var nodes=Array.prototype.slice.call(document.querySelectorAll('[data-zel-v49-adv-root="1"],[data-zel-v48-adv-root="1"],[data-zel-v47-adv-root="1"]'));
    nodes.forEach(function(el){ if(el.id!=='zel-v50-legacy-sink') el.setAttribute('data-zel-v50-hidden-legacy','1'); });
  }
  function render(force){
    installLegacySink();
    var root=state.root && document.body.contains(state.root) ? state.root : findAdvRoot();
    if(!root) return false;
    state.root=root;
    hideLegacyNear(root);
    root.setAttribute('data-zel-v50-adv-root','1');
    root.setAttribute('data-zel-v50-owner','team-overlay');
    var next=html();
    if(force || next!==state.lastHtml || !root.querySelector('.zel-v50-adv')){
      root.innerHTML=next;
      state.lastHtml=next;
      state.lastAt=Date.now();
    }
    var btn=root.querySelector('[data-zel-v50-close="1"]');
    if(btn && !btn.__zelV50Close){ btn.__zelV50Close=true; btn.addEventListener('click',function(){ root.style.display='none'; }); }
    return true;
  }
  function start(){
    installLegacySink();
    render(true);
    setInterval(function(){ render(false); }, 1800);
    var mo=new MutationObserver(function(){
      state.seq++; var my=state.seq;
      setTimeout(function(){ if(my===state.seq) render(false); },120);
    });
    mo.observe(document.documentElement,{childList:true,subtree:true});
    window.ZEL_APP_V50_ADV_STACK={version:VER,render:function(){return render(true);},state:state};
  }
  ready(start);
})();
