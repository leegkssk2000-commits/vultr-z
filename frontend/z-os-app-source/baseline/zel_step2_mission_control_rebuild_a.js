(() => {
  "use strict";

  const VERSION = "ZEL_STEP2_MISSION_CONTROL_REBUILD_A";
  const ID = "zel-step2-mission-control-rebuild-a";
  const OLD_IDS = [
    "zel-mission-control-dock-v1",
    "zel-mission-control-dock-v2",
    "zel-mission-control-dock-v3"
  ];

  const state = {
    initialized: false,
    collapsed: false,
    restoredCount: 0,
    updateCount: 0,
    mutationTick: 0,
    last: null,
    lastHeight: 0
  };

  function norm(s) {
    return String(s || "").replace(/\s+/g, " ").trim();
  }

  function removeOld() {
    OLD_IDS.forEach(id => {
      document.querySelectorAll("#" + id).forEach(el => el.remove());
    });
  }

  function readPageText() {
    let body = document.body;
    if (!body) return "";
    let t = norm(body.textContent || "");
    const self = document.getElementById(ID);
    if (self) t = norm(t.replace(norm(self.textContent || ""), " "));
    OLD_IDS.forEach(id => {
      const el = document.getElementById(id);
      if (el) t = norm(t.replace(norm(el.textContent || ""), " "));
    });
    return t;
  }

  function shellElement() {
    const tmp = document.createElement("div");
    tmp.innerHTML = `
      <section id="${ID}" data-version="${VERSION}" data-collapsed="0" data-owner="body-portal">
        <div class="z2-shell">
          <div class="z2-head">
            <div><div class="z2-kicker">ZEL Mission Control Dock</div><div class="z2-title" data-z2-title>boot · source/proof pending</div></div>
            <div class="z2-actions"><div class="z2-state" data-z2-state>BOOT</div><button class="z2-btn" type="button" data-z2-toggle>fold</button></div>
          </div>
          <div class="z2-body">
            <div class="z2-rail">
              <span class="z2-chip" data-sev="pending" data-z2-chip="truth"><i class="z2-dot"></i><span>truth: loading</span></span>
              <span class="z2-chip" data-sev="hold" data-z2-chip="decision"><i class="z2-dot"></i><span>decision: hold</span></span>
              <span class="z2-chip" data-sev="pending" data-z2-chip="proof"><i class="z2-dot"></i><span>proof: pending</span></span>
            </div>
            <div class="z2-grid">
              <div class="z2-row"><b>Decision</b><span data-z2-decision>initializing · no execution</span></div>
              <div class="z2-row"><b>Guard</b><span data-z2-guard>stable body portal · no app relocation</span></div>
              <div class="z2-row"><b>Missing</b><span data-z2-missing>unbound</span></div>
            </div>
            <div class="z2-mini">
              <div><label>LIVE</label><strong data-z2-live>read-only / no execution</strong></div>
              <div><label>VIRTUAL</label><strong data-z2-virtual>route pending</strong></div>
              <div><label>TEAM</label><strong data-z2-team>advisor pending</strong></div>
            </div>
            <div class="z2-foot"><span data-z2-foot>Step2 rebuild A · stable</span><code data-z2-time>BOOT</code></div>
          </div>
        </div>
      </section>`;
    return tmp.firstElementChild;
  }

  function ensureSingleDock() {
    removeOld();

    let docks = Array.from(document.querySelectorAll("#" + ID));
    if (docks.length > 1) {
      docks.slice(1).forEach(el => el.remove());
      docks = docks.slice(0, 1);
    }

    let dock = docks[0];
    if (!dock) {
      dock = shellElement();
      document.body.appendChild(dock);
      state.restoredCount += 1;
    } else if (dock.parentElement !== document.body) {
      document.body.appendChild(dock);
      state.restoredCount += 1;
    }

    dock.dataset.version = VERSION;
    dock.dataset.owner = "body-portal";
    if (!dock.hasAttribute("data-collapsed")) dock.dataset.collapsed = "0";

    bindOnce(dock);
    measure();
    return dock;
  }

  function setText(root, sel, val) {
    const el = root.querySelector(sel);
    if (el && el.textContent !== String(val)) el.textContent = String(val);
  }

  function setChip(root, key, label, value, sev) {
    const el = root.querySelector(`[data-z2-chip="${key}"]`);
    if (!el) return;
    el.dataset.sev = sev || "pending";
    const span = el.querySelector("span");
    const txt = `${label}: ${value}`;
    if (span && span.textContent !== txt) span.textContent = txt;
  }

  function extractMissing(t) {
    const m = t.match(/missing:?\s*([a-zA-Z0-9_,%\-\s]+?)(?:DATA_HOLD|no execution|Advisor|Evidence|Decision|Dash|Trade|Log|Settings|Bots|$)/i);
    if (m && m[1]) return norm(m[1]).replace(/\s+/g, "").slice(0, 120);

    const keys = [];
    ["price","pos_pct","lev","entry_ts","liq_buffer_pct","funding_8h_pct","DD_day_pct","DD_total_pct"].forEach(k => {
      const re = new RegExp(k.replace(/[.*+?^${}()|[\]\\]/g, "\\$&") + "\\s*=\\s*unbound", "i");
      if (re.test(t)) keys.push(k);
    });
    return keys.length ? keys.join(",") : "unbound";
  }

  function extractSymbol(t) {
    const u = t.toUpperCase();
    return ["BTCUSDT","ETHUSDT","SOLUSDT","XRPUSDT","LINKUSDT"].find(s => u.includes(s)) || "unbound";
  }

  function snapshot() {
    const t = readPageText();
    const l = t.toLowerCase();

    const src =
      l.includes("source-bound") || l.includes("source bound") ? "source-bound" :
      l.includes("source-required") || l.includes("source required") || l.includes("source-bound required") ? "source-required" :
      "unbound";

    const proof =
      l.includes("proof verified") || l.includes("proof pass") ? "pass" :
      l.includes("proof pending") || l.includes("signature pending") || l.includes("receipt pending") ? "pending" :
      "unbound";

    const order =
      l.includes("orders blocked") || l.includes("order-blocked") || l.includes("no app-side execution") ? "orders-blocked" :
      l.includes("execution authority none") || l.includes("no execution") ? "no-execution" :
      "unbound";

    const data =
      l.includes("data hold") || l.includes("data_hold") || l.includes("mindata missing") ? "DATA_HOLD" :
      "unbound";

    let reason = "source/proof pending";
    if (/MinData/i.test(t) && /missing|complete/i.test(t)) reason = "MinData/source proof gate";
    else if (/source-bound required|source required/i.test(t)) reason = "source-bound truth required";
    else if (/orders blocked|order-blocked/i.test(t)) reason = "orders blocked";

    return {
      symbol: extractSymbol(t),
      action: "hold",
      reason,
      missing: extractMissing(t),
      src,
      proof,
      order,
      data,
      ts: Date.now()
    };
  }

  function render() {
    const dock = ensureSingleDock();
    const s = snapshot();
    state.last = s;
    state.updateCount += 1;

    setText(dock, "[data-z2-title]", `${s.symbol} · ${s.action} · ${s.reason}`);
    setText(dock, "[data-z2-state]", s.data);
    setChip(dock, "truth", "truth", s.src, s.src === "source-bound" ? "pass" : "hold");
    setChip(dock, "decision", "decision", s.action, "hold");
    setChip(dock, "proof", "proof", s.proof, s.proof === "pass" ? "pass" : "pending");

    setText(dock, "[data-z2-decision]", `${s.symbol} | action=${s.action} | ${s.reason}`);
    setText(dock, "[data-z2-guard]", `${s.data} · ${s.src} · ${s.order} · proof=${s.proof}`);
    setText(dock, "[data-z2-missing]", s.missing);
    setText(dock, "[data-z2-live]", "read-only / no execution");
    setText(dock, "[data-z2-virtual]", "route pending");
    setText(dock, "[data-z2-team]", "advisor pending");
    setText(dock, "[data-z2-time]", new Date(s.ts).toISOString().slice(11, 19) + "Z");
    setText(dock, "[data-z2-foot]", "Step2 rebuild A · stable body portal");

    measure();
    expose();
  }

  function bindOnce(dock) {
    if (dock.dataset.bound === "1") return;
    dock.dataset.bound = "1";
    dock.addEventListener("click", ev => {
      const btn = ev.target && ev.target.closest && ev.target.closest("[data-z2-toggle]");
      if (!btn) return;
      const collapsed = dock.dataset.collapsed === "1";
      dock.dataset.collapsed = collapsed ? "0" : "1";
      btn.textContent = collapsed ? "fold" : "open";
      state.collapsed = !collapsed;
      measure();
      expose();
    }, { passive: true });
  }

  function measure() {
    try {
      const dock = document.getElementById(ID);
      const h = dock ? Math.ceil(dock.getBoundingClientRect().height || 0) : 0;
      state.lastHeight = h;
      document.documentElement.style.setProperty("--zel-step2-dock-h", h + "px");
      document.body.classList.add("zel-step2-dock-pad");
    } catch (_) {}
  }

  function expose() {
    const dock = document.getElementById(ID);
    window.__ZEL_STEP2_MISSION_CONTROL_REBUILD_A__ = {
      version: VERSION,
      inserted: !!dock,
      parent: dock && dock.parentElement ? dock.parentElement.tagName : null,
      stableBodyPortal: !!dock && dock.parentElement === document.body,
      collapsed: dock ? dock.dataset.collapsed === "1" : false,
      restoredCount: state.restoredCount,
      updateCount: state.updateCount,
      mutationTick: state.mutationTick,
      height: state.lastHeight,
      last: state.last,
      ts: Date.now()
    };
  }

  function boot() {
    ensureSingleDock();
    render();

    setInterval(render, 2000);
    setInterval(() => {
      ensureSingleDock();
      measure();
      expose();
    }, 250);

    try {
      new MutationObserver(() => {
        state.mutationTick += 1;
        ensureSingleDock();
      }).observe(document.documentElement, { childList: true, subtree: true });
    } catch (_) {}

    addEventListener("resize", measure, { passive: true });
    addEventListener("orientationchange", () => setTimeout(measure, 120), { passive: true });
    addEventListener("scroll", () => requestAnimationFrame(measure), { passive: true });

    expose();
    console.info("[ZEL]", VERSION, "boot");
  }

  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", boot, { once: true });
  else boot();
})();
