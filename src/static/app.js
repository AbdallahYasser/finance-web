// finance-web W3 — login + dashboard + transactions + items + places.

let CONFIG = null;
let ME = null;
let LOOKUPS = null;

const TYPE_ICONS = {
  cash: '💵', bank: '🏦', e_wallet: '📱', asset_gold: '🥇',
};

// One palette for chart lines per place
const CHART_PALETTE = [
  '#38bdf8', '#22c55e', '#f59e0b', '#ef4444',
  '#a78bfa', '#ec4899', '#14b8a6', '#84cc16',
];

// ---------- Helpers ----------

function $(id) { return document.getElementById(id); }
function show(id) {
  ['login-screen', 'app'].forEach(s => $(s).classList.add('hidden'));
  $(id).classList.remove('hidden');
}

async function fetchJSON(url, opts) {
  const res = await fetch(url, opts);
  if (!res.ok) {
    const err = new Error(`HTTP ${res.status}`);
    err.status = res.status;
    throw err;
  }
  return res.json();
}

function escapeHtml(s) {
  if (s == null) return '';
  return String(s).replace(/&/g, '&amp;').replace(/</g, '&lt;')
    .replace(/>/g, '&gt;').replace(/"/g, '&quot;').replace(/'/g, '&#39;');
}

function fmtAmount(cents) {
  if (cents == null) return '—';
  const sign = cents < 0 ? '-' : '';
  const abs = Math.abs(cents);
  const whole = Math.floor(abs / 100);
  const frac = abs % 100;
  return sign + whole.toLocaleString('en-US') + '.' + String(frac).padStart(2, '0') + ' EGP';
}

function fmtDateRelative(iso) {
  if (!iso) return '—';
  const normalized = iso.replace(' ', 'T').replace(/Z?$/, 'Z');
  const dt = new Date(normalized);
  if (isNaN(dt.getTime())) return iso.slice(0, 10);
  const now = new Date();
  const dtDate = new Date(dt.getFullYear(), dt.getMonth(), dt.getDate());
  const todayDate = new Date(now.getFullYear(), now.getMonth(), now.getDate());
  const days = Math.round((todayDate - dtDate) / 86400000);
  if (days === 0) {
    const hh = String(dt.getHours()).padStart(2, '0');
    const mm = String(dt.getMinutes()).padStart(2, '0');
    return `today ${hh}:${mm}`;
  }
  if (days === 1) return 'yesterday';
  if (days >= 2 && days <= 6) return `${days} days ago`;
  return dt.toISOString().slice(0, 10);
}

function fmtDateAbsolute(iso) {
  if (!iso) return '—';
  const normalized = iso.replace(' ', 'T').replace(/Z?$/, 'Z');
  const dt = new Date(normalized);
  if (isNaN(dt.getTime())) return iso;
  return dt.toLocaleString('en-GB', {
    year: 'numeric', month: 'short', day: '2-digit',
    hour: '2-digit', minute: '2-digit',
  });
}

function txSign(type) {
  if (type === 'spend') return { sign: '−', cls: 'minus' };
  if (type === 'income' || type === 'refund') return { sign: '+', cls: 'plus' };
  if (type === 'transfer') return { sign: '↔', cls: 'transfer' };
  return { sign: '', cls: '' };
}

function txIcon(t) {
  if (t.category_icon) return t.category_icon;
  if (t.type === 'transfer') return '↔';
  if (t.type === 'income')   return '💰';
  if (t.type === 'refund')   return '↩️';
  return '💸';
}

function txCategoryName(t) {
  if (t.category_name) return t.category_name;
  if (t.type === 'transfer') return 'Transfer';
  if (t.type === 'income')   return 'Income';
  if (t.type === 'refund')   return 'Refund';
  return '—';
}

function txItemPlace(t) {
  const parts = [];
  if (t.item_name) {
    let name = t.item_name;
    if (t.item_size) name += ` (${t.item_size})`;
    parts.push(name);
  }
  if (t.place_branch) parts.push(`@ ${t.place_branch}`);
  return parts.join(' ');
}

function placeLabel(p) {
  if (!p) return '—';
  let label = p.branch_name || `Place ${p.place_id || p.id}`;
  if (p.chain_name && p.chain_name !== p.branch_name) label += ` · ${p.chain_name}`;
  return label;
}

function itemLabel(i) {
  if (!i) return '—';
  let label = i.name_en || i.canonical_name_en || i.name_ar || i.canonical_name_ar || `Item ${i.id}`;
  if (i.size) label += ` (${i.size})`;
  return label;
}

// ---------- Telegram login ----------

function mountTelegramWidget() {
  if (!CONFIG || !CONFIG.bot_username) return;
  const link = $('bot-link');
  if (link) {
    link.textContent = '@' + CONFIG.bot_username;
    link.href = 'https://t.me/' + CONFIG.bot_username;
  }
  const c = $('telegram-login-widget');
  c.innerHTML = '';
  const s = document.createElement('script');
  s.async = true;
  s.src = 'https://telegram.org/js/telegram-widget.js?22';
  s.setAttribute('data-telegram-login', CONFIG.bot_username);
  s.setAttribute('data-size', 'large');
  s.setAttribute('data-onauth', 'onTelegramAuth(user)');
  s.setAttribute('data-request-access', 'write');
  s.setAttribute('data-userpic', 'true');
  c.appendChild(s);
}

async function onTelegramAuth(user) {
  try {
    await fetchJSON('/api/auth/telegram', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(user),
    });
    location.reload();
  } catch (e) {
    alert('Login failed: ' + (e.message || 'unknown'));
  }
}

