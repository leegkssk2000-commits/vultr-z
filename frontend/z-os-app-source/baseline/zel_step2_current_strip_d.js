(() => {
  "use strict";

  const VERSION = "ZEL_STEP2_CURRENT_STRIP_D_INLINE";
  const STRIP_CLASS = "zel-current-strip-d";
  const SYMBOLS = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "XRPUSDT", "LINKUSDT"];
  const OLD_IDS = [
    "zel-mission-control-dock-v1",
    "zel-mission-control-dock-v2",
    "zel-mission-control-dock-v3",
    "zel-step2-mission-control-rebuild-a",
    "zel-step2-mission-rail-b",
    "zel-step2-mission-rail-c"
  ];

  const state = {
    updateCount: 0,
    stripCount: 0,
    candidateCount: 0,
    last: null,
    ts: Date.now()
  };

  const compact = value => String(value || "").toUpperCase().replace(/\s+/g, "");
  const norm = value => String(value || "").replace(/\s+/g, " ").trim();

  function killOldFloating() {
    OLD_IDS.forEach(id => {
      document.querySelectorAll("#" + id).forEach(el => el.remove());
    });
    document.querySelectorAll(".zel-step2-mission-rail-b,.zel-step2-mission-rail-c,[class*='zel-step2-mission-rail'],[id^='zel-step2-mission-rail'],[id^='zel-mission-control-dock'],[id*='mission-control-rebuild']").forEach(el => el.remove());
    if (document.body) {
      document.body.classList.remove("zel-step2-dock-pad");
      document.body.classList.remove("zel-mission-rail-pad");
    }
    if (document.documentElement) {
      document.documentElement.style.removeProperty("--zel-step2-dock-h");
      document.documentElement.style.removeProperty("--zel-step2-rail-h");
    }
  }

  function pageText() {
    const body = document.body;
    if (!body) return "";
    let text = norm(body.textContent || "");
    document.querySelectorAll("." + STRIP_CLASS).forEach(strip => {
      text = norm(text.replace(norm(strip.textContent || ""), " "));
    });
    return text;
  }

  function snapshot() {
    const text = pageText();
    const lower = text.toLowerCase();

    const src =
      lower.includes("source-bound") || lower.includes("source bound") ? "source-bound" :
      lower.includes("source-required") || lower.includes("source required") || lower.includes("source-bound required") ? "source-required" :
      "unbound";

    const proof =
      lower.includes("proof verified") || lower.includes("proof pass") ? "pass" :
      lower.includes("proof pending") || lower.includes("signature pending") || lower.includes("receipt pending") ? "pending" :
      "unbound";

    const order =
      lower.includes("orders blocked") || lower.includes("order-blocked") || lower.includes("no app-side execution") ? "orders-blocked" :
      lower.includes("execution authority none") || lower.includes("no execution") ? "no-execution" :
      "unbound";

    const data =
      lower.includes("data hold") || lower.includes("data_hold") || lower.includes("mindata missing") ? "DATA_HOLD" :
      "unbound";

    let reason = "source/proof pending";
    if (/MinData/i.test(text) && /missing|complete/i.test(text)) reason = "MinData/source proof gate";
    else if (/source-bound required|source required/i.test(text)) reason = "source-bound truth required";
    else if (/orders blocked|order-blocked/i.test(text)) reason = "orders blocked";

    let missing = "unbound";
    const m = text.match(/missing:?\s*([a-zA-Z0-9_,%\-\s]+?)(?:DATA_HOLD|no execution|Advisor|Evidence|Decision|Dash|Trade|Log|Settings|Bots|$)/i);
    if (m && m[1]) {
      missing = norm(m[1]).replace(/\s+/g, "").slice(0, 100);
    } else {
      const keys = [];
      ["price","pos_pct","lev","entry_ts","liq_buffer_pct","funding_8h_pct","DD_day_pct","DD_total_pct"].forEach(k => {
        const re = new RegExp(k.replace(/[.*+?^${}()|[\]\\]/g, "\\$&") + "\\s*=\\s*unbound", "i");
        if (re.test(text)) keys.push(k);
      });
      if (keys.length) missing = keys.join(",");
    }

    return { src, proof, order, data, reason, missing, action: "hold", ts: Date.now() };
  }

  function isOldOrStrip(el) {
    if (!el || el.nodeType !== 1) return true;
    if (el.classList && el.classList.contains(STRIP_CLASS)) return true;
    if (el.closest && el.closest("." + STRIP_CLASS)) return true;
    if (OLD_IDS.some(id => el.id === id || (el.closest && el.closest("#" + id)))) return true;
    return false;
  }

  function isCardCandidate(el, symbol) {
    if (isOldOrStrip(el)) return false;
    const raw = el.textContent || "";
    if (!raw || raw.length > 5000) return false;

    const c = compact(raw);
    if (!c.includes(symbol)) return false;
    if (!c.includes("BINANCE:")) return false;
    if (!c.includes("LIVE") || !c.includes("VIRTUAL")) return false;

    const rect = el.getBoundingClientRect();
    if (!rect || rect.width < 130 || rect.height < 120) return false;
    if (rect.width > Math.min(window.innerWidth * 0.92, 820)) return false;
    if (rect.height > Math.max(window.innerHeight * 1.6, 980)) return false;

    return true;
  }

  function sameOrContained(a, b) {
    return a === b || a.contains(b) || b.contains(a);
  }

  function findCards() {
    const all = Array.from(document.body ? document.body.querySelectorAll("section,article,div,li") : []);
    const candidates = [];

    for (const symbol of SYMBOLS) {
      for (const el of all) {
        if (!isCardCandidate(el, symbol)) continue;
        const rect = el.getBoundingClientRect();
        const area = rect.width * rect.height;
        const stripCount = el.querySelectorAll("." + STRIP_CLASS).length;
        candidates.push({ el, symbol, area, width: rect.width, height: rect.height, stripCount });
      }
    }

    candidates.sort((a, b) => {
      if (a.symbol !== b.symbol) return a.symbol.localeCompare(b.symbol);
      return a.area - b.area;
    });

    const kept = [];
    for (const cand of candidates) {
      if (kept.some(k => k.symbol === cand.symbol && sameOrContained(k.el, cand.el))) continue;
      if (kept.some(k => k.el === cand.el)) continue;
      kept.push(cand);
    }

    state.candidateCount = candidates.length;
    return kept.slice(0, 10);
  }

  function makeNode(tag, className, text) {
    const el = document.createElement(tag);
    if (className) el.className = className;
    if (text !== undefined) el.textContent = text;
    return el;
  }

  function createStrip(symbol) {
    const root = makeNode("div", STRIP_CLASS);
    root.dataset.symbol = symbol;
    root.dataset.open = "0";
    root.dataset.version = VERSION;

    const head = makeNode("div", "zel-current-strip-d-head");

    const titleBox = makeNode("div");
    const kicker = makeNode("span", "zel-current-strip-d-k", "ZEL Current");
    const title = makeNode("span", "zel-current-strip-d-title", symbol + " · hold · source/proof pending");
    title.dataset.zelRole = "title";
    titleBox.appendChild(kicker);
    titleBox.appendChild(title);

    const pill = makeNode("span", "zel-current-strip-d-pill", "DATA_HOLD");
    pill.dataset.zelRole = "state";

    const btn = makeNode("button", "zel-current-strip-d-btn", "open");
    btn.type = "button";
    btn.dataset.zelRole = "toggle";

    head.appendChild(titleBox);
    head.appendChild(pill);
    head.appendChild(btn);

    const detail = makeNode("div", "zel-current-strip-d-detail");

    const chips = makeNode("div", "zel-current-strip-d-chips");
    ["truth", "proof", "live", "virtual"].forEach(key => {
      const chip = makeNode("span", "zel-current-strip-d-chip", key + ": pending");
      chip.dataset.zelChip = key;
      chip.dataset.sev = "pending";
      chips.appendChild(chip);
    });

    const rows = [
      ["decision", "Decision", "hold"],
      ["guard", "Guard", "source/proof pending"],
      ["missing", "Missing", "unbound"],
      ["team", "Team", "advisor pending"]
    ];

    detail.appendChild(chips);

    for (const [key, label, value] of rows) {
      const row = makeNode("div", "zel-current-strip-d-row");
      const b = makeNode("b", "", label);
      const span = makeNode("span", "", value);
      span.dataset.zelRole = key;
      row.appendChild(b);
      row.appendChild(span);
      detail.appendChild(row);
    }

    root.appendChild(head);
    root.appendChild(detail);

    btn.addEventListener("click", ev => {
      ev.preventDefault();
      ev.stopPropagation();
      const open = root.dataset.open === "1";
      root.dataset.open = open ? "0" : "1";
      btn.textContent = open ? "open" : "close";
    });

    return root;
  }

  function laneState(cardText, lane) {
    const re = new RegExp(lane + "\\s+([a-zA-Z0-9._:+/%-]+)", "i");
    const m = norm(cardText).match(re);
    return m && m[1] ? m[1].slice(0, 24) : "flat";
  }

  function setText(root, selector, value) {
    const el = root.querySelector(selector);
    if (el && el.textContent !== String(value)) el.textContent = String(value);
  }

  function setChip(root, key, text, sev) {
    const chip = root.querySelector('[data-zel-chip="' + key + '"]');
    if (!chip) return;
    chip.dataset.sev = sev || "pending";
    if (chip.textContent !== text) chip.textContent = text;
  }

  function ensureStrip(card, symbol) {
    let strip = Array.from(card.children).find(el => el.classList && el.classList.contains(STRIP_CLASS));
    if (!strip) {
      strip = createStrip(symbol);
      card.appendChild(strip);
    }
    strip.dataset.symbol = symbol;
    return strip;
  }

  function updateStrip(strip, card, symbol, snap) {
    const cardText = card.textContent || "";
    const live = laneState(cardText, "LIVE");
    const virtual = laneState(cardText, "VIRTUAL");
    const title = `${symbol} · ${snap.action} · ${snap.reason}`;

    setText(strip, '[data-zel-role="title"]', title);
    setText(strip, '[data-zel-role="state"]', snap.data);
    setText(strip, '[data-zel-role="decision"]', `${symbol} | action=${snap.action} | ${snap.reason}`);
    setText(strip, '[data-zel-role="guard"]', `${snap.data} · ${snap.src} · ${snap.order} · proof=${snap.proof}`);
    setText(strip, '[data-zel-role="missing"]', snap.missing);
    setText(strip, '[data-zel-role="team"]', "advisor pending · no execution");

    setChip(strip, "truth", "truth: " + snap.src, snap.src === "source-bound" ? "pass" : "hold");
    setChip(strip, "proof", "proof: " + snap.proof, snap.proof === "pass" ? "pass" : "pending");
    setChip(strip, "live", "live: " + live, live === "flat" ? "pending" : "pass");
    setChip(strip, "virtual", "virtual: " + virtual, virtual === "flat" ? "pending" : "pass");
  }

  function cleanupOrphans(validCards) {
    const valid = new Set(validCards.map(c => c.el));
    document.querySelectorAll("." + STRIP_CLASS).forEach(strip => {
      const parent = strip.parentElement;
      if (!parent || !valid.has(parent)) strip.remove();
    });
  }

  function update() {
    killOldFloating();

    const snap = snapshot();
    const cards = findCards();

    cleanupOrphans(cards);

    for (const card of cards) {
      const strip = ensureStrip(card.el, card.symbol);
      updateStrip(strip, card.el, card.symbol, snap);
    }

    state.updateCount += 1;
    state.stripCount = document.querySelectorAll("." + STRIP_CLASS).length;
    state.last = {
      cards: cards.map(c => ({
        symbol: c.symbol,
        width: Math.round(c.width),
        height: Math.round(c.height)
      })),
      snapshot: snap
    };
    expose();
  }

  function expose() {
    window.__ZEL_STEP2_CURRENT_STRIP_D__ = {
      version: VERSION,
      inserted: document.querySelectorAll("." + STRIP_CLASS).length > 0,
      inlineOnly: true,
      fixed: false,
      stripCount: state.stripCount,
      candidateCount: state.candidateCount,
      updateCount: state.updateCount,
      last: state.last,
      preboot: window.__ZEL_STEP2_CURRENT_STRIP_D_PREBOOT__ || null,
      ts: Date.now()
    };
  }

  function boot() {
    update();
    setInterval(update, 1800);

    try {
      new MutationObserver(() => {
        window.clearTimeout(boot._t);
        boot._t = window.setTimeout(update, 120);
      }).observe(document.body, { childList: true, subtree: true });
    } catch (_) {}

    window.addEventListener("resize", () => window.setTimeout(update, 100), { passive: true });
    expose();
    console.info("[ZEL]", VERSION, "boot");
  }

  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", boot, { once: true });
  else boot();
})();
