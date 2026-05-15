(() => {
  "use strict";
  const VERSION = "ZEL_STEP2_MISSION_RAIL_C_APPBOUND";
  const ID = "zel-step2-mission-rail-c";
  const OLD_IDS = [
    "zel-mission-control-dock-v1",
    "zel-mission-control-dock-v2",
    "zel-mission-control-dock-v3",
    "zel-step2-mission-control-rebuild-a",
    "zel-step2-mission-rail-b"
  ];

  const state = { updateCount: 0, restoredCount: 0, expanded: false, layout: null, last: null };
  const clamp = (n, lo, hi) => Math.max(lo, Math.min(hi, n));
  const norm = s => String(s || "").replace(/\s+/g, " ").trim();

  function removeOld(){
    OLD_IDS.forEach(id => document.querySelectorAll("#" + id).forEach(el => el.remove()));
  }

  function shell(){
    const tmp = document.createElement("div");
    tmp.innerHTML = `<section id="${ID}" data-version="${VERSION}" data-expanded="0" data-owner="body-portal">
      <div class="z2c-shell">
        <div class="z2c-head">
          <div><span class="z2c-kicker">ZEL Mission Rail</span><strong class="z2c-title" data-z2c-title>boot · source/proof pending</strong></div>
          <span class="z2c-state" data-z2c-state>BOOT</span>
          <button class="z2c-btn" type="button" data-z2c-toggle>open</button>
        </div>
        <div class="z2c-body">
          <div class="z2c-rail">
            <span class="z2c-chip" data-sev="pending" data-z2c-chip="truth">truth: loading</span>
            <span class="z2c-chip" data-sev="hold" data-z2c-chip="decision">decision: hold</span>
            <span class="z2c-chip" data-sev="pending" data-z2c-chip="proof">proof: pending</span>
          </div>
          <div class="z2c-grid">
            <div class="z2c-row"><b>Decision</b><span data-z2c-decision>initializing · no execution</span></div>
            <div class="z2c-row"><b>Guard</b><span data-z2c-guard>app-bound body portal · no full width</span></div>
            <div class="z2c-row"><b>Missing</b><span data-z2c-missing>unbound</span></div>
          </div>
          <div class="z2c-foot"><span data-z2c-foot>Step2 Rail C · app-bound</span><code data-z2c-time>BOOT</code></div>
        </div>
      </div>
    </section>`;
    return tmp.firstElementChild;
  }

  function ensure(){
    removeOld();
    let nodes = Array.from(document.querySelectorAll("#" + ID));
    if(nodes.length > 1){ nodes.slice(1).forEach(n => n.remove()); nodes = nodes.slice(0,1); }
    let el = nodes[0];
    if(!el){ el = shell(); document.body.appendChild(el); state.restoredCount += 1; }
    else if(el.parentElement !== document.body){ document.body.appendChild(el); state.restoredCount += 1; }
    el.dataset.version = VERSION;
    el.dataset.owner = "body-portal";
    if(!el.hasAttribute("data-expanded")) el.dataset.expanded = "0";
    bind(el);
    return el;
  }

  function visibleRect(el){
    if(!el || el.id === ID || OLD_IDS.includes(el.id)) return null;
    if(el.closest && el.closest("#" + ID)) return null;
    const r = el.getBoundingClientRect();
    if(r.width < 280 || r.height < 220) return null;
    if(r.right < 0 || r.left > innerWidth || r.bottom < 0 || r.top > innerHeight) return null;
    return r;
  }

  function scoreApp(el){
    const r = visibleRect(el);
    if(!r) return null;
    const t = norm(el.textContent || "");
    let score = 0;
    const center = r.left + r.width / 2;
    score += 60 - Math.min(60, Math.abs(center - innerWidth / 2) / 8);
    if(r.width >= 340 && r.width <= 680) score += 35;
    if(r.width > innerWidth * 0.82) score -= 45;
    if(/Dash\s+Trade\s+Log\s+Settings\s+Bots/i.test(t)) score += 60;
    if(/ADVISOR MICRO STRIP|EVIDENCE SUMMARY|Advanced ZEL stack/i.test(t)) score += 24;
    if(/BTCUSDT|ETHUSDT|SOLUSDT|XRPUSDT|LINKUSDT/.test(t)) score += 8;
    if(r.top <= 40 && r.bottom >= innerHeight * 0.55) score += 12;
    return {el, r, score};
  }

  function findApp(){
    const sels = ["main", "#root > *", "body > div", "[class*='app' i]", "[class*='shell' i]", "[class*='pwa' i]", "[class*='phone' i]", "[class*='container' i]"];
    const seen = new Set();
    const scored = [];
    sels.forEach(sel => {
      document.querySelectorAll(sel).forEach(el => {
        if(seen.has(el)) return;
        seen.add(el);
        const s = scoreApp(el);
        if(s) scored.push(s);
      });
    });
    scored.sort((a,b) => b.score - a.score);
    return scored[0] || null;
  }

  function scoreNav(el, appRect){
    if(!el || el.id === ID || (el.closest && el.closest("#" + ID))) return null;
    const t = norm(el.textContent || "");
    if(!/Dash\s+Trade\s+Log\s+Settings\s+Bots/i.test(t)) return null;
    const r = el.getBoundingClientRect();
    if(r.width < 240 || r.height < 24 || r.height > 130) return null;
    if(r.bottom < innerHeight - 220) return null;
    let score = 0;
    score += 80 - Math.min(80, Math.abs(r.bottom - innerHeight) / 2);
    if(appRect){
      score += 40 - Math.min(40, Math.abs(r.left - appRect.left) / 4);
      score += 40 - Math.min(40, Math.abs(r.width - appRect.width) / 4);
    }
    return {el, r, score};
  }

  function findNav(appRect){
    const nodes = Array.from(document.querySelectorAll("nav, footer, div, section"));
    const scored = [];
    nodes.forEach(el => { const s = scoreNav(el, appRect); if(s) scored.push(s); });
    scored.sort((a,b) => b.score - a.score);
    return scored[0] || null;
  }

  function applyLayout(){
    const rail = ensure();
    const app = findApp();
    const vw = innerWidth || document.documentElement.clientWidth || 390;
    const vh = innerHeight || document.documentElement.clientHeight || 800;

    let left, width, transform = "none";
    let appRect = app && app.r;
    if(appRect){
      const inset = vw <= 560 ? 8 : 10;
      width = clamp(Math.floor(appRect.width - inset * 2), 280, Math.min(620, vw - 16));
      left = Math.round(appRect.left + (appRect.width - width) / 2);
    } else {
      width = Math.min(520, Math.max(280, vw - 20));
      left = Math.round((vw - width) / 2);
    }

    const nav = findNav(appRect);
    let bottom = vw <= 560 ? 76 : 78;
    if(nav && nav.r){
      bottom = clamp(Math.ceil(vh - nav.r.top + 8), 60, 150);
    }

    rail.style.setProperty("--z2c-left", left + "px");
    rail.style.setProperty("--z2c-width", width + "px");
    rail.style.setProperty("--z2c-transform", transform);
    rail.style.setProperty("--z2c-bottom", bottom + "px");
    state.layout = { left, width, bottom, appFound: !!app, navFound: !!nav, appScore: app ? Math.round(app.score) : null };
    expose();
  }

  function pageText(){
    let t = norm(document.body ? document.body.textContent : "");
    const self = document.getElementById(ID);
    if(self) t = norm(t.replace(norm(self.textContent || ""), " "));
    return t;
  }

  function missing(t){
    const m = t.match(/missing:?\s*([a-zA-Z0-9_,%\-\s]+?)(?:DATA_HOLD|no execution|Advisor|Evidence|Decision|Dash|Trade|Log|Settings|Bots|$)/i);
    if(m && m[1]) return norm(m[1]).replace(/\s+/g, "").slice(0, 110);
    const keys = [];
    ["price","pos_pct","lev","entry_ts","liq_buffer_pct","funding_8h_pct","DD_day_pct","DD_total_pct"].forEach(k => {
      const re = new RegExp(k.replace(/[.*+?^${}()|[\]\\]/g, "\\$&") + "\\s*=\\s*unbound", "i");
      if(re.test(t)) keys.push(k);
    });
    return keys.length ? keys.join(",") : "unbound";
  }

  function snapshot(){
    const t = pageText();
    const l = t.toLowerCase();
    const symbol = ["BTCUSDT","ETHUSDT","SOLUSDT","XRPUSDT","LINKUSDT"].find(s => t.toUpperCase().includes(s)) || "unbound";
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
    return {symbol, action:"hold", reason, src, proof, order, data, missing: missing(t), ts: Date.now()};
  }

  function setText(root, sel, val){ const el = root.querySelector(sel); if(el && el.textContent !== String(val)) el.textContent = String(val); }
  function setChip(root, key, label, val, sev){
    const el = root.querySelector(`[data-z2c-chip="${key}"]`);
    if(!el) return;
    el.dataset.sev = sev || "pending";
    const txt = `${label}: ${val}`;
    if(el.textContent !== txt) el.textContent = txt;
  }

  function render(){
    const rail = ensure();
    const s = snapshot();
    state.last = s;
    state.updateCount += 1;
    setText(rail, "[data-z2c-title]", `${s.symbol} · ${s.action} · ${s.reason}`);
    setText(rail, "[data-z2c-state]", s.data);
    setChip(rail, "truth", "truth", s.src, s.src === "source-bound" ? "pass" : "hold");
    setChip(rail, "decision", "decision", s.action, "hold");
    setChip(rail, "proof", "proof", s.proof, s.proof === "pass" ? "pass" : "pending");
    setText(rail, "[data-z2c-decision]", `${s.symbol} | action=${s.action} | ${s.reason}`);
    setText(rail, "[data-z2c-guard]", `${s.data} · ${s.src} · ${s.order} · proof=${s.proof}`);
    setText(rail, "[data-z2c-missing]", s.missing);
    setText(rail, "[data-z2c-time]", new Date(s.ts).toISOString().slice(11,19) + "Z");
    applyLayout();
    expose();
  }

  function bind(rail){
    if(rail.dataset.bound === "1") return;
    rail.dataset.bound = "1";
    rail.addEventListener("click", ev => {
      const btn = ev.target && ev.target.closest && ev.target.closest("[data-z2c-toggle]");
      if(!btn) return;
      const exp = rail.dataset.expanded === "1";
      rail.dataset.expanded = exp ? "0" : "1";
      btn.textContent = exp ? "open" : "close";
      state.expanded = !exp;
      requestAnimationFrame(applyLayout);
      expose();
    });
  }

  function expose(){
    const rail = document.getElementById(ID);
    window.__ZEL_STEP2_MISSION_RAIL_C__ = {
      version: VERSION,
      inserted: !!rail,
      stableBodyPortal: !!rail && rail.parentElement === document.body,
      parent: rail && rail.parentElement ? rail.parentElement.tagName : null,
      expanded: rail ? rail.dataset.expanded === "1" : false,
      appBound: !!(state.layout && state.layout.appFound),
      navBound: !!(state.layout && state.layout.navFound),
      layout: state.layout,
      restoredCount: state.restoredCount,
      updateCount: state.updateCount,
      last: state.last,
      preboot: window.__ZEL_STEP2_MISSION_RAIL_C_PREBOOT__ || null,
      ts: Date.now()
    };
  }

  function boot(){
    ensure();
    render();
    setInterval(render, 2000);
    setInterval(() => { ensure(); applyLayout(); expose(); }, 350);
    try { new MutationObserver(() => { ensure(); requestAnimationFrame(applyLayout); }).observe(document.documentElement, {childList:true, subtree:true}); } catch(_){ }
    addEventListener("resize", () => requestAnimationFrame(applyLayout), {passive:true});
    addEventListener("orientationchange", () => setTimeout(applyLayout, 120), {passive:true});
    addEventListener("scroll", () => requestAnimationFrame(applyLayout), {passive:true});
    console.info("[ZEL]", VERSION, "boot");
    expose();
  }

  if(document.readyState === "loading") document.addEventListener("DOMContentLoaded", boot, {once:true});
  else boot();
})();