async function logout() {
  try { await fetchJSON('/api/logout', { method: 'POST' }); } catch (_) {}
  location.reload();
}

// ---------- Routing ----------

let currentRoute = 'dashboard';
const ROUTES = ['dashboard', 'transactions', 'items', 'places'];

function setRoute(route) {
  currentRoute = route;
  document.querySelectorAll('.page').forEach(p => p.classList.add('hidden'));
  document.querySelectorAll('.nav-link').forEach(a => a.classList.remove('active'));
  const page = $(`page-${route}`);
  const link = document.querySelector(`.nav-link[data-route="${route}"]`);
  if (page) page.classList.remove('hidden');
  if (link) link.classList.add('active');
  refreshCurrent();
}

function onHashChange() {
  const route = (location.hash || '#dashboard').replace('#', '').split('?')[0];
  setRoute(ROUTES.includes(route) ? route : 'dashboard');
}

function refreshCurrent() {
  if (currentRoute === 'dashboard')    return loadDashboard();
  if (currentRoute === 'transactions') return loadTransactions();
  if (currentRoute === 'items')        return loadItems();
  if (currentRoute === 'places')       return loadPlaces();
}

// ---------- Dashboard ----------

function renderHeader(me) {
  $('user-name').textContent = `User ${me.user_id}`;
}

function renderNetWorth(cents, walletCount) {
  $('net-worth').textContent = fmtAmount(cents);
  const noun = walletCount === 1 ? 'wallet' : 'wallets';
  $('net-worth-sub').textContent = `across ${walletCount} ${noun}`;
}

function renderWallets(wallets) {
  const root = $('wallets-list');
  if (!wallets || wallets.length === 0) {
    root.innerHTML = '<div class="muted small">No wallets yet. Use the bot.</div>';
    return;
  }
  root.innerHTML = wallets.map(w => {
    const icon = TYPE_ICONS[w.type] || '•';
    const name = w.name_en || w.name_ar || `Wallet ${w.id}`;
    const balCls = w.balance_cents < 0 ? 'wallet-balance negative' : 'wallet-balance';
    return `<div class="wallet-row">
      <div class="wallet-name"><span class="wallet-icon">${icon}</span><span>${escapeHtml(name)}</span></div>
      <div class="${balCls}">${fmtAmount(w.balance_cents)}</div>
    </div>`;
  }).join('');
}

function renderMonthBreakdown(monthData) {
  $('month-total').textContent = fmtAmount(monthData.total_cents || 0);
  $('month-name').textContent = new Date().toLocaleString('en-US', { month: 'long' });
  const root = $('month-by-category');
  const rows = monthData.by_category || [];
  if (rows.length === 0) {
    root.innerHTML = '<div class="muted small">No spending this month yet.</div>';
    return;
  }
  const max = rows[0].total_cents || 1;
  root.innerHTML = rows.slice(0, 8).map(r => {
    const pct = Math.max(2, Math.round((r.total_cents / max) * 100));
    return `<div class="bar-row">
      <div class="bar-meta">
        <span class="bar-cat">${r.category_icon || '•'} ${escapeHtml(r.category_name)}</span>
        <span class="bar-amt">${fmtAmount(r.total_cents)}</span>
      </div>
      <div class="bar-track"><div class="bar-fill" style="width:${pct}%"></div></div>
    </div>`;
  }).join('');
}

