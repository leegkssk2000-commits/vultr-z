/* ZEL APP V51 Advanced ZEL Stack: compact account + team overlay only.
 * Scope: Advanced ZEL stack DOM only. Market/orderbook cards are not touched.
 */
(function () {
  'use strict';

  var VER = 'V51';
  var ROOT_ATTR = 'data-zel-v51-adv-root';
  var LEGACY_ATTRS = [
    '[data-zel-v48-adv-root]',
    '[data-zel-v49-adv-root]',
    '[data-zel-v50-adv-root]',
    '[data-zel-v51-legacy-root]'
  ];
  var TEAM_STATE = { active: 'Alpha' };
  var LAST_HTML = '';

  function q(sel, root) { return (root || document).querySelector(sel); }
  function qa(sel, root) { return Array.prototype.slice.call((root || document).querySelectorAll(sel)); }
  function cleanText(v) { return String(v == null ? '' : v).replace(/\s+/g, ' ').trim(); }
  function esc(v) {
    return String(v == null ? '' : v).replace(/[&<>"']/g, function (c) {
      return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c];
    });
  }
  function n(v) {
    if (v == null) return null;
    var s = String(v).replace(/,/g, '').replace(/[%x]/gi, '').trim();
    if (!s || s === '-' || s === '—' || /unbound|null|nan/i.test(s)) return null;
    var x = Number(s);
    return Number.isFinite(x) ? x : null;
  }
  function fmtNum(v, d) {
    var x = n(v);
    if (x == null) return '—';
    return x.toLocaleString(undefined, { maximumFractionDigits: d == null ? 4 : d, minimumFractionDigits: 0 });
  }
  function fmtPct(v) {
    var x = n(v);
    if (x == null) return '—';
    return (x > 0 ? '+' : '') + x.toFixed(3) + '%';
  }
  function fmtLev(v) {
    var x = n(v);
    return x == null ? '—' : (x.toFixed(x % 1 ? 1 : 0) + 'x');
  }
  function fmtMoney(v) {
    var x = n(v);
    if (x == null) return '—';
    var sign = x > 0 ? '+' : '';
    return sign + x.toLocaleString(undefined, { maximumFractionDigits: 2, minimumFractionDigits: 0 });
  }
  function clsByNumber(v) {
    var x = n(v);
    if (x == null) return 'neutral';
    if (x > 0) return 'good';
    if (x < 0) return 'bad';
    return 'neutral';
  }

  function readWindowFeed() {
    var out = {};
    try {
      var candidates = [
        window.ZEL_APP_V47_LIVE_ORDERBOOK_ACCOUNT,
        window.ZEL_APP_V47_LIVE_ORDERBOOK,
        window.ZEL_APP_V46_ORDERBOOK,
        window.ZEL_APP_V42_LIVE_FEED,
        window.ZEL_APP_LIVE_FEED,
        window.ZEL_SOURCE_ENVELOPE,
        window.ZEL_LIVE_NORMALIZED
      ];
      candidates.forEach(function (obj) {
        if (!obj || typeof obj !== 'object') return;
        var sym = obj.symbol || obj.sym || (obj.payload && obj.payload.symbol);
        if (!sym) return;
        out[String(sym).toUpperCase()] = obj.payload || obj;
      });
    } catch (_) {}
    return out;
  }

  function findCard(sym) {
    sym = String(sym || '').toUpperCase();
    return q('[data-z49-symbol="' + sym + '"], [data-z49-sym="' + sym + '"], [data-symbol="' + sym + '"]');
  }

  function readCard(sym) {
    var el = findCard(sym);
    var txt = cleanText(el ? el.textContent : '');
    var price = null;
    var m;
    if (el) {
      var priceEl = q('.z49-price,.z46-price,.price,[data-price]', el);
      if (priceEl) price = n(priceEl.getAttribute('data-price') || priceEl.textContent);
      if (price == null) {
        m = txt.match(/\b\d{1,3}(?:,\d{3})*(?:\.\d+)?\b|\b\d+\.\d+\b/);
        if (m) price = n(m[0]);
      }
    }
    var ticks = null;
    m = txt.match(/ticks\s*(\d+)/i);
    if (m) ticks = n(m[1]);
    var livePos = null, liveLev = null, virtPos = null, virtLev = null, upnl = null, virtUpnl = null;
    m = txt.match(/LIVE\s*POS\s*([+\-]?[\d.,]+%?)/i); if (m) livePos = n(m[1]);
    m = txt.match(/LIVE\s*LEV\s*([+\-]?[\d.,]+x?)/i); if (m) liveLev = n(m[1]);
    m = txt.match(/VIRT\s*POS\s*([+\-]?[\d.,]+%?)/i); if (m) virtPos = n(m[1]);
    m = txt.match(/VIRT\s*LEV\s*([+\-]?[\d.,]+x?)/i); if (m) virtLev = n(m[1]);
    m = txt.match(/(?:UPNL|uPNL|PNL)\s*([+\-]?[\d.,]+%?)/i); if (m) upnl = n(m[1]);
    m = txt.match(/(?:V\.PNL|VIRT\s*PNL)\s*([+\-]?[\d.,]+%?)/i); if (m) virtUpnl = n(m[1]);
    return { el: el, txt: txt, price: price, ticks: ticks, livePos: livePos, liveLev: liveLev, virtPos: virtPos, virtLev: virtLev, upnl: upnl, virtUpnl: virtUpnl };
  }

  function readSourceFromDOM() {
    var out = {};
    qa('[data-z49-symbol],[data-z49-sym],[data-symbol]').forEach(function (el) {
      var sym = el.getAttribute('data-z49-symbol') || el.getAttribute('data-z49-sym') || el.getAttribute('data-symbol');
      if (!sym) return;
      out[String(sym).toUpperCase()] = readCard(sym);
    });
    ['BTCUSDT', 'ETHUSDT', 'SOLUSDT', 'XRPUSDT', 'LINKUSDT'].forEach(function (s) {
      if (!out[s]) out[s] = readCard(s);
    });
    return out;
  }

  function sourceData() {
    var dom = readSourceFromDOM();
    var win = readWindowFeed();
    Object.keys(win).forEach(function (sym) {
      var w = win[sym] || {};
      dom[sym] = dom[sym] || {};
      if (dom[sym].price == null) dom[sym].price = n(w.price || w.last || w.markPrice || w.mid);
      if (dom[sym].livePos == null) dom[sym].livePos = n(w.pos_pct || w.pos || w.position_pct);
      if (dom[sym].liveLev == null) dom[sym].liveLev = n(w.lev || w.leverage);
      if (dom[sym].upnl == null) dom[sym].upnl = n(w.upnl || w.uPNL || w.unrealizedPnl || w.pnl);
      if (dom[sym].virtPos == null) dom[sym].virtPos = n(w.virtual_pos_pct || w.virt_pos_pct);
      if (dom[sym].virtLev == null) dom[sym].virtLev = n(w.virtual_lev || w.virt_lev);
      if (dom[sym].virtUpnl == null) dom[sym].virtUpnl = n(w.virtual_upnl || w.virt_upnl);
    });
    return dom;
  }

  function findLegacyRoot() {
    for (var i = 0; i < LEGACY_ATTRS.length; i++) {
      var el = q(LEGACY_ATTRS[i]);
      if (el) return el;
    }
    var nodes = qa('section,article,div,details');
    for (var j = 0; j < nodes.length; j++) {
      var t = cleanText(nodes[j].textContent);
      if (!t) continue;
      if (/Advanced\s+ZEL\s+stack/i.test(t) && !nodes[j].closest('[' + ROOT_ATTR + ']')) return nodes[j];
    }
    return null;
  }

  function insertAfterMarketCards(root) {
    var cards = qa('[data-z49-symbol],[data-z49-sym]');
    if (cards.length) {
      var last = cards[cards.length - 1];
      last.parentNode.insertBefore(root, last.nextSibling);
      return true;
    }
    var body = document.body || document.documentElement;
    body.appendChild(root);
    return true;
  }

  function ensureRoot() {
    var root = q('[' + ROOT_ATTR + ']');
    if (root) return root;
    root = document.createElement('section');
    root.setAttribute(ROOT_ATTR, '1');
    root.setAttribute('data-zel-v49-card', '1');
    root.className = 'z51-adv-root';
    var old = findLegacyRoot();
    if (old && old.parentNode) old.parentNode.replaceChild(root, old);
    else insertAfterMarketCards(root);
    return root;
  }

  function removeLegacyRoots(root) {
    LEGACY_ATTRS.forEach(function (sel) {
      qa(sel).forEach(function (el) {
        if (el !== root && el.parentNode) el.parentNode.removeChild(el);
      });
    });
    qa('section,article,div,details').forEach(function (el) {
      if (el === root || el.closest('[' + ROOT_ATTR + ']')) return;
      var t = cleanText(el.textContent);
      if (/Advanced\s+ZEL\s+stack/i.test(t) && /DATA HOLD|source-bound|required|BingX paper|Alpha route|LiCo|ZICO|Zlice|ZBot/i.test(t)) {
        if (el.parentNode) el.parentNode.removeChild(el);
      }
    });
  }

  function auditLine(feedOk, btc) {
    var proof = feedOk ? 'proof pending' : 'proof required';
    var age = btc && btc.ticks != null ? ('ticks ' + btc.ticks) : 'ticks —';
    return 'feed ' + (feedOk ? 'exchange live' : 'waiting') + ' · ' + proof + ' · hash pending · ' + age;
  }

  function accountBox(title, mode, sym, pos, lev, upnl, extra) {
    return '<div class="z51-box z51-' + mode + '">' +
      '<div class="z51-box-head"><b>' + esc(title) + '</b><span>' + esc(sym || 'BTCUSDT') + '</span></div>' +
      '<div class="z51-metric-grid">' +
        '<span>POS</span><b>' + esc(pos == null ? '—' : fmtPct(pos)) + '</b>' +
        '<span>LEV</span><b>' + esc(lev == null ? '—' : fmtLev(lev)) + '</b>' +
        '<span>uPNL</span><b class="' + clsByNumber(upnl) + '">' + esc(upnl == null ? '—' : fmtMoney(upnl)) + '</b>' +
        '<span>' + esc(extra && extra.label ? extra.label : 'STATE') + '</span><b>' + esc(extra && extra.value ? extra.value : 'read-only') + '</b>' +
      '</div>' +
    '</div>';
  }

  function teamData() {
    return {
      Alpha: { tier: 'S', role: 'primary route', status: 'active', score: '84', bots: [['LBot','lead','pass'],['MBot','method','pass'],['OBot','venue','watch'],['SBot','safety','clear']], rule: 'trend lane owns route while proof/guard clean' },
      Beta:  { tier: 'A', role: 'fallback range', status: 'standby', score: '71', bots: [['LBot','range','ready'],['MBot','confirm','ready'],['OBot','venue','watch'],['SBot','safety','clear']], rule: 'promote only if Alpha decays or range edge wins' },
      Gamma: { tier: 'B', role: 'probe/retest', status: 'probe', score: '58', bots: [['LBot','probe','ready'],['MBot','retest','wait'],['OBot','venue','watch'],['SBot','safety','clear']], rule: 'observe only; no live route without guard pass' },
      Delta: { tier: 'G', role: 'guard/veto', status: 'guard', score: '92', bots: [['Risk','DD/liquidation','clear'],['Proof','source parity','pending'],['Venue','execution','read-only'],['Noise','alert throttle','clear']], rule: 'can veto; cannot promote trade alone' }
    };
  }

  function teamOverlay() {
    var teams = teamData();
    var active = teams[TEAM_STATE.active] ? TEAM_STATE.active : 'Alpha';
    var t = teams[active];
    var pills = Object.keys(teams).map(function (name) {
      return '<button type="button" class="z51-team-pill ' + (name === active ? 'on' : '') + '" data-z51-team="' + esc(name) + '">' + esc(name) + '</button>';
    }).join('');
    var bots = t.bots.map(function (b) {
      return '<div class="z51-bot"><span><b>' + esc(b[0]) + '</b><small>' + esc(b[1]) + '</small></span><em>' + esc(b[2]) + '</em></div>';
    }).join('');
    return '<div class="z51-box z51-teambox">' +
      '<div class="z51-box-head"><b>Team overlay</b><span>single active view</span></div>' +
      '<div class="z51-team-pills">' + pills + '</div>' +
      '<div class="z51-team-main">' +
        '<div><h4>' + esc(active) + ' · Tier ' + esc(t.tier) + '</h4><p>' + esc(t.role) + ' · ' + esc(t.rule) + '</p></div>' +
        '<strong>' + esc(t.score) + '</strong>' +
      '</div>' +
      '<div class="z51-bots">' + bots + '</div>' +
    '</div>';
  }

  function symbolStrip(data) {
    return ['BTCUSDT','ETHUSDT','SOLUSDT','XRPUSDT','LINKUSDT'].map(function (s) {
      var d = data[s] || {};
      return '<span><b>' + esc(s.replace('USDT','')) + '</b> ' + esc(fmtNum(d.price, s === 'BTCUSDT' ? 1 : 4)) + '</span>';
    }).join('');
  }

  function render() {
    var root = ensureRoot();
    removeLegacyRoots(root);
    var data = sourceData();
    var btc = data.BTCUSDT || {};
    var feedOk = !!(btc.price || (data.ETHUSDT && data.ETHUSDT.price) || (data.SOLUSDT && data.SOLUSDT.price));
    var html = '' +
      '<div class="z51-head">' +
        '<div><small>ADVANCED ZEL STACK</small><h3>Live · Virtual · Guard</h3><p>시장카드/호가창은 그대로 두고 계좌·uPNL·팀 오버레이만 압축 표시.</p></div>' +
        '<b class="z51-state">READ-ONLY HOLD</b>' +
      '</div>' +
      '<div class="z51-symbol-strip">' + symbolStrip(data) + '</div>' +
      '<div class="z51-grid">' +
        accountBox('Live account', 'live', 'BTCUSDT', btc.livePos, btc.liveLev, btc.upnl, { label: 'ORDER', value: 'RO' }) +
        accountBox('Virtual account', 'virt', 'PAPER', btc.virtPos, btc.virtLev, btc.virtUpnl, { label: 'MODE', value: 'simulation' }) +
        '<div class="z51-box z51-guard"><div class="z51-box-head"><b>Execution guard</b><span>orders</span></div><h4>ORDER RO · DATA HOLD</h4><p>최종 주문/차단 판정은 CF/GS proof가 붙을 때만 갱신.</p><div class="z51-chips"><span>proof pending</span><span>guard read-only</span><span>route locked</span></div></div>' +
        teamOverlay() +
      '</div>' +
      '<div class="z51-audit">' + esc(auditLine(feedOk, btc)) + '</div>';
    if (html !== LAST_HTML || root.innerHTML.indexOf('z51-head') < 0) {
      root.innerHTML = html;
      LAST_HTML = html;
    }
  }

  function bindClicks(ev) {
    var btn = ev.target && ev.target.closest ? ev.target.closest('[data-z51-team]') : null;
    if (!btn) return;
    TEAM_STATE.active = btn.getAttribute('data-z51-team') || 'Alpha';
    LAST_HTML = '';
    render();
  }

  function start() {
    try { render(); } catch (e) { console.warn('[ZEL V51] render skipped', e); }
    document.addEventListener('click', bindClicks, true);
    setInterval(function () {
      try { render(); } catch (e) { console.warn('[ZEL V51] render skipped', e); }
    }, 1000);
  }

  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', start, { once: true });
  else start();
})();
