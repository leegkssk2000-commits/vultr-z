async function j(url){const r=await fetch(url);return r.json()}

function num(n){return Number(n||0).toLocaleString()}

async function boot(){
  const s = await j('/api/summary');
  document.getElementById('k_trades').textContent = num(s.trades);
  document.getElementById('k_win').textContent = (s.win_rate||0)+'%';
  document.getElementById('k_pnl').textContent = num(s.pnl_sum);

  const r = await j('/api/routine/status');
  document.getElementById('k_620').textContent = `${r.phase} ${r.progress}%`;

  const m = await j('/api/pnl/monthly');
  new Chart(document.getElementById('pnlChart'),{
    type:'line',
    data:{labels:m.map(x=>x.ym),datasets:[{label:'PnL',data:m.map(x=>x.pnl)}]}
  });

  const sy = await j('/api/winrates/by_symbol');
  new Chart(document.getElementById('symChart'),{
    type:'bar',
    data:{labels:sy.map(x=>x.symbol),datasets:[{label:'Win %',data:sy.map(x=>x.win_rate)}]}
  });

  const st = await j('/api/winrates/by_strategy');
  new Chart(document.getElementById('strChart'),{
    type:'bar',
    data:{labels:st.map(x=>x.strategy),datasets:[{label:'Win %',data:st.map(x=>x.win_rate)}]}
  });

  const ls = await j('/api/winrates/long_short');
  new Chart(document.getElementById('lsChart'),{
    type:'bar',
    data:{labels:ls.map(x=>x.side),datasets:[{label:'Win %',data:ls.map(x=>x.win_rate)}]}
  });

  const sc = await j('/api/scanner/alts');
  const tb = document.querySelector('#scan tbody'); tb.innerHTML='';
  sc.forEach(r=>{
    const tr=document.createElement('tr');
    tr.innerHTML=`<td>${r.symbol}</td><td>${r.change24?.toFixed?.(2)??'-'}</td><td>${num(r.vol24)}</td>`;
    tb.appendChild(tr);
  });
}

fetch("/api/health").then(r=>r.json()).then(j=>{
  document.getElementById("stat").innerText = j.ok ? "API OK" : "API FAIL";
}).catch(()=>{document.getElementById("stat").innerText="API FAIL";});

boot();