function renderRecent(rows) {
  const root = $('recent-list');
  if (!rows || rows.length === 0) {
    root.innerHTML = '<div class="muted small">No transactions yet.</div>';
    return;
  }
  root.innerHTML = rows.map(t => {
    const { sign, cls } = txSign(t.type);
    const cat = txCategoryName(t);
    const icon = txIcon(t);
    const itemPlace = txItemPlace(t);
    const parts = [];
    if (itemPlace) parts.push(itemPlace);
    if (t.note) parts.push(`<span class="tx-note">${escapeHtml(t.note)}</span>`);
    parts.push(fmtDateRelative(t.occurred_at));
    return `<div class="tx-row">
      <div class="tx-icon">${icon}</div>
      <div class="tx-mid">
        <div class="tx-line1">${escapeHtml(cat)}</div>
        <div class="tx-line2">${parts.join(' · ')}</div>
      </div>
      <div class="tx-amount ${cls}">${sign}${fmtAmount(t.amount_cents).replace('-', '')}</div>
    </div>`;
  }).join('');
}

async function loadDashboard() {
  const btn = $('refresh-btn');
  btn.classList.add('spinning');
  try {
    const data = await fetchJSON('/api/dashboard');
    renderNetWorth(data.net_worth_cents, (data.wallets || []).length);
    renderWallets(data.wallets);
    renderMonthBreakdown(data.this_month || { total_cents: 0, by_category: [] });
    renderRecent(data.recent_transactions);
  } catch (e) {
    if (e.status === 401 || e.status === 403) { show('login-screen'); mountTelegramWidget(); return; }
    alert('Failed to load dashboard: ' + (e.message || 'unknown'));
  } finally {
    btn.classList.remove('spinning');
  }
}

// ---------- Transactions ----------

let TX_STATE = { page: 1, page_size: 50 };

async function ensureLookups() {
  if (LOOKUPS) return LOOKUPS;
  LOOKUPS = await fetchJSON('/api/lookups');
  populateFilterDropdowns();
  return LOOKUPS;
}

function populateFilterDropdowns() {
  const wsel = $('f-wallet');
  wsel.innerHTML = '<option value="">— Any —</option>' +
    (LOOKUPS.wallets || []).map(w => `<option value="${w.id}">${escapeHtml(w.name_en || w.name_ar || `Wallet ${w.id}`)}</option>`).join('');

  const csel = $('f-category');
  const cats = LOOKUPS.categories || [];
  const parents = cats.filter(c => c.parent_id == null);
  const childrenByParent = {};
  cats.filter(c => c.parent_id != null).forEach(c => {
    (childrenByParent[c.parent_id] = childrenByParent[c.parent_id] || []).push(c);
  });
  let opts = '<option value="">— Any —</option>';
  for (const p of parents) {
    opts += `<option value="${p.id}">${p.icon || '•'} ${escapeHtml(p.name_en || p.name_ar)}</option>`;
    for (const ch of (childrenByParent[p.id] || [])) {
      opts += `<option value="${ch.id}">  ↳ ${ch.icon || '·'} ${escapeHtml(ch.name_en || ch.name_ar)}</option>`;
    }
  }
  csel.innerHTML = opts;

  const psel = $('f-place');
  psel.innerHTML = '<option value="">— Any —</option>' +
    (LOOKUPS.places || []).map(p => {
      let label = p.branch_name || `Place ${p.id}`;
      if (p.chain_name && p.chain_name !== p.branch_name) label += ` · ${p.chain_name}`;
      return `<option value="${p.id}">${escapeHtml(label)}</option>`;
    }).join('');

  const isel = $('f-item');
  isel.innerHTML = '<option value="">— Any —</option>' +
    (LOOKUPS.items || []).map(it => {
      let label = it.canonical_name_en || it.canonical_name_ar || `Item ${it.id}`;
      if (it.size) label += ` (${it.size})`;
      return `<option value="${it.id}">${escapeHtml(label)}</option>`;
    }).join('');
}

function readFilters() {
  const f = {
    date_from:   $('f-date-from').value || '',
    date_to:     $('f-date-to').value || '',
    type:        $('f-type').value || '',
    wallet_id:   $('f-wallet').value || '',
    category_id: $('f-category').value || '',
    place_id:    $('f-place').value || '',
    item_id:     $('f-item').value || '',
    q:           $('f-q').value.trim(),
    sort:        $('f-sort').value || 'date_desc',
    page:        TX_STATE.page,
    page_size:   parseInt($('f-page-size').value, 10) || 50,
  };
  if (f.date_from) f.date_from = `${f.date_from}T00:00:00Z`;
  if (f.date_to)   f.date_to   = `${f.date_to}T23:59:59Z`;
  return f;
}

