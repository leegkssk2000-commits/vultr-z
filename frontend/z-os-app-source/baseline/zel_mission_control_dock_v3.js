(() => {
  "use strict";

  const VERSION = "ZEL_MISSION_CONTROL_DOCK_V3_STABLE";
  const ID = "zel-mission-control-dock-v3";
  const OLD_IDS = ["zel-mission-control-dock-v1", "zel-mission-control-dock-v2"];

  const state = {
    inserted: false,
    stable: true,
    collapsed: false,
    last: null,
    restoredCount: 0,
    updateCount: 0,
    ts: Date.now()
  };

  function norm(s) {
    return String(s || "").replace(/\s+/g, " ").trim();
  }

  function textOf(el) {
    return norm(el?.textContent || "");
  }

  function pageText() {
    let t = textOf(document.body);
    const dock = document.getElementById(ID);
    if (dock) t = t.replace(textOf(dock), "");
    for (const old of OLD_IDS) {
      const el = document.getElementById(old);
      if (el) t = t.replace(textOf(el), "");
    }
    return norm(t);
  }

  function removeOld() {
    for (const old of OLD_IDS) {
      const el = document.getElementById(old);
      if (el) el.remove();
    }
  }

  function skeletonHtml() {
    return `<section id="${ID}" data-version="${VERSION}" data-collapsed="0">
      <div class="zel-mcd-v3-head">
        <div>
          <div class="zel-mcd-v3-kicker">ZEL Mission Control Dock</div>
          <div class="zel-mcd-v3-title">boot · source/proof pending</div>
        </div>
        <div class="zel-mcd-v3-actions">
          <div class="zel-mcd-v3-state">BOOT</div>
          <button class="zel-mcd-v3-toggle" type="button" data-zmc-toggle="1">fold</button>
        </div>
      </div>
      <div class="zel-mcd-v3-body">
        <div class="zel-mcd-v3-rail">
          <span class="zel-mcd-v3-chip" data-sev="pending"><i class="zel-mcd-v3-dot"></i>truth: loading</span>
          <span class="zel-mcd-v3-chip" data-sev="hold"><i class="zel-mcd-v3-dot"></i>decision: hold</span>
          <span class="zel-mcd-v3-chip" data-sev="pending"><i class="zel-mcd-v3-dot"></i>proof: pending</span>
        </div>
        <div class="zel-mcd-v3-strip">
          <div class="zel-mcd-v3-row"><b>Decision</b><span>initializing · no execution</span></div>
          <div class="zel-mcd-v3-row"><b>Guard</b><span>body-portal stable · no dashboard relocation</span></div>
        </div>
        <div class="zel-mcd-v3-mini">
          <div><label>LIVE</label><strong>read-only</strong></div>
          <div><label>VIRTUAL</label><strong>route pending</strong></div>
          <div><label>TEAM</label><strong>advisor pending</strong></div>
        </div>
        <div class="zel-mcd-v3-foot"><span>Step2 v3 stable portal</span><code>BOOT</code></div>
      </div>
    </section>`;
  }

  function ensureDock() {
    removeOld();

    let nodes = Array.from(document.querySelectorAll("#" + ID));
    if (nodes.length > 1) {
      nodes.slice(1).forEach(n => n.remove());
      nodes = nodes.slice(0, 1);
    }

    let dock = nodes[0] || null;
    if (!dock) {
      const tmp = document.createElement("div");
      tmp.innerHTML = skeletonHtml().trim();
      dock = tmp.firstElementChild;
      document.body.appendChild(dock);
      state.restoredCount += 1;
    } else if (dock.parentElement !== document.body) {
      document.body.appendChild(dock);
      state.restoredCount += 1;
    }

    state.inserted = true;
    bindToggle(dock);
    measureDock();
    return dock;
  }

  function measureDock() {
    try {
      const dock = document.getElementById(ID);
      const h = dock ? Math.ceil(dock.getBoundingClientRect().height || 0) : 0;
      document.documentElement.style.setProperty("--zel-mcd-v3-h", h + "px");
      document.body.classList.add("zel-mcd-v3-pad");
    } catch (_) {}
  }

  function extractMissingKeys(t) {
    const m = t.match(/missing:?\s*([a-zA-Z0-9_,%\-\s]+?)(?:DATA_HOLD|no execution|Advisor|Evidence|Decision|Dash|Trade|Log|Settings|Bots|$)/i);
    if (m && m[1]) return norm(m[1]).replace(/\s+/g, "").slice(0, 120);

    const keys = [];
    for (const k of ["price", "pos_pct", "lev", "entry_ts", "liq_buffer_pct", "funding_8h_pct", "DD_day_pct", "DD_total_pct"]) {
      const re = new RegExp(k.replace(/[.*+?^${}()|[\]\\]/g, "\\$&") + "\\s*=\\s*unbound", "i");
      if (re.test(t)) keys.push(k);
    }
    return keys.length ? keys.join(",") : "unbound";
  }

  function extractSymbol(t) {
    const symbols = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "XRPUSDT", "LINKUSDT"];
    const u = t.toUpperCase();
    return symbols.find(s => u.includes(s)) || "unbound";
  }

  function snapshot() {
    const t = pageText();
    const lower = t.toLowerCase();

    const proof =
      lower.includes("proof verified") || lower.includes("proof pass") ? "pass" :
      lower.includes("proof pending") || lower.includes("signature pending") || lower.includes("receipt pending") ? "pending" :
      "unbound";

    const src =
      lower.includes("source-bound") || lower.includes("source bound") ? "source-bound" :
      lower.includes("source-required") || lower.includes("source required") || lower.includes("source-bound required") ? "source-required" :
      "unbound";

    const order =
      lower.includes("orders blocked") || lower.includes("order-blocked") || lower.includes("no app-side execution") ? "orders-blocked" :
      lower.includes("execution authority none") || lower.includes("no execution") ? "no-execution" :
      "unbound";

    const data =
      lower.includes("data hold") || lower.includes("data_hold") || lower.includes("mindata missing") ? "DATA_HOLD" :
      "unbound";

    let reason = "source/proof pending";
    if (/MinData/i.test(t) && /missing|complete/i.test(t)) reason = "MinData/source proof gate";
    else if (/source-bound required|source required/i.test(t)) reason = "source-bound truth required";
    else if (/orders blocked|order-blocked/i.test(t)) reason = "orders blocked";

    return {
      symbol: extractSymbol(t),
      action: "hold",
      reason,
      missing: extractMissingKeys(t),
      proof,
      src,
      order,
      data,
      ts: Date.now()
    };
  }

  function chip(label, value, sev) {
    return `<span class="zel-mcd-v3-chip" data-sev="${sev || "pending"}"><i class="zel-mcd-v3-dot"></i>${label}: ${value}</span>`;
  }

  function renderBody(s) {
    const time = new Date(s.ts).toISOString().slice(11, 19) + "Z";
    return `
      <div class="zel-mcd-v3-head">
        <div>
          <div class="zel-mcd-v3-kicker">ZEL Mission Control Dock</div>
          <div class="zel-mcd-v3-title">${s.symbol} · ${s.action} · ${s.reason}</div>
        </div>
        <div class="zel-mcd-v3-actions">
          <div class="zel-mcd-v3-state">${s.data}</div>
          <button class="zel-mcd-v3-toggle" type="button" data-zmc-toggle="1">${state.collapsed ? "open" : "fold"}</button>
        </div>
      </div>
      <div class="zel-mcd-v3-body">
        <div class="zel-mcd-v3-rail">
          ${chip("truth", s.src, s.src === "source-bound" ? "pass" : "hold")}
          ${chip("decision", s.action, "hold")}
          ${chip("orders", s.order, s.order.includes("blocked") || s.order.includes("no") ? "hold" : "pending")}
          ${chip("proof", s.proof, s.proof === "pass" ? "pass" : "pending")}
          ${chip("missing", s.missing, s.missing === "unbound" ? "pending" : "hold")}
        </div>
        <div class="zel-mcd-v3-strip">
          <div class="zel-mcd-v3-row"><b>Decision</b><span>${s.symbol} | action=${s.action} | ${s.reason}</span></div>
          <div class="zel-mcd-v3-row"><b>Guard</b><span>${s.data} · ${s.src} · ${s.order} · proof=${s.proof}</span></div>
          <div class="zel-mcd-v3-row"><b>Missing</b><span>${s.missing}</span></div>
        </div>
        <div class="zel-mcd-v3-mini">
          <div><label>LIVE</label><strong>read-only / no execution</strong></div>
          <div><label>VIRTUAL</label><strong>route pending</strong></div>
          <div><label>TEAM</label><strong>advisor pending</strong></div>
        </div>
        <div class="zel-mcd-v3-foot"><span>Step2 v3 stable · no relocation</span><code>${time}</code></div>
      </div>`;
  }

  function bindToggle(dock) {
    if (dock.dataset.boundToggle === "1") return;
    dock.dataset.boundToggle = "1";
    dock.addEventListener("click", ev => {
      const btn = ev.target?.closest?.("[data-zmc-toggle]");
      if (!btn) return;
      state.collapsed = !state.collapsed;
      dock.setAttribute("data-collapsed", state.collapsed ? "1" : "0");
      btn.textContent = state.collapsed ? "open" : "fold";
      measureDock();
      expose();
    });
  }

  function update() {
    const dock = ensureDock();
    const s = snapshot();
    state.last = s;
    state.updateCount += 1;

    const collapsedAttr = dock.getAttribute("data-collapsed");
    state.collapsed = collapsedAttr === "1";

    dock.innerHTML = renderBody(s);
    dock.setAttribute("data-version", VERSION);
    dock.setAttribute("data-collapsed", state.collapsed ? "1" : "0");
    dock.dataset.boundToggle = "0";
    bindToggle(dock);

    requestAnimationFrame(measureDock);
    expose();
  }

  function expose() {
    window.__ZEL_MISSION_CONTROL_DOCK_V3__ = {
      version: VERSION,
      inserted: !!document.getElementById(ID),
      stablePortal: true,
      parent: document.getElementById(ID)?.parentElement?.tagName || null,
      collapsed: state.collapsed,
      restoredCount: state.restoredCount,
      updateCount: state.updateCount,
      last: state.last,
      preboot: window.__ZEL_MISSION_CONTROL_DOCK_V3_PREBOOT__ || null,
      ts: Date.now()
    };
  }

  function boot() {
    ensureDock();
    update();

    setInterval(update, 2000);
    setInterval(() => {
      ensureDock();
      expose();
    }, 250);

    try {
      new MutationObserver(() => {
        ensureDock();
      }).observe(document.documentElement, { childList: true, subtree: true });
    } catch (_) {}

    addEventListener("resize", measureDock, { passive: true });
    addEventListener("orientationchange", () => setTimeout(measureDock, 100), { passive: true });
    addEventListener("scroll", () => requestAnimationFrame(measureDock), { passive: true });

    expose();
    console.info("[ZEL]", VERSION, "boot");
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", boot, { once: true });
  } else {
    boot();
  }
})();
