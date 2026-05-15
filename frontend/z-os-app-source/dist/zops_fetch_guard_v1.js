(function zopsFetchGuardV1(){
  if (window.__ZOPS_FETCH_GUARD_V1__ && window.__ZOPS_FETCH_GUARD_V1__.installed) return;
  const nativeFetch = window.fetch ? window.fetch.bind(window) : null;
  if (!nativeFetch) return;

  const VERSION = 'zops_fetch_guard_v1';
  const inflight = new Map();
  const cache = new Map();
  const stats = {
    version: VERSION,
    installed: true,
    mode: 'safe_get_dedupe_and_short_ttl_cache',
    advisory_only: true,
    order_mutation: 'blocked_by_contract_no_post_intercept',
    started_at: Date.now(),
    calls: 0,
    deduped: 0,
    cache_hits: 0,
    bypassed: 0,
    errors: 0,
    last_url: null,
    ttl_ms: 850,
    max_cache_entries: 48,
    guarded_paths: [
      '/api/gate/', '/api/order-gate/', '/api/replay/', '/api/ledger/',
      '/api/promotion/', '/api/harness/', '/api/chaos/', '/api/alimi/', '/api/observability/'
    ]
  };

  function now(){ return Date.now(); }
  function toUrl(input){
    try {
      if (typeof input === 'string') return new URL(input, window.location.origin);
      if (input && input.url) return new URL(input.url, window.location.origin);
    } catch(_e) {}
    return null;
  }
  function methodOf(input, init){
    return String((init && init.method) || (input && input.method) || 'GET').toUpperCase();
  }
  function isGuarded(url){
    if (!url) return false;
    const path = url.pathname || '';
    if (!stats.guarded_paths.some(p => path.indexOf(p) === 0)) return false;
    return /\/(health|status|sample|visual\/status|proof|timeline|report)$/.test(path) || path.indexOf('/api/observability/') === 0;
  }
  function canCache(input, init, url){
    if (methodOf(input, init) !== 'GET') return false;
    if (!isGuarded(url)) return false;
    if (init && (init.body || init.signal)) return false;
    return true;
  }
  function keyOf(input, init, url){
    return methodOf(input, init) + ' ' + url.origin + url.pathname + url.search;
  }
  function prune(){
    const t = now();
    for (const [k, v] of cache) {
      if (!v || (t - v.ts) > stats.ttl_ms * 4) cache.delete(k);
    }
    while (cache.size > stats.max_cache_entries) {
      const first = cache.keys().next().value;
      if (first === undefined) break;
      cache.delete(first);
    }
  }
  async function cloneFromCached(entry){
    return new Response(entry.body, {
      status: entry.status,
      statusText: entry.statusText,
      headers: entry.headers
    });
  }

  window.fetch = function guardedFetch(input, init){
    const url = toUrl(input);
    const method = methodOf(input, init);
    stats.calls += 1;
    stats.last_url = url ? (url.pathname + url.search) : null;

    if (!url || method !== 'GET' || !canCache(input, init, url)) {
      stats.bypassed += 1;
      return nativeFetch(input, init);
    }

    const key = keyOf(input, init, url);
    const hit = cache.get(key);
    const t = now();
    if (hit && (t - hit.ts) <= stats.ttl_ms) {
      stats.cache_hits += 1;
      return Promise.resolve(cloneFromCached(hit));
    }
    if (inflight.has(key)) {
      stats.deduped += 1;
      return inflight.get(key).then(r => r.clone());
    }

    const p = nativeFetch(input, init).then(async (res) => {
      if (res && res.ok) {
        try {
          const copy = res.clone();
          const body = await copy.arrayBuffer();
          cache.set(key, {
            ts: now(),
            status: res.status,
            statusText: res.statusText,
            headers: Array.from(res.headers.entries()),
            body
          });
          prune();
        } catch(_e) {}
      }
      return res;
    }).catch((err) => {
      stats.errors += 1;
      throw err;
    }).finally(() => {
      inflight.delete(key);
    });
    inflight.set(key, p);
    return p.then(r => r.clone());
  };

  window.__ZOPS_FETCH_GUARD_V1__ = stats;
  window.__ZOPS_FETCH_GUARD_V1_CLEAR__ = function(){ inflight.clear(); cache.clear(); return true; };

  window.addEventListener('pagehide', function(){ try { inflight.clear(); cache.clear(); } catch(_e){} });
})();