function buildQuery(filters) {
  const params = new URLSearchParams();
  Object.entries(filters).forEach(([k, v]) => {
    if (v !== '' && v != null) params.set(k, v);
  });
  return params.toString();
}

function syncFilterUrl(filters) {
  const visible = { ...filters };
  delete visible.page_size;
  delete visible.page;
  const q = buildQuery(visible);
  const newHash = q ? `#transactions?${q}` : '#transactions';
  if (location.hash !== newHash) {
    history.replaceState(null, '', newHash);
  }
}

function applyFilters() { TX_STATE.page = 1; loadTransactions(); }

function clearFilters() {
  ['f-date-from', 'f-date-to', 'f-type', 'f-wallet',
   'f-category', 'f-place', 'f-item', 'f-q'].forEach(id => { $(id).value = ''; });
  $('f-sort').value = 'date_desc';
  $('f-page-size').value = '50';
  TX_STATE.page = 1;
  loadTransactions();
}

function gotoPage(p) { TX_STATE.page = Math.max(1, p); loadTransactions(); }

function renderTxTable(payload) {
  const wrap = $('tx-table-wrap');
  $('tx-total').textContent = `${payload.total} transaction${payload.total === 1 ? '' : 's'}`;

  const rows = payload.rows || [];
  if (rows.length === 0) {
    wrap.innerHTML = '<div class="muted small" style="padding:24px 0;text-align:center;">No transactions match these filters.</div>';
    $('pagination').innerHTML = '';
    return;
  }

  const trs = rows.map(t => {
    const { sign, cls } = txSign(t.type);
    const icon = txIcon(t);
    const cat = txCategoryName(t);
    const itemPlace = txItemPlace(t) || '—';
    let walletCol = '';
    if (t.type === 'transfer') {
      walletCol = `${escapeHtml(t.source_wallet_name || '?')} → ${escapeHtml(t.dest_wallet_name || '?')}`;
    } else if (t.type === 'spend') {
      walletCol = escapeHtml(t.source_wallet_name || '?');
    } else {
      walletCol = escapeHtml(t.dest_wallet_name || '?');
    }
    return `
      <tr data-id="${t.id}" onclick="toggleTxDetail(${t.id})">
        <td class="col-date">${fmtDateRelative(t.occurred_at)}</td>
        <td class="col-cat"><span class="icon">${icon}</span>${escapeHtml(cat)}</td>
        <td class="hide-mobile">${escapeHtml(itemPlace)}</td>
        <td class="hide-mobile">${walletCol}</td>
        <td class="col-amount ${cls}">${sign}${fmtAmount(t.amount_cents).replace('-', '')}</td>
      </tr>
      <tr class="detail-row hidden" id="detail-${t.id}">
        <td colspan="5">
          <div class="detail-inner">
            <div class="kv-row"><span>Type</span><span>${t.type}</span></div>
            <div class="kv-row"><span>Date</span><span>${fmtDateAbsolute(t.occurred_at)}</span></div>
            ${t.item_name ? `<div class="kv-row"><span>Item</span><span>${escapeHtml(t.item_name)}${t.item_size ? ` (${escapeHtml(t.item_size)})` : ''}</span></div>` : ''}
            ${t.place_branch ? `<div class="kv-row"><span>Place</span><span>${escapeHtml(t.place_branch)}${t.place_chain && t.place_chain !== t.place_branch ? ` · ${escapeHtml(t.place_chain)}` : ''}</span></div>` : ''}
            ${t.source_wallet_name ? `<div class="kv-row"><span>From wallet</span><span>${escapeHtml(t.source_wallet_name)}</span></div>` : ''}
            ${t.dest_wallet_name ? `<div class="kv-row"><span>To wallet</span><span>${escapeHtml(t.dest_wallet_name)}</span></div>` : ''}
            ${t.note ? `<div class="kv-row"><span>Note</span><span>${escapeHtml(t.note)}</span></div>` : ''}
            <div class="kv-row"><span>ID</span><span>#${t.id}</span></div>
          </div>
        </td>
      </tr>
    `;
  }).join('');

  wrap.innerHTML = `
    <table class="tx-table">
      <thead>
        <tr>
          <th class="col-date">Date</th>
          <th>Category</th>
          <th class="hide-mobile">Item / Place</th>
          <th class="hide-mobile">Wallet</th>
          <th class="col-amount">Amount</th>
        </tr>
      </thead>
      <tbody>${trs}</tbody>
    </table>
  `;

  const { page, total_pages } = payload;
  $('pagination').innerHTML = `
    <button onclick="gotoPage(1)"             ${page <= 1 ? 'disabled' : ''} title="First">«</button>
    <button onclick="gotoPage(${page - 1})"   ${page <= 1 ? 'disabled' : ''}>‹ Prev</button>
    <span class="page-info">Page ${page} of ${total_pages}</span>
    <button onclick="gotoPage(${page + 1})"   ${page >= total_pages ? 'disabled' : ''}>Next ›</button>
    <button onclick="gotoPage(${total_pages})" ${page >= total_pages ? 'disabled' : ''} title="Last">»</button>
  `;
}

