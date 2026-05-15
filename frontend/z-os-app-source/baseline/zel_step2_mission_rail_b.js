(() => {
  "use strict";
  const VERSION = "ZEL_STEP2_MISSION_RAIL_B_FIX1";
  const ID = "zel-step2-mission-rail-b";
  const OLD_IDS = [
    "zel-mission-control-dock-v1",
    "zel-mission-control-dock-v2",
    "zel-mission-control-dock-v3",
    "zel-step2-mission-control-rebuild-a"
  ];
  const state = { restoredCount:0, updateCount:0, mutationTick:0, last:null };

  function norm(s){ return String(s || "").replace(/\s+/g," ").trim(); }
  function removeOld(){ OLD_IDS.forEach(id => document.querySelectorAll("#"+id).forEach(el => el.remove())); }
  function shell(){
    const div = document.createElement("div");
    div.innerHTML = '<section id="'+ID+'" data-version="'+VERSION+'" data-expanded="0" data-owner="body-portal">'+
      '<div class="z2b-shell"><div class="z2b-top">'+
      '<div class="z2b-main"><div class="z2b-kicker">ZEL Mission Rail</div><div class="z2b-title" data-z2b-title>boot · hold · proof pending</div></div>'+
      '<div class="z2b-right"><div class="z2b-state" data-z2b-state>BOOT</div><button class="z2b-btn" type="button" data-z2b-toggle>open</button></div>'+
      '</div><div class="z2b-body"><div class="z2b-rail">'+
      '<span class="z2b-chip" data-sev="pending" data-z2b-chip="truth"><i class="z2b-dot"></i><span>truth: loading</span></span>'+
      '<span class="z2b-chip" data-sev="hold" data-z2b-chip="decision"><i class="z2b-dot"></i><span>decision: hold</span></span>'+
      '<span class="z2b-chip" data-sev="pending" data-z2b-chip="proof"><i class="z2b-dot"></i><span>proof: pending</span></span>'+
      '</div><div class="z2b-grid">'+
      '<div class="z2b-row"><b>Decision</b><span data-z2b-decision>initializing · no execution</span></div>'+
      '<div class="z2b-row"><b>Guard</b><span data-z2b-guard>compact rail · no app relocation</span></div>'+
      '<div class="z2b-row"><b>Missing</b><span data-z2b-missing>unbound</span></div>'+
      '</div><div class="z2b-foot"><span>Step2 Mission Rail B fix1</span><code data-z2b-time>BOOT</code></div>'+
      '</div></div></section>';
    return div.firstElementChild;
  }
  function ensure(){
    removeOld();
    let rails = Array.from(document.querySelectorAll("#"+ID));
    if(rails.length > 1){ rails.slice(1).forEach(el => el.remove()); rails = rails.slice(0,1); }
    let rail = rails[0];
    if(!rail){ rail = shell(); document.body.appendChild(rail); state.restoredCount += 1; }
    else if(rail.parentElement !== document.body){ document.body.appendChild(rail); state.restoredCount += 1; }
    rail.dataset.version = VERSION;
    rail.dataset.owner = "body-portal";
    if(!rail.hasAttribute("data-expanded")) rail.setAttribute("data-expanded","0");
    bind(rail);
    return rail;
  }
  function pageText(){
    let t = norm(document.body?.textContent || "");
    const self = document.getElementById(ID);
    if(self) t = norm(t.replace(norm(self.textContent || ""), " "));
    OLD_IDS.forEach(id => { const el = document.getElementById(id); if(el) t = norm(t.replace(norm(el.textContent || ""), " ")); });
    return t;
  }
  function extractMissing(t){
    const m = t.match(/missing:?\s*([a-zA-Z0-9_,%\-\s]+?)(?:DATA_HOLD|no execution|Advisor|Evidence|Decision|Dash|Trade|Log|Settings|Bots|$)/i);
    if(m && m[1]) return norm(m[1]).replace(/\s+/g,"").slice(0,120);
    const keys = [];
    ["price","pos_pct","lev","entry_ts","liq_buffer_pct","funding_8h_pct","DD_day_pct","DD_total_pct"].forEach(k => {
      const re = new RegExp(k.replace(/[.*+?^${}()|[\]\\]/g,"\\$&") + "\\s*=\\s*unbound", "i");
      if(re.test(t)) keys.push(k);
    });
    return keys.length ? keys.join(",") : "unbound";
  }
  function extractSymbol(t){
    const u = t.toUpperCase();
    return ["BTCUSDT","ETHUSDT","SOLUSDT","XRPUSDT","LINKUSDT"].find(s => u.includes(s)) || "unbound";
  }
  function snapshot(){
    const t = pageText();
    const l = t.toLowerCase();
    const src = l.includes("source-bound") || l.includes("source bound") ? "source-bound" :
      l.includes("source-required") || l.includes("source required") || l.includes("source-bound required") ? "source-required" : "unbound";
    const proof = l.includes("proof verified") || l.includes("proof pass") ? "pass" :
      l.includes("proof pending") || l.includes("signature pending") || l.includes("receipt pending") ? "pending" : "unbound";
    const order = l.includes("orders blocked") || l.includes("order-blocked") || l.includes("no app-side execution") ? "orders-blocked" :
      l.includes("execution authority none") || l.includes("no execution") ? "no-execution" : "unbound";
    const data = l.includes("data hold") || l.includes("data_hold") || l.includes("mindata missing") ? "DATA_HOLD" : "unbound";
    let reason = "source/proof pending";
    if(/MinData/i.test(t) && /missing|complete/i.test(t)) reason = "MinData/source proof gate";
    else if(/source-bound required|source required/i.test(t)) reason = "source-bound truth required";
    else if(/orders blocked|order-blocked/i.test(t)) reason = "orders blocked";
    return { symbol:extractSymbol(t), action:"hold", reason, missing:extractMissing(t), src, proof, order, data, ts:Date.now() };
  }
  function setText(root, sel, value){ const el = root.querySelector(sel); if(el && el.textContent !== String(value)) el.textContent = String(value); }
  function setChip(root, key, label, value, sev){
    const el = root.querySelector(`[data-z2b-chip="${key}"]`);
    if(!el) return;
    el.setAttribute("data-sev", sev || "pending");
    const span = el.querySelector("span");
    const txt = `${label}: ${value}`;
    if(span && span.textContent !== txt) span.textContent = txt;
  }
  function render(){
    const rail = ensure();
    const s = snapshot();
    state.last = s;
    state.updateCount += 1;
    setText(rail,"[data-z2b-title]",`${s.symbol} · ${s.action} · ${s.reason}`);
    setText(rail,"[data-z2b-state]",s.data);
    setChip(rail,"truth","truth",s.src,s.src === "source-bound" ? "pass" : "hold");
    setChip(rail,"decision","decision",s.action,"hold");
    setChip(rail,"proof","proof",s.proof,s.proof === "pass" ? "pass" : "pending");
    setText(rail,"[data-z2b-decision]",`${s.symbol} | action=${s.action} | ${s.reason}`);
    setText(rail,"[data-z2b-guard]",`${s.data} · ${s.src} · ${s.order} · proof=${s.proof}`);
    setText(rail,"[data-z2b-missing]",s.missing);
    setText(rail,"[data-z2b-time]",new Date(s.ts).toISOString().slice(11,19)+"Z");
    expose();
  }
  function bind(rail){
    if(rail.dataset.bound === "1") return;
    rail.dataset.bound = "1";
    rail.addEventListener("click", ev => {
      const btn = ev.target?.closest?.("[data-z2b-toggle]");
      if(!btn) return;
      const isOpen = rail.getAttribute("data-expanded") === "1";
      rail.setAttribute("data-expanded", isOpen ? "0" : "1");
      btn.textContent = isOpen ? "open" : "close";
      expose();
    });
  }
  function closeOnEscape(ev){
    if(ev.key !== "Escape") return;
    const rail = document.getElementById(ID);
    if(!rail) return;
    rail.setAttribute("data-expanded","0");
    const btn = rail.querySelector("[data-z2b-toggle]");
    if(btn) btn.textContent = "open";
    expose();
  }
  function expose(){
    const rail = document.getElementById(ID);
    window.__ZEL_STEP2_MISSION_RAIL_B__ = {
      version: VERSION,
      inserted: !!rail,
      parent: rail?.parentElement?.tagName || null,
      stableBodyPortal: !!rail && rail.parentElement === document.body,
      expanded: rail?.getAttribute("data-expanded") === "1",
      compactHeightPx: 58,
      maxExpandedPx: 220,
      bottomOffsetPx: 74,
      restoredCount: state.restoredCount,
      updateCount: state.updateCount,
      mutationTick: state.mutationTick,
      last: state.last,
      ts: Date.now()
    };
  }
  function boot(){
    ensure();
    render();
    setInterval(render, 2000);
    setInterval(() => { ensure(); expose(); }, 500);
    try { new MutationObserver(() => { state.mutationTick += 1; ensure(); }).observe(document.documentElement, {childList:true, subtree:true}); } catch(_){ }
    addEventListener("keydown", closeOnEscape);
    expose();
    console.info("[ZEL]", VERSION, "boot");
  }
  if(document.readyState === "loading") document.addEventListener("DOMContentLoaded", boot, {once:true});
  else boot();
})();
