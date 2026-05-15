(() => {
  const VERSION = 'zops_runtime_guard_v1';
  const KEYWORDS = [
    'ledger offline', 'replay offline', 'WEB audit replay', 'audit replay',
    'advisory_only', 'exec:blocked', 'Z-OS Harness Visual Gate',
    'zops_harness_visual_gate', 'zops_ui_residue_cleanup', 'receipt pending',
    'alimi clear', 'lkg ready', 'expand evidence'
  ];
  const SAFE_DATA_ATTR = 'data-zops-runtime-guard';
  let lastStatus = { status: 'booting', hidden: [], failures: [], version: VERSION, ts_ms: Date.now() };

  const isRootOrApp = (el) => {
    const root = document.getElementById('root');
    if (!el || el === document.documentElement || el === document.body) return true;
    if (root && (el === root || root.contains(el))) return true;
    if (el.closest && el.closest('#zops-runtime-guard-root')) return true;
    return false;
  };

  const visibleFixedBottomLeft = (el) => {
    const cs = window.getComputedStyle(el);
    if (!['fixed', 'sticky', 'absolute'].includes(cs.position)) return false;
    const r = el.getBoundingClientRect();
    const vw = window.innerWidth || 0;
    const vh = window.innerHeight || 0;
    if (!r || r.width < 12 || r.height < 8) return false;
    const isBottom = r.bottom > vh - 96 || r.top > vh - 140;
    const isLeft = r.left < Math.min(420, vw * 0.45);
    const isFloating = parseInt(cs.zIndex || '0', 10) > 20 || cs.position === 'fixed';
    return isBottom && isLeft && isFloating;
  };

  const textMatches = (txt) => {
    const t = String(txt || '').slice(0, 1600);
    return KEYWORDS.some(k => t.includes(k));
  };

  const hideResidues = () => {
    const hidden = [];
    const children = Array.from(document.body ? document.body.children : []);
    for (const el of children) {
      if (!(el instanceof HTMLElement)) continue;
      if (isRootOrApp(el)) continue;
      const tag = el.tagName.toLowerCase();
      if (['script','style','link','meta','title'].includes(tag)) continue;
      const txt = el.innerText || el.textContent || '';
      if (visibleFixedBottomLeft(el) && textMatches(txt)) {
        el.classList.add('zops-runtime-hidden-residue');
        el.setAttribute('data-zops-hidden-by', VERSION);
        hidden.push((txt.trim().split(/\s+/).slice(0, 8).join(' ') || tag));
      }
    }
    lastStatus.hidden = hidden.slice(0, 12);
    lastStatus.ts_ms = Date.now();
    return hidden;
  };

  const ensureRoot = () => {
    let root = document.getElementById('zops-runtime-guard-root');
    if (root) return root;
    root = document.createElement('div');
    root.id = 'zops-runtime-guard-root';
    root.setAttribute(SAFE_DATA_ATTR, '1');
    root.innerHTML = `
      <button class="zops-harness-pill" type="button" aria-label="Z-OS harness status">
        <span class="zops-harness-dot"></span><span class="zops-harness-label">HARNESS active</span>
      </button>
      <pre class="zops-harness-panel"></pre>`;
    document.body.appendChild(root);
    root.querySelector('.zops-harness-pill')?.addEventListener('click', () => {
      root.classList.toggle('zops-open');
      renderPanel(root);
    });
    return root;
  };

  const renderPanel = (root) => {
    const panel = root.querySelector('.zops-harness-panel');
    if (!panel) return;
    const payload = {
      version: VERSION,
      status: lastStatus.status || 'active',
      href: location.href,
      viewport: { w: window.innerWidth, h: window.innerHeight, dpr: window.devicePixelRatio || 1 },
      hidden: lastStatus.hidden || [],
      failures: lastStatus.failures || [],
      ts_ms: Date.now(),
      note: 'single guard active; orphan debug residues are hidden outside app root'
    };
    panel.textContent = JSON.stringify(payload, null, 2);
  };

  const pollHarness = async () => {
    try {
      const res = await fetch('/api/harness/visual/status', { headers: { accept: 'application/json' }, cache: 'no-store' });
      const ct = res.headers.get('content-type') || '';
      if (!res.ok || !ct.includes('json')) throw new Error(`bad_status=${res.status} ct=${ct}`);
      const data = await res.json();
      lastStatus = { ...lastStatus, ...data, status: data.status || 'pass' };
    } catch (e) {
      lastStatus.status = 'local_guard_active';
      lastStatus.failures = [String(e && e.message ? e.message : e).slice(0, 160)];
    }
    const root = ensureRoot();
    root.querySelector('.zops-harness-label').textContent = lastStatus.status === 'pass' ? 'HARNESS active' : 'HARNESS local';
    if (root.classList.contains('zops-open')) renderPanel(root);
  };

  const tick = () => { try { hideResidues(); ensureRoot(); } catch (_) {} };

  const boot = () => {
    ensureRoot();
    tick();
    pollHarness();
    window.addEventListener('hashchange', () => setTimeout(tick, 80), { passive: true });
    window.addEventListener('resize', () => setTimeout(tick, 120), { passive: true });
    const mo = new MutationObserver(() => tick());
    mo.observe(document.body, { childList: true, subtree: false });
    setInterval(tick, 1200);
    setInterval(pollHarness, 15000);
  };

  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', boot, { once: true });
  else boot();
})();