function toggleTxDetail(id) { $(`detail-${id}`)?.classList.toggle('hidden'); }

let _appliedHashOnce = false;
function applyFiltersFromUrl() {
  if (_appliedHashOnce) return;
  _appliedHashOnce = true;
  const hash = location.hash || '';
  const idx = hash.indexOf('?');
  if (idx < 0) return;
  const params = new URLSearchParams(hash.slice(idx + 1));
  const set = (id, key, transform) => {
    const v = params.get(key);
    if (v != null && v !== '') $(id).value = transform ? transform(v) : v;
  };
  set('f-date-from', 'date_from', v => v.slice(0, 10));
  set('f-date-to',   'date_to',   v => v.slice(0, 10));
  set('f-type',      'type');
  set('f-wallet',    'wallet_id');
  set('f-category',  'category_id');
  set('f-place',     'place_id');
  set('f-item',      'item_id');
  set('f-q',         'q');
  set('f-sort',      'sort');
}

async function loadTransactions() {
  await ensureLookups();
  applyFiltersFromUrl();
  const filters = readFilters();
  syncFilterUrl(filters);
  const btn = $('refresh-btn');
  btn.classList.add('spinning');
  $('tx-table-wrap').innerHTML = '<div class="muted small" style="padding:24px 0;text-align:center;">Loading…</div>';
  try {
    const data = await fetchJSON('/api/transactions?' + buildQuery(filters));
    renderTxTable(data);
  } catch (e) {
    if (e.status === 401 || e.status === 403) { show('login-screen'); mountTelegramWidget(); return; }
    $('tx-table-wrap').innerHTML = `<div class="muted small">Error: ${escapeHtml(e.message || 'unknown')}</div>`;
  } finally {
    btn.classList.remove('spinning');
  }
}

// ---------- Items ----------

const _itemCharts = new Map();

async function loadItems() {
  const btn = $('refresh-btn');
  btn.classList.add('spinning');
  $('items-table-wrap').innerHTML = '<div class="muted small" style="padding:24px 0;text-align:center;">Loading…</div>';
  try {
    const data = await fetchJSON('/api/items');
    renderItemsTable(data.items || []);
  } catch (e) {
    if (e.status === 401 || e.status === 403) { show('login-screen'); mountTelegramWidget(); return; }
    $('items-table-wrap').innerHTML = `<div class="muted small">Error: ${escapeHtml(e.message || 'unknown')}</div>`;
  } finally {
    btn.classList.remove('spinning');
  }
}

function renderItemsTable(items) {
  $('items-meta').textContent = `${items.length} item${items.length === 1 ? '' : 's'}`;
  const wrap = $('items-table-wrap');
  if (items.length === 0) {
    wrap.innerHTML = '<div class="muted small" style="padding:24px 0;text-align:center;">No items yet. Add some via the bot.</div>';
    return;
  }
  const trs = items.map(it => `
    <tr data-id="${it.id}" onclick="toggleItemDetail(${it.id})">
      <td>${escapeHtml(itemLabel(it))}</td>
      <td class="hide-mobile">${it.tx_count || 0}</td>
      <td class="hide-mobile">${it.place_count || 0}</td>
      <td class="col-amount">${fmtAmount(it.last_price_cents)}</td>
      <td class="col-amount">${fmtAmount(it.total_spent_cents)}</td>
      <td class="hide-mobile col-date">${it.last_observed_at ? fmtDateRelative(it.last_observed_at) : '—'}</td>
    </tr>
    <tr class="detail-row hidden" id="item-detail-${it.id}">
      <td colspan="6"><div id="item-detail-body-${it.id}" class="detail-inner-block">
        <div class="muted small">Loading…</div>
      </div></td>
    </tr>
  `).join('');

  wrap.innerHTML = `
    <table class="tx-table">
      <thead>
        <tr>
          <th>Item</th>
          <th class="hide-mobile">Bought</th>
          <th class="hide-mobile">Places</th>
          <th class="col-amount">Last price</th>
          <th class="col-amount">Total spent</th>
          <th class="hide-mobile col-date">Last seen</th>
        </tr>
      </thead>
      <tbody>${trs}</tbody>
    </table>
  `;
}

