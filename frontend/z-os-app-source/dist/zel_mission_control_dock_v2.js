(() => {
  "use strict";

  const VERSION = "ZEL_MISSION_CONTROL_DOCK_V2_INSTANT";
  const DOCK_ID = "zel-mission-control-dock-v2";
  const OLD_ID = "zel-mission-control-dock-v1";
  const MARKERS = [
    "ADVISOR MICRO STRIP",
    "EVIDENCE SUMMARY",
    "Decision proof snapshot",
    "Advanced ZEL stack"
  ];

  const state = {
    inserted: false,
    relocated: false,
    target: null,
    marker: null,
    last: null
  };

  function textOf(el) {
    return String(el?.textContent || "").replace(/\s+/g, " ").trim();
  }

  function norm(s) {
    return String(s || "").replace(/\s+/g, " ").trim();
  }

  function all(sel, root = document) {
    return Array.from(root.querySelectorAll(sel));
  }

  function rectOk(el) {
    try {
      const r = el.getBoundingClientRect();
      return r.width > 180 && r.height > 35;
    } catch (_) {
      return false;
    }
  }

  function forbidden(el) {
    if (!el) return true;
    if (el.id === DOCK_ID || el.id === OLD_ID) return true;
    if (el.closest?.("#" + DOCK_ID) || el.closest?.("#" + OLD_ID)) return true;
    if (el.closest?.(".zel-v7-book,.zel-v6-book,.zel-v5-book,.zel-v4-book,.zel-v3-book,.zel-v2-book,.zel-v1-book")) return true;
    const t = textOf(el).toUpperCase();
    if (t.includes("BTCUSDT") && t.includes("ETHUSDT") && t.includes("SOLUSDT") && t.includes("XRPUSDT")) return true;
    return false;
  }

  function scoreMarker(el, marker) {
    const t = textOf(el);
    if (!t.includes(marker)) return -999;
    if (forbidden(el)) return -999;
    if (!rectOk(el)) return -999;

    const r = el.getBoundingClientRect();
    let s = 0;

    if (r.top > 150) s += 8;
    if (r.width < Math.min(innerWidth * .75, 820)) s += 5;
    if (t.length < 900) s += 10;
    if (marker === "ADVISOR MICRO STRIP") s += 15;
    if (marker === "EVIDENCE SUMMARY") s += 13;
    if (marker === "Decision proof snapshot") s += 8;
    if (marker === "Advanced ZEL stack") s += 6;
    if (r.height < 260) s += 10;
    if (r.height > 520) s -= 30;
    if (t.includes("Dash Trade Log Settings Bots")) s -= 35;

    return s;
  }

  function findInsertionTarget() {
    const candidates = [];
    const nodes = all("section,article,div,main,li");

    for (const marker of MARKERS) {
      for (const el of nodes) {
        const s = scoreMarker(el, marker);
        if (s > -100) candidates.push({ el, marker, score: s });
      }
    }

    candidates.sort((a, b) => b.score - a.score);
    const best = candidates[0];
    if (!best) return null;

    return { el: best.el, marker: best.marker, mode: "before" };
  }

  function extractMissingKeys() {
    const t = textOf(document.body);
    const m = t.match(/missing:?\s*([a-zA-Z0-9_,%\-\s]+?)(?:DATA_HOLD|no execution|Advisor|Evidence|Decision|Dash|Trade|Log|Settings|Bots|$)/i);
    if (m && m[1]) {
      return norm(m[1]).replace(/\s+/g, "").slice(0, 120);
    }

    const keys = [];
    for (const k of ["price", "pos_pct", "lev", "entry_ts", "liq_buffer_pct", "funding_8h_pct", "DD_day_pct", "DD_total_pct"]) {
      const re = new RegExp(k.replace(/[.*+?^${}()|[\]\\]/g, "\\$&") + "\\s*=\\s*unbound", "i");
      if (re.test(t)) keys.push(k);
    }
    return keys.length ? keys.join(",") : "unbound";
  }

  function extractSymbol() {
    const symbols = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "XRPUSDT", "LINKUSDT"];
    const t = textOf(document.body).toUpperCase();
    return symbols.find(s => t.includes(s)) || "unbound";
  }

  function proofState() {
    const t = textOf(document.body).toLowerCase();
    if (t.includes("proof pending") || t.includes("signature pending") || t.includes("receipt pending")) return "pending";
    if (t.includes("proof verified") || t.includes("proof pass")) return "pass";
    return "unbound";
  }

  function sourceState() {
    const t = textOf(document.body).toLowerCase();
    if (t.includes("source-bound") || t.includes("source bound")) return "source-bound";
    if (t.includes("source-required") || t.includes("source required") || t.includes("source-bound required")) return "source-required";
    return "unbound";
  }

  function orderState() {
    const t = textOf(document.body).toLowerCase();
    if (t.includes("orders blocked") || t.includes("order-blocked") || t.includes("no app-side execution")) return "orders-blocked";
    if (t.includes("execution authority none") || t.includes("no execution")) return "no-execution";
    return "unbound";
  }

  function dataHoldState() {
    const t = textOf(document.body).toLowerCase();
    if (t.includes("data hold") || t.includes("data_hold") || t.includes("mindata missing")) return "DATA_HOLD";
    return "unbound";
  }

  function currentAction() {
    const t = textOf(document.body).toLowerCase();
    if (t.includes("action hold") || t.includes("current_action hold") || t.includes("no app-side execution")) return "hold";
    return "hold";
  }

  function decisionReason() {
    const t = textOf(document.body);
    if (/MinData/i.test(t) && /missing|complete/i.test(t)) return "MinData/source proof gate";
    if (/source-bound required|source required/i.test(t)) return "source-bound truth required";
    if (/orders blocked|order-blocked/i.test(t)) return "orders blocked";
    return "source/proof pending";
  }

  function snapshot() {
    const symbol = extractSymbol();
    const missing = extractMissingKeys();
    const proof = proofState();
    const src = sourceState();
    const order = orderState();
    const data = dataHoldState();
    const action = currentAction();
    const reason = decisionReason();

    return {
      symbol, action, reason, missing, proof, src, order, data,
      ts: Date.now()
    };
  }

  function chip(label, value, sev) {
    return `<span class="zel-mcd-chip" data-sev="${sev || "pending"}"><i class="zel-mcd-dot"></i>${label}: ${value}</span>`;
  }

  function html(s, phase) {
    return `<section id="${DOCK_ID}" class="zel-mcd-v2" data-step="2" data-version="${VERSION}" data-phase="${phase || "inline"}">
      <div class="zel-mcd-head">
        <div>
          <div class="zel-mcd-kicker">ZEL Mission Control Dock</div>
          <div class="zel-mcd-title">${s.symbol} · ${s.action} · ${s.reason}</div>
        </div>
        <div class="zel-mcd-state">${s.data}</div>
      </div>

      <div class="zel-mcd-rail">
        ${chip("truth", s.src, s.src === "source-bound" ? "pass" : "hold")}
        ${chip("decision", s.action, "hold")}
        ${chip("orders", s.order, s.order.includes("blocked") || s.order.includes("no") ? "hold" : "pending")}
        ${chip("proof", s.proof, s.proof === "pass" ? "pass" : "pending")}
        ${chip("missing", s.missing, s.missing === "unbound" ? "pending" : "hold")}
      </div>

      <div class="zel-mcd-strip">
        <div class="zel-mcd-row">
          <b>Decision</b>
          <span>${s.symbol} | action=${s.action} | ${s.reason}</span>
        </div>
        <div class="zel-mcd-row">
          <b>Guard</b>
          <span>${s.data} · ${s.src} · ${s.order} · proof=${s.proof}</span>
        </div>
        <div class="zel-mcd-row">
          <b>Missing</b>
          <span>${s.missing}</span>
        </div>
      </div>

      <div class="zel-mcd-mini">
        <div><label>LIVE</label><strong>read-only / no execution</strong></div>
        <div><label>VIRTUAL</label><strong>route pending</strong></div>
        <div><label>TEAM</label><strong>advisor pending</strong></div>
      </div>

      <div class="zel-mcd-foot">
        <span>Step2 v2 instant · ${phase === "instant" ? "waiting inline target" : "inline"}</span>
        <code>${new Date(s.ts).toISOString().slice(11, 19)}Z</code>
      </div>
    </section>`;
  }

  function ensureDock() {
    let old = document.getElementById(OLD_ID);
    if (old) old.remove();

    let dock = document.getElementById(DOCK_ID);
    if (!dock) {
      const tmp = document.createElement("div");
      tmp.innerHTML = html(snapshot(), "instant").trim();
      dock = tmp.firstElementChild;
      document.body.appendChild(dock);
      state.inserted = true;
    }
    return dock;
  }

  function relocateInline() {
    const dock = ensureDock();
    const target = findInsertionTarget();
    if (!target) {
      state.relocated = false;
      expose();
      return false;
    }

    if (dock.nextElementSibling !== target.el) {
      target.el.insertAdjacentElement("beforebegin", dock);
    }

    dock.setAttribute("data-phase", "inline");
    state.inserted = true;
    state.relocated = true;
    state.target = {
      tag: target.el.tagName,
      id: target.el.id || "",
      cls: String(target.el.className || "").slice(0, 140),
      text: textOf(target.el).slice(0, 120)
    };
    state.marker = target.marker;
    expose();
    return true;
  }

  function update() {
    const dock = ensureDock();
    const phase = dock.getAttribute("data-phase") || "instant";
    const s = snapshot();
    state.last = s;

    const tmp = document.createElement("div");
    tmp.innerHTML = html(s, phase).trim();
    const fresh = tmp.firstElementChild;
    dock.replaceWith(fresh);

    relocateInline();
    expose();
    return true;
  }

  function expose() {
    window.__ZEL_MISSION_CONTROL_DOCK_V2__ = {
      version: VERSION,
      inserted: !!document.getElementById(DOCK_ID),
      relocated: state.relocated,
      target: state.target,
      marker: state.marker,
      last: state.last,
      preboot: window.__ZEL_MISSION_CONTROL_DOCK_V2_PREBOOT__ || null,
      ts: Date.now()
    };
  }

  function boot() {
    ensureDock();
    let n = 0;
    const fast = setInterval(() => {
      update();
      if (state.relocated || ++n > 80) clearInterval(fast);
    }, 100);

    setInterval(update, 2000);
    expose();
    console.info("[ZEL]", VERSION, "boot");
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", boot, { once: true });
  } else {
    boot();
  }
})();