async function toggleItemDetail(id) {
  const row = $(`item-detail-${id}`);
  if (!row) return;
  const wasHidden = row.classList.contains('hidden');
  row.classList.toggle('hidden');
  if (wasHidden) {
    await populateItemDetail(id);
  }
}

async function populateItemDetail(id) {
  const body = $(`item-detail-body-${id}`);
  body.innerHTML = '<div class="muted small">Loading…</div>';
  let data;
  try {
    data = await fetchJSON(`/api/items/${id}`);
  } catch (e) {
    body.innerHTML = `<div class="muted small">Failed to load: ${escapeHtml(e.message)}</div>`;
    return;
  }
  const { item, places, summary } = data;

  const summaryHtml = `
    <div class="entity-summary">
      <div class="kv-tile"><span>Total spent</span><strong>${fmtAmount(summary.total_spent_cents)}</strong></div>
      <div class="kv-tile"><span>Transactions</span><strong>${summary.tx_count}</strong></div>
      <div class="kv-tile"><span>Places</span><strong>${summary.place_count}</strong></div>
      <div class="kv-tile"><span>Min</span><strong>${fmtAmount(summary.overall_min_cents)}</strong></div>
      <div class="kv-tile"><span>Avg</span><strong>${fmtAmount(summary.overall_avg_cents)}</strong></div>
      <div class="kv-tile"><span>Max</span><strong>${fmtAmount(summary.overall_max_cents)}</strong></div>
    </div>
  `;

  const placesHtml = places.length === 0 ? '' : `
    <h4 class="detail-section-title">Per-place price history</h4>
    <table class="tx-table compact">
      <thead>
        <tr>
          <th>Place</th>
          <th>Observations</th>
          <th class="col-amount">Min</th>
          <th class="col-amount">Last</th>
          <th class="col-amount">Max</th>
        </tr>
      </thead>
      <tbody>
        ${places.map(p => `
          <tr>
            <td>${escapeHtml(placeLabel(p))}</td>
            <td>${p.observation_count}</td>
            <td class="col-amount">${fmtAmount(p.min_cents)}</td>
            <td class="col-amount">${fmtAmount(p.last_cents)}</td>
            <td class="col-amount">${fmtAmount(p.max_cents)}</td>
          </tr>
        `).join('')}
      </tbody>
    </table>
  `;

  const chartHtml = places.length > 0 ? `
    <h4 class="detail-section-title">Price chart</h4>
    <div class="chart-wrap"><canvas id="item-chart-${id}"></canvas></div>
  ` : '<div class="muted small" style="margin-top:12px;">No price observations yet. Buy this item again from the bot to start the history.</div>';

  body.innerHTML = summaryHtml + chartHtml + placesHtml;

  if (places.length > 0) {
    drawItemChart(id, places);
  }
}

function drawItemChart(id, places) {
  const canvas = $(`item-chart-${id}`);
  if (!canvas) return;
  if (_itemCharts.has(id)) {
    _itemCharts.get(id).destroy();
    _itemCharts.delete(id);
  }
  if (typeof Chart === 'undefined') {
    canvas.parentElement.innerHTML = '<div class="muted small">Chart library unavailable.</div>';
    return;
  }

  const datasets = places.map((p, i) => {
    const color = CHART_PALETTE[i % CHART_PALETTE.length];
    return {
      label: placeLabel(p),
      data: p.observations.map(o => ({
        x: o.observed_at,
        y: o.price_cents / 100,  // EGP for display
      })),
      borderColor: color,
      backgroundColor: color,
      pointRadius: 4,
      tension: 0.2,
      spanGaps: true,
    };
  });

  const chart = new Chart(canvas.getContext('2d'), {
    type: 'line',
    data: { datasets },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      parsing: false,
      scales: {
        x: {
          type: 'time',
          time: { tooltipFormat: 'yyyy-LL-dd HH:mm', unit: 'day' },
          ticks: { color: '#94a3b8' },
          grid: { color: '#334155' },
        },
        y: {
          ticks: {
            color: '#94a3b8',
            callback: v => v.toLocaleString('en-US') + ' EGP',
          },
          grid: { color: '#334155' },
          beginAtZero: false,
        },
      },
      plugins: {
        legend: { labels: { color: '#e2e8f0' } },
        tooltip: {
          callbacks: {
            label: ctx => `${ctx.dataset.label}: ${ctx.parsed.y.toFixed(2)} EGP`,
          },
        },
      },
    },
  });

  _itemCharts.set(id, chart);
}

// Chart.js v4 needs a date adapter for time scales — bring in luxon adapter on demand.
// We avoid the adapter dependency by formatting x as a date string and using 'category' scale instead.
// Override above to use category if time adapter unavailable:
(function patchChartTimeFallback() {
  // Detect if time adapter is missing and switch scale type lazily
  const orig = drawItemChart;
  window.drawItemChart = function(id, places) {
    const canvas = $(`item-chart-${id}`);
    if (!canvas) return;
    if (_itemCharts.has(id)) { _itemCharts.get(id).destroy(); _itemCharts.delete(id); }
    if (typeof Chart === 'undefined') {
      canvas.parentElement.innerHTML = '<div class="muted small">Chart library unavailable.</div>';
      return;
    }
    // Build labels (sorted union of all observation timestamps) for category-x chart
    const allDates = new Set();
    places.forEach(p => p.observations.forEach(o => allDates.add(o.observed_at)));
    const labels = Array.from(allDates).sort();
    const labelDisplay = labels.map(d => fmtDateAbsolute(d).replace(/, \d{2}:\d{2}$/, ''));

    const datasets = places.map((p, i) => {
      const color = CHART_PALETTE[i % CHART_PALETTE.length];
      const map = new Map(p.observations.map(o => [o.observed_at, o.price_cents / 100]));
      return {
        label: placeLabel(p),
        data: labels.map(d => map.has(d) ? map.get(d) : null),
        borderColor: color,
        backgroundColor: color,
        pointRadius: 4,
        tension: 0.2,
        spanGaps: true,
      };
    });

    const chart = new Chart(canvas.getContext('2d'), {
      type: 'line',
      data: { labels: labelDisplay, datasets },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        scales: {
          x: { ticks: { color: '#94a3b8' }, grid: { color: '#334155' } },
          y: {
            ticks: {
              color: '#94a3b8',
              callback: v => v.toLocaleString('en-US') + ' EGP',
            },
            grid: { color: '#334155' },
            beginAtZero: false,
          },
        },
        plugins: {
          legend: { labels: { color: '#e2e8f0' } },
          tooltip: {
            callbacks: {
              label: ctx => `${ctx.dataset.label}: ${ctx.parsed.y.toFixed(2)} EGP`,
            },
          },
        },
      },
    });
    _itemCharts.set(id, chart);
  };
})();

// ---------- Places ----------

async function loadPlaces() {
  const btn = $('refresh-btn');
  btn.classList.add('spinning');
  $('places-table-wrap').innerHTML = '<div class="muted small" style="padding:24px 0;text-align:center;">Loading…</div>';
  try {
    const data = await fetchJSON('/api/places');
    renderPlacesTable(data.places || []);
  } catch (e) {
    if (e.status === 401 || e.status === 403) { show('login-screen'); mountTelegramWidget(); return; }
    $('places-table-wrap').innerHTML = `<div class="muted small">Error: ${escapeHtml(e.message || 'unknown')}</div>`;
  } finally {
    btn.classList.remove('spinning');
  }
}

function renderPlacesTable(places) {
  $('places-meta').textContent = `${places.length} place${places.length === 1 ? '' : 's'}`;
  const wrap = $('places-table-wrap');
  if (places.length === 0) {
    wrap.innerHTML = '<div class="muted small" style="padding:24px 0;text-align:center;">No places yet. Add some via the bot.</div>';
    return;
  }
  const trs = places.map(p => `
    <tr data-id="${p.id}" onclick="togglePlaceDetail(${p.id})">
      <td>${escapeHtml(placeLabel(p))}</td>
      <td class="hide-mobile">${p.tx_count || 0}</td>
      <td class="hide-mobile">${p.item_count || 0}</td>
      <td class="col-amount">${fmtAmount(p.total_spent_cents)}</td>
      <td class="hide-mobile col-date">${p.last_used ? fmtDateRelative(p.last_used) : '—'}</td>
    </tr>
    <tr class="detail-row hidden" id="place-detail-${p.id}">
      <td colspan="5"><div id="place-detail-body-${p.id}" class="detail-inner-block">
        <div class="muted small">Loading…</div>
      </div></td>
    </tr>
  `).join('');

  wrap.innerHTML = `
    <table class="tx-table">
      <thead>
        <tr>
          <th>Place</th>
          <th class="hide-mobile">Transactions</th>
          <th class="hide-mobile">Items</th>
          <th class="col-amount">Total spent</th>
          <th class="hide-mobile col-date">Last visit</th>
        </tr>
      </thead>
      <tbody>${trs}</tbody>
    </table>
  `;
}

async function togglePlaceDetail(id) {
  const row = $(`place-detail-${id}`);
  if (!row) return;
  const wasHidden = row.classList.contains('hidden');
  row.classList.toggle('hidden');
  if (wasHidden) {
    await populatePlaceDetail(id);
  }
}

async function populatePlaceDetail(id) {
  const body = $(`place-detail-body-${id}`);
  body.innerHTML = '<div class="muted small">Loading…</div>';
  let data;
  try {
    data = await fetchJSON(`/api/places/${id}`);
  } catch (e) {
    body.innerHTML = `<div class="muted small">Failed to load: ${escapeHtml(e.message)}</div>`;
    return;
  }
  const { summary, top_items, recent } = data;

  const summaryHtml = `
    <div class="entity-summary">
      <div class="kv-tile"><span>Total spent</span><strong>${fmtAmount(summary.total_spent_cents)}</strong></div>
      <div class="kv-tile"><span>Transactions</span><strong>${summary.tx_count}</strong></div>
      <div class="kv-tile"><span>First visit</span><strong>${summary.first_used ? fmtDateRelative(summary.first_used) : '—'}</strong></div>
      <div class="kv-tile"><span>Last visit</span><strong>${summary.last_used ? fmtDateRelative(summary.last_used) : '—'}</strong></div>
    </div>
  `;

  const topItemsHtml = top_items.length === 0 ? '' : `
    <h4 class="detail-section-title">Top items bought here</h4>
    <table class="tx-table compact">
      <thead>
        <tr>
          <th>Item</th>
          <th class="hide-mobile">Times bought</th>
          <th class="col-amount">Last price</th>
          <th class="col-amount">Total spent</th>
        </tr>
      </thead>
      <tbody>
        ${top_items.map(it => `
          <tr>
            <td>${escapeHtml(itemLabel(it))}</td>
            <td class="hide-mobile">${it.tx_count}</td>
            <td class="col-amount">${fmtAmount(it.last_price_cents)}</td>
            <td class="col-amount">${fmtAmount(it.total_spent_cents)}</td>
          </tr>
        `).join('')}
      </tbody>
    </table>
  `;

  const recentHtml = recent.length === 0 ? '' : `
    <h4 class="detail-section-title">Recent transactions</h4>
    <div class="tx-list">
      ${recent.map(t => {
        const { sign, cls } = txSign(t.type);
        const cat = txCategoryName(t);
        const icon = txIcon(t);
        const parts = [];
        if (t.item_name) {
          let n = t.item_name; if (t.item_size) n += ` (${t.item_size})`; parts.push(n);
        }
        if (t.note) parts.push(`<span class="tx-note">${escapeHtml(t.note)}</span>`);
        parts.push(fmtDateRelative(t.occurred_at));
        return `<div class="tx-row">
          <div class="tx-icon">${icon}</div>
          <div class="tx-mid">
            <div class="tx-line1">${escapeHtml(cat)}</div>
            <div class="tx-line2">${parts.join(' · ')}</div>
          </div>
          <div class="tx-amount ${cls}">${sign}${fmtAmount(t.amount_cents).replace('-', '')}</div>
        </div>`;
      }).join('')}
    </div>
  `;

  body.innerHTML = summaryHtml + topItemsHtml + recentHtml;
}

// ---------- Init ----------

async function init() {
  try { CONFIG = await fetchJSON('/api/config'); }
  catch (_) { CONFIG = { bot_username: 'Money_trackeer_bot' }; }

  try {
    ME = await fetchJSON('/api/me');
    renderHeader(ME);
    show('app');
    onHashChange();
    window.addEventListener('hashchange', () => {
      _appliedHashOnce = false;
      onHashChange();
    });
  } catch (e) {
    if (e.status === 401 || e.status === 403) {
      show('login-screen'); mountTelegramWidget();
    } else {
      alert('Error loading: ' + (e.message || 'unknown'));
      show('login-screen'); mountTelegramWidget();
    }
  }
}

window.onTelegramAuth = onTelegramAuth;
window.logout = logout;
window.refreshCurrent = refreshCurrent;
window.applyFilters = applyFilters;
window.clearFilters = clearFilters;
window.gotoPage = gotoPage;
window.toggleTxDetail = toggleTxDetail;
window.toggleItemDetail = toggleItemDetail;
window.togglePlaceDetail = togglePlaceDetail;
window.addEventListener('DOMContentLoaded', init);
