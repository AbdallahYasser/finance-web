// finance-web W4 — login + dashboard + transactions (CRUD) + items + places.

let CONFIG = null;
let ME = null;
let LOOKUPS = null;

const TYPE_ICONS = {
  cash: '💵', bank: '🏦', e_wallet: '📱', asset_gold: '🥇',
};

const CHART_PALETTE = [
  '#38bdf8', '#22c55e', '#f59e0b', '#ef4444',
  '#a78bfa', '#ec4899', '#14b8a6', '#84cc16',
];

// ---------- i18n (W11) ----------

const I18N = {
  en: {
    'nav.dashboard':    'Dashboard',
    'nav.transactions': 'Transactions',
    'nav.wallets':      'Wallets',
    'nav.items':        'Items',
    'nav.places':       'Places',
    'action.add':       '+ Add',
    'action.logout':    'Logout',
    'action.cancel':    'Cancel',
    'action.save':      'Save',
    'action.new_wallet':'+ New wallet',
    'action.edit':      '✏️ Edit',
    'action.delete':    '🗑 Delete',
    'action.restore':   '♻ Restore',
    'page.places.title':'Places',
    'page.wallets.title':'Wallets',
    'filter.show_deleted':'Show deleted',
    'filter.page_size': 'Page size',
  },
  ar: {
    'nav.dashboard':    'الرئيسية',
    'nav.transactions': 'العمليات',
    'nav.wallets':      'المحافظ',
    'nav.items':        'الأصناف',
    'nav.places':       'الأماكن',
    'action.add':       '+ إضافة',
    'action.logout':    'خروج',
    'action.cancel':    'إلغاء',
    'action.save':      'حفظ',
    'action.new_wallet':'+ محفظة جديدة',
    'action.edit':      '✏️ تعديل',
    'action.delete':    '🗑 حذف',
    'action.restore':   '♻ استرجاع',
    'page.places.title':'الأماكن',
    'page.wallets.title':'المحافظ',
    'filter.show_deleted':'إظهار المحذوف',
    'filter.page_size': 'حجم الصفحة',
  },
};

let CURRENT_LANG = 'en';

function t(key) {
  return (I18N[CURRENT_LANG] && I18N[CURRENT_LANG][key]) || (I18N.en && I18N.en[key]) || key;
}

function applyI18n() {
  document.querySelectorAll('[data-i18n]').forEach(el => {
    const key = el.getAttribute('data-i18n');
    el.textContent = t(key);
  });
  document.documentElement.lang = CURRENT_LANG;
  document.documentElement.dir = (CURRENT_LANG === 'ar') ? 'rtl' : 'ltr';
  const pill = document.getElementById('lang-btn');
  if (pill) pill.textContent = (CURRENT_LANG === 'ar') ? 'EN' : 'عربي';
}

function setLang(code) {
  if (!I18N[code]) code = 'en';
  CURRENT_LANG = code;
  applyI18n();
}

async function toggleLang() {
  const next = (CURRENT_LANG === 'ar') ? 'en' : 'ar';
  try {
    await fetchJSON('/api/me/language', {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ language: next }),
    });
    setLang(next);
  } catch (e) {
    alert('Could not change language: ' + (e.message || ''));
  }
}

// ---------- Generic helpers ----------

function $(id) { return document.getElementById(id); }
function show(id) {
  ['login-screen', 'app'].forEach(s => $(s).classList.add('hidden'));
  $(id).classList.remove('hidden');
}

async function fetchJSON(url, opts) {
  const res = await fetch(url, opts);
  let body = null;
  try { body = await res.json(); } catch (_) {}
  if (!res.ok) {
    const err = new Error((body && body.detail) || `HTTP ${res.status}`);
    err.status = res.status;
    err.body = body;
    throw err;
  }
  return body;
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

// ---------- Toasts ----------

function toast(message, type = 'info') {
  const root = $('toasts');
  const el = document.createElement('div');
  el.className = `toast toast-${type}`;
  el.innerHTML = `<button class="toast-close">×</button>${escapeHtml(message)}`;
  el.querySelector('.toast-close').onclick = () => el.remove();
  root.appendChild(el);
  setTimeout(() => el.remove(), 4500);
}

// ---------- Tolerant amount parser (mirror of bot's parse_amount) ----------

const AR_DIGITS = /[٠-٩۰-۹]/g;
const AR_DIGIT_MAP = { '٠':'0','١':'1','٢':'2','٣':'3','٤':'4','٥':'5','٦':'6','٧':'7','٨':'8','٩':'9',
                       '۰':'0','۱':'1','۲':'2','۳':'3','۴':'4','۵':'5','۶':'6','۷':'7','۸':'8','۹':'9' };
const CURRENCY_SUFFIX = /\s*(EGP|LE|pounds?|جنيه|ج\.م|ج)\s*$/i;
const SPACE_THOU = /^\d{1,3}( \d{3})+(\.\d+)?$/;
const PATTERNS = [
  [/^\d+$/, 'int'],
  [/^\d+\.\d+$/, 'dot'],
  [/^\d+,\d{1,2}$/, 'comma'],
  [/^\d{1,3}(,\d{3})+(\.\d+)?$/, 'thou'],
];

function parseAmountToCents(text) {
  if (text == null) throw new Error('empty amount');
  let s = text.normalize('NFKC').trim();
  s = s.replace('٫', '.').replace('٬', '').replace('،', ',');
  s = s.replace(AR_DIGITS, ch => AR_DIGIT_MAP[ch] || ch);
  if (s.startsWith('+')) s = s.slice(1).trimStart();
  s = s.replace(CURRENCY_SUFFIX, '').trim();
  if (SPACE_THOU.test(s)) s = s.replace(/ /g, '');
  if (!s) throw new Error('empty amount');

  for (const [re, kind] of PATTERNS) {
    if (!re.test(s)) continue;
    if (kind === 'int') return parseInt(s, 10) * 100;
    if (kind === 'dot') {
      const [whole, frac] = s.split('.');
      return parseInt(whole, 10) * 100 + parseInt(frac.slice(0, 2).padEnd(2, '0'), 10);
    }
    if (kind === 'comma') {
      const [whole, frac] = s.split(',');
      return parseInt(whole, 10) * 100 + parseInt(frac.slice(0, 2).padEnd(2, '0'), 10);
    }
    if (kind === 'thou') {
      const s2 = s.replace(/,/g, '');
      if (s2.includes('.')) {
        const [whole, frac] = s2.split('.');
        return parseInt(whole, 10) * 100 + parseInt(frac.slice(0, 2).padEnd(2, '0'), 10);
      }
      return parseInt(s2, 10) * 100;
    }
  }
  throw new Error(`could not parse amount: ${text}`);
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
const ROUTES = ['dashboard', 'transactions', 'wallets', 'items', 'places'];

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
  if (currentRoute === 'wallets')      return loadWalletsPage();
  if (currentRoute === 'items')        return loadItems();
  if (currentRoute === 'places')       return loadPlaces();
}

// ---------- Dashboard ----------

function renderHeader(me) { $('user-name').textContent = `User ${me.user_id}`; }

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
    toast('Failed to load dashboard: ' + (e.message || 'unknown'), 'error');
  } finally {
    btn.classList.remove('spinning');
  }
}

// ---------- Transactions ----------

let TX_STATE = { page: 1, page_size: 50 };

async function ensureLookups(force = false) {
  if (LOOKUPS && !force) return LOOKUPS;
  LOOKUPS = await fetchJSON('/api/lookups');
  populateFilterDropdowns();
  return LOOKUPS;
}

function populateFilterDropdowns() {
  const wsel = $('f-wallet');
  wsel.innerHTML = '<option value="">— Any —</option>' +
    (LOOKUPS.wallets || []).map(w => `<option value="${w.id}">${escapeHtml(w.name_en || w.name_ar || `Wallet ${w.id}`)}</option>`).join('');

  const csel = $('f-category');
  csel.innerHTML = renderCategoryOptions('— Any —');

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

function renderCategoryOptions(emptyLabel) {
  const cats = (LOOKUPS && LOOKUPS.categories) || [];
  const parents = cats.filter(c => c.parent_id == null);
  const childrenByParent = {};
  cats.filter(c => c.parent_id != null).forEach(c => {
    (childrenByParent[c.parent_id] = childrenByParent[c.parent_id] || []).push(c);
  });
  let opts = `<option value="">${escapeHtml(emptyLabel)}</option>`;
  for (const p of parents) {
    opts += `<option value="${p.id}">${p.icon || '•'} ${escapeHtml(p.name_en || p.name_ar)}</option>`;
    for (const ch of (childrenByParent[p.id] || [])) {
      opts += `<option value="${ch.id}">  ↳ ${ch.icon || '·'} ${escapeHtml(ch.name_en || ch.name_ar)}</option>`;
    }
  }
  return opts;
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
    include_deleted: $('f-show-deleted').checked ? 'true' : '',
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
  delete visible.page_size; delete visible.page;
  const q = buildQuery(visible);
  const newHash = q ? `#transactions?${q}` : '#transactions';
  if (location.hash !== newHash) history.replaceState(null, '', newHash);
}

function applyFilters() { TX_STATE.page = 1; loadTransactions(); }

function clearFilters() {
  ['f-date-from', 'f-date-to', 'f-type', 'f-wallet',
   'f-category', 'f-place', 'f-item', 'f-q'].forEach(id => { $(id).value = ''; });
  $('f-sort').value = 'date_desc';
  $('f-page-size').value = '50';
  $('f-show-deleted').checked = false;
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
    const isDeleted = !!t.deleted_at;
    let walletCol = '';
    if (t.type === 'transfer') {
      walletCol = `${escapeHtml(t.source_wallet_name || '?')} → ${escapeHtml(t.dest_wallet_name || '?')}`;
    } else if (t.type === 'spend') {
      walletCol = escapeHtml(t.source_wallet_name || '?');
    } else {
      walletCol = escapeHtml(t.dest_wallet_name || '?');
    }

    const restoreBtn = isDeleted
      ? `<button class="btn-primary" onclick="event.stopPropagation(); restoreTx(${t.id})">♻ Restore</button>`
      : '';
    const editDeleteBtns = isDeleted ? '' : `
      <button onclick="event.stopPropagation(); openTxForm(${t.id})">✏️ Edit</button>
      <button class="btn-danger" onclick="event.stopPropagation(); confirmDeleteTx(${t.id})">🗑 Delete</button>
    `;

    return `
      <tr data-id="${t.id}" class="${isDeleted ? 'tx-row-deleted-row' : ''}" onclick="toggleTxDetail(${t.id})">
        <td class="col-date">${fmtDateRelative(t.occurred_at)}</td>
        <td class="col-cat"><span class="icon">${icon}</span>${escapeHtml(cat)}</td>
        <td class="hide-mobile">${escapeHtml(itemPlace)}</td>
        <td class="hide-mobile">${walletCol}</td>
        <td class="col-amount ${cls}">${sign}${fmtAmount(t.amount_cents).replace('-', '')}</td>
      </tr>
      <tr class="detail-row hidden" id="detail-${t.id}">
        <td colspan="5">
          <div class="detail-inner">
            <div class="kv-row"><span>Type</span><span>${t.type}${isDeleted ? ' (deleted)' : ''}</span></div>
            <div class="kv-row"><span>Date</span><span>${fmtDateAbsolute(t.occurred_at)}</span></div>
            ${t.item_name ? `<div class="kv-row"><span>Item</span><span>${escapeHtml(t.item_name)}${t.item_size ? ` (${escapeHtml(t.item_size)})` : ''}</span></div>` : ''}
            ${t.place_branch ? `<div class="kv-row"><span>Place</span><span>${escapeHtml(t.place_branch)}${t.place_chain && t.place_chain !== t.place_branch ? ` · ${escapeHtml(t.place_chain)}` : ''}</span></div>` : ''}
            ${t.source_wallet_name ? `<div class="kv-row"><span>From wallet</span><span>${escapeHtml(t.source_wallet_name)}</span></div>` : ''}
            ${t.dest_wallet_name ? `<div class="kv-row"><span>To wallet</span><span>${escapeHtml(t.dest_wallet_name)}</span></div>` : ''}
            ${t.note ? `<div class="kv-row"><span>Note</span><span>${escapeHtml(t.note)}</span></div>` : ''}
            <div class="kv-row"><span>ID</span><span>#${t.id}</span></div>
          </div>
          <div class="detail-actions">${restoreBtn}${editDeleteBtns}</div>
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

// ---------- Transaction form (W4) ----------

let TX_FORM_MODE = 'create'; // 'create' | 'edit'
let TX_FORM_EDITING = null;  // tx row when editing

async function openTxForm(txId = null) {
  await ensureLookups();
  populateTxFormDropdowns();

  if (txId == null) {
    TX_FORM_MODE = 'create';
    TX_FORM_EDITING = null;
    $('tx-modal-title').textContent = 'New transaction';
    $('tx-id').value = '';
    $('tx-refund-of').value = '';
    document.querySelector('input[name="tx-type"][value="spend"]').checked = true;
    $('tx-amount').value = '';
    $('tx-date').value = new Date().toISOString().slice(0, 10);
    $('tx-from-wallet').value = '';
    $('tx-to-wallet').value = '';
    $('tx-category').value = '';
    $('tx-place').value = '';
    $('tx-item').value = '';
    $('tx-note').value = '';
  } else {
    TX_FORM_MODE = 'edit';
    let tx;
    try {
      const filters = readFilters();
      filters.include_deleted = 'true';
      const data = await fetchJSON('/api/transactions?' + buildQuery(filters));
      tx = (data.rows || []).find(r => r.id === txId);
      if (!tx) throw new Error('Transaction not found');
    } catch (e) {
      toast('Could not load transaction: ' + (e.message || ''), 'error');
      return;
    }
    TX_FORM_EDITING = tx;
    $('tx-modal-title').textContent = `Edit transaction #${txId}`;
    $('tx-id').value = txId;
    $('tx-refund-of').value = tx.refund_of_id || '';
    const radio = document.querySelector(`input[name="tx-type"][value="${tx.type}"]`);
    if (radio) radio.checked = true;
    else document.querySelector('input[name="tx-type"][value="spend"]').checked = true;
    $('tx-amount').value = (tx.amount_cents / 100).toFixed(2);
    $('tx-date').value = (tx.occurred_at || '').slice(0, 10);
    $('tx-from-wallet').value = tx.source_wallet_id || '';
    $('tx-to-wallet').value = tx.dest_wallet_id || '';
    $('tx-category').value = tx.category_id || '';
    $('tx-place').value = tx.place_id || '';
    $('tx-item').value = tx.item_id || '';
    $('tx-note').value = tx.note || '';
  }

  $('tx-amount-error').textContent = '';
  $('tx-form-error').textContent = '';
  cancelInlinePlace();
  cancelInlineItem();
  onTypeChange();
  $('tx-modal').classList.remove('hidden');
  setTimeout(() => $('tx-amount').focus(), 50);
}

function closeTxForm() {
  $('tx-modal').classList.add('hidden');
}

function onTxModalBgClick(e) {
  if (e.target.id === 'tx-modal') closeTxForm();
}

function populateTxFormDropdowns() {
  const wallets = (LOOKUPS && LOOKUPS.wallets) || [];
  const walletOpts = '<option value="">— Pick wallet —</option>' +
    wallets.map(w => {
      const icon = TYPE_ICONS[w.type] || '•';
      const name = w.name_en || w.name_ar || `Wallet ${w.id}`;
      return `<option value="${w.id}">${icon} ${escapeHtml(name)}</option>`;
    }).join('');
  $('tx-from-wallet').innerHTML = walletOpts;
  $('tx-to-wallet').innerHTML = walletOpts;

  $('tx-category').innerHTML = renderCategoryOptions('— Pick category —');

  const places = (LOOKUPS && LOOKUPS.places) || [];
  $('tx-place').innerHTML = '<option value="">— None —</option>' +
    places.map(p => {
      let label = p.branch_name || `Place ${p.id}`;
      if (p.chain_name && p.chain_name !== p.branch_name) label += ` · ${p.chain_name}`;
      return `<option value="${p.id}">${escapeHtml(label)}</option>`;
    }).join('') +
    '<option value="__create__">➕ New place…</option>';

  const items = (LOOKUPS && LOOKUPS.items) || [];
  $('tx-item').innerHTML = '<option value="">— None —</option>' +
    items.map(it => {
      let label = it.canonical_name_en || it.canonical_name_ar || `Item ${it.id}`;
      if (it.size) label += ` (${it.size})`;
      return `<option value="${it.id}">${escapeHtml(label)}</option>`;
    }).join('') +
    '<option value="__create__">➕ New item…</option>';
}

function selectedTxType() {
  const r = document.querySelector('input[name="tx-type"]:checked');
  return r ? r.value : 'spend';
}

function onTypeChange() {
  const t = selectedTxType();
  // Show/hide fields per type:
  //   spend    → from + category + place + item + note
  //   income   → to   + category +                  note
  //   transfer → from + to       (no category, place, item)
  $('tx-from-wallet-field').classList.toggle('hidden', t === 'income');
  $('tx-to-wallet-field').classList.toggle('hidden', t === 'spend');
  $('tx-category-field').classList.toggle('hidden', t === 'transfer');
  $('tx-place-item-fields').classList.toggle('hidden', t === 'transfer' || t === 'income');
}

function onPlaceChange() {
  if ($('tx-place').value === '__create__') {
    $('tx-place').value = '';
    $('tx-new-place-panel').classList.remove('hidden');
    setTimeout(() => $('tx-new-place-branch').focus(), 50);
  }
}

function cancelInlinePlace() {
  $('tx-new-place-panel').classList.add('hidden');
  $('tx-new-place-branch').value = '';
  $('tx-new-place-chain').value = '';
}

async function createInlinePlace() {
  const branch = $('tx-new-place-branch').value.trim();
  const chain = $('tx-new-place-chain').value.trim();
  if (!branch) {
    toast('Branch name is required', 'error');
    return;
  }
  try {
    const place = await fetchJSON('/api/places', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ branch_name: branch, chain_name: chain || null }),
    });
    await ensureLookups(true);
    populateTxFormDropdowns();
    $('tx-place').value = place.id;
    cancelInlinePlace();
    toast('Place created', 'success');
  } catch (e) {
    toast('Failed to create place: ' + (e.message || ''), 'error');
  }
}

function onItemChange() {
  if ($('tx-item').value === '__create__') {
    $('tx-item').value = '';
    $('tx-new-item-panel').classList.remove('hidden');
    setTimeout(() => $('tx-new-item-name').focus(), 50);
  }
}

function cancelInlineItem() {
  $('tx-new-item-panel').classList.add('hidden');
  $('tx-new-item-name').value = '';
  $('tx-new-item-size').value = '';
  $('tx-new-item-unit').value = '';
}

async function createInlineItem() {
  const name = $('tx-new-item-name').value.trim();
  const size = $('tx-new-item-size').value.trim();
  const unit = $('tx-new-item-unit').value.trim();
  if (!name) {
    toast('Item name is required', 'error');
    return;
  }
  const defaultCat = parseInt($('tx-category').value, 10) || null;
  try {
    const item = await fetchJSON('/api/items', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        canonical_name_en: name,
        size: size || null, unit: unit || null,
        default_category_id: defaultCat,
      }),
    });
    await ensureLookups(true);
    populateTxFormDropdowns();
    $('tx-item').value = item.id;
    cancelInlineItem();
    toast('Item created', 'success');
  } catch (e) {
    toast('Failed to create item: ' + (e.message || ''), 'error');
  }
}

async function saveTxForm() {
  $('tx-amount-error').textContent = '';
  $('tx-form-error').textContent = '';
  const saveBtn = $('tx-form-save');
  saveBtn.disabled = true;

  const type = selectedTxType();
  let amount;
  try {
    amount = parseAmountToCents($('tx-amount').value);
    if (amount <= 0) throw new Error('amount must be > 0');
  } catch (e) {
    $('tx-amount-error').textContent = e.message || 'invalid amount';
    saveBtn.disabled = false;
    return;
  }

  const dateStr = $('tx-date').value;
  const occurredAt = dateStr ? `${dateStr}T12:00:00Z` : null;

  const fromW = $('tx-from-wallet').value || null;
  const toW   = $('tx-to-wallet').value   || null;
  const cat   = $('tx-category').value    || null;
  const place = $('tx-place').value       || null;
  const item  = $('tx-item').value        || null;
  const note  = $('tx-note').value.trim() || null;
  const refundOf = $('tx-refund-of').value || null;

  const body = {
    type,
    amount_cents: amount,
    occurred_at: occurredAt,
    note,
  };

  if (type === 'spend') {
    body.source_wallet_id = fromW ? +fromW : null;
    body.category_id = cat ? +cat : null;
    body.place_id = place ? +place : null;
    body.item_id = item ? +item : null;
  } else if (type === 'income') {
    body.dest_wallet_id = toW ? +toW : null;
    body.category_id = cat ? +cat : null;
  } else if (type === 'transfer') {
    body.source_wallet_id = fromW ? +fromW : null;
    body.dest_wallet_id = toW ? +toW : null;
    if (body.source_wallet_id && body.dest_wallet_id &&
        body.source_wallet_id === body.dest_wallet_id) {
      $('tx-form-error').textContent = 'Source and destination wallets must differ.';
      saveBtn.disabled = false;
      return;
    }
  } else if (type === 'refund') {
    body.dest_wallet_id = toW ? +toW : null;
    body.refund_of_id = refundOf ? +refundOf : null;
    body.category_id = cat ? +cat : null;
    body.item_id = item ? +item : null;
    body.place_id = place ? +place : null;
  }

  try {
    if (TX_FORM_MODE === 'create') {
      await fetchJSON('/api/transactions', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
      });
      toast('Transaction added', 'success');
    } else {
      const id = parseInt($('tx-id').value, 10);
      await fetchJSON(`/api/transactions/${id}`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
      });
      toast('Transaction updated', 'success');
    }
    closeTxForm();
    await ensureLookups(true);
    refreshCurrent();
  } catch (e) {
    $('tx-form-error').textContent = e.message || 'save failed';
  } finally {
    saveBtn.disabled = false;
  }
}

// ---------- Confirm modal ----------

let _pendingConfirm = null;

function openConfirm(title, message, okLabel = 'Confirm', okClass = 'btn-danger') {
  return new Promise(resolve => {
    $('confirm-title').textContent = title;
    $('confirm-message').textContent = message;
    const btn = $('confirm-ok-btn');
    btn.textContent = okLabel;
    btn.className = okClass;
    btn.onclick = () => { closeConfirm(); resolve(true); };
    _pendingConfirm = resolve;
    $('confirm-modal').classList.remove('hidden');
  });
}

function closeConfirm() {
  $('confirm-modal').classList.add('hidden');
  if (_pendingConfirm) { _pendingConfirm(false); _pendingConfirm = null; }
}

// ---------- Delete / Restore ----------

async function confirmDeleteTx(id) {
  const ok = await openConfirm(
    'Delete transaction?',
    `This soft-deletes transaction #${id}. You can restore it from the "Show deleted" filter.`,
    'Delete',
  );
  if (!ok) return;
  try {
    await fetchJSON(`/api/transactions/${id}`, { method: 'DELETE' });
    toast('Transaction deleted', 'success');
    refreshCurrent();
  } catch (e) {
    toast('Delete failed: ' + (e.message || ''), 'error');
  }
}

async function restoreTx(id) {
  try {
    await fetchJSON(`/api/transactions/${id}/restore`, { method: 'POST' });
    toast('Transaction restored', 'success');
    refreshCurrent();
  } catch (e) {
    toast('Restore failed: ' + (e.message || ''), 'error');
  }
}

// ---------- Items / Places (W3) ----------

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
    wrap.innerHTML = '<div class="muted small" style="padding:24px 0;text-align:center;">No items yet.</div>';
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
  if (wasHidden) await populateItemDetail(id);
}

async function populateItemDetail(id) {
  const body = $(`item-detail-body-${id}`);
  body.innerHTML = '<div class="muted small">Loading…</div>';
  let data;
  try { data = await fetchJSON(`/api/items/${id}`); }
  catch (e) { body.innerHTML = `<div class="muted small">Failed: ${escapeHtml(e.message)}</div>`; return; }
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
      <thead><tr><th>Place</th><th>Observations</th><th class="col-amount">Min</th><th class="col-amount">Last</th><th class="col-amount">Max</th></tr></thead>
      <tbody>${places.map(p => `
          <tr>
            <td>${escapeHtml(placeLabel(p))}</td>
            <td>${p.observation_count}</td>
            <td class="col-amount">${fmtAmount(p.min_cents)}</td>
            <td class="col-amount">${fmtAmount(p.last_cents)}</td>
            <td class="col-amount">${fmtAmount(p.max_cents)}</td>
          </tr>`).join('')}</tbody>
    </table>
  `;

  const chartHtml = places.length > 0 ? `
    <h4 class="detail-section-title">Price chart</h4>
    <div class="chart-wrap"><canvas id="item-chart-${id}"></canvas></div>
  ` : '<div class="muted small" style="margin-top:12px;">No price observations yet.</div>';

  const aliasesHtml = `
    <h4 class="detail-section-title">Aliases</h4>
    <div class="aliases-wrap" id="item-aliases-${id}">
      <div id="alias-chips-${id}" class="alias-chips"><span class="muted small">Loading…</span></div>
      <div class="alias-input-row">
        <input type="text" id="alias-input-${id}" placeholder="Add alias…" maxlength="80"
               onkeydown="if(event.key==='Enter'){event.preventDefault();addAlias(${id});}" />
        <button class="btn-primary" onclick="addAlias(${id})">Add</button>
      </div>
    </div>
  `;

  const actionsHtml = `
    <div class="detail-actions">
      <button onclick="openItemForm(${id})">✏️ Edit</button>
      <button class="btn-danger" onclick="confirmDeleteItem(${id})">🗑 Delete</button>
    </div>
  `;

  body.innerHTML = summaryHtml + chartHtml + placesHtml + aliasesHtml + actionsHtml;
  if (places.length > 0) drawItemChart(id, places);
  loadAliasChips(id);
}

function drawItemChart(id, places) {
  const canvas = $(`item-chart-${id}`);
  if (!canvas) return;
  if (_itemCharts.has(id)) { _itemCharts.get(id).destroy(); _itemCharts.delete(id); }
  if (typeof Chart === 'undefined') {
    canvas.parentElement.innerHTML = '<div class="muted small">Chart library unavailable.</div>';
    return;
  }
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
          ticks: { color: '#94a3b8', callback: v => v.toLocaleString('en-US') + ' EGP' },
          grid: { color: '#334155' },
          beginAtZero: false,
        },
      },
      plugins: {
        legend: { labels: { color: '#e2e8f0' } },
        tooltip: { callbacks: { label: ctx => `${ctx.dataset.label}: ${ctx.parsed.y.toFixed(2)} EGP` } },
      },
    },
  });
  _itemCharts.set(id, chart);
}

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
    wrap.innerHTML = '<div class="muted small" style="padding:24px 0;text-align:center;">No places yet.</div>';
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
  if (wasHidden) await populatePlaceDetail(id);
}

async function populatePlaceDetail(id) {
  const body = $(`place-detail-body-${id}`);
  body.innerHTML = '<div class="muted small">Loading…</div>';
  let data;
  try { data = await fetchJSON(`/api/places/${id}`); }
  catch (e) { body.innerHTML = `<div class="muted small">Failed: ${escapeHtml(e.message)}</div>`; return; }
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
      <thead><tr><th>Item</th><th class="hide-mobile">Times bought</th><th class="col-amount">Last price</th><th class="col-amount">Total spent</th></tr></thead>
      <tbody>${top_items.map(it => `
          <tr>
            <td>${escapeHtml(itemLabel(it))}</td>
            <td class="hide-mobile">${it.tx_count}</td>
            <td class="col-amount">${fmtAmount(it.last_price_cents)}</td>
            <td class="col-amount">${fmtAmount(it.total_spent_cents)}</td>
          </tr>`).join('')}</tbody>
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
          <div class="tx-mid"><div class="tx-line1">${escapeHtml(cat)}</div><div class="tx-line2">${parts.join(' · ')}</div></div>
          <div class="tx-amount ${cls}">${sign}${fmtAmount(t.amount_cents).replace('-', '')}</div>
        </div>`;
      }).join('')}
    </div>
  `;
  const placeActions = `
    <div class="detail-actions">
      <button onclick="openPlaceForm(${id})">✏️ Edit</button>
      <button class="btn-danger" onclick="confirmDeletePlace(${id})">🗑 Delete</button>
    </div>
  `;
  body.innerHTML = summaryHtml + topItemsHtml + recentHtml + placeActions;
}

// ---------- Wallets page (W5) ----------

async function loadWalletsPage() {
  const btn = $('refresh-btn');
  btn.classList.add('spinning');
  const root = $('wallets-page-list');
  root.innerHTML = '<div class="muted small" style="padding:24px 0;text-align:center;">Loading…</div>';
  try {
    const data = await fetchJSON('/api/dashboard'); // reuses wallet+balance composite
    renderWalletsPage(data.wallets || []);
  } catch (e) {
    if (e.status === 401 || e.status === 403) { show('login-screen'); mountTelegramWidget(); return; }
    root.innerHTML = `<div class="muted small">Error: ${escapeHtml(e.message || 'unknown')}</div>`;
  } finally {
    btn.classList.remove('spinning');
  }
}

function renderWalletsPage(wallets) {
  const root = $('wallets-page-list');
  if (!wallets || wallets.length === 0) {
    root.innerHTML = '<div class="muted small">No wallets yet. Tap <b>+ New wallet</b>.</div>';
    return;
  }
  root.innerHTML = wallets.map(w => {
    const icon = TYPE_ICONS[w.type] || '•';
    const name = w.name_en || w.name_ar || `Wallet ${w.id}`;
    const balCls = w.balance_cents < 0 ? 'wallet-balance negative' : 'wallet-balance';
    let meta = `${w.type}`;
    if (w.type === 'asset_gold') {
      const grams = (w.gold_grams_milligrams || 0) / 1000;
      const karat = w.karat || '?';
      const price = w.gold_price_per_gram_cents
        ? (w.gold_price_per_gram_cents / 100).toLocaleString('en-US')
        : '?';
      meta = `${karat}k · ${grams} g · ${price} EGP/g`;
    }
    return `<div class="wallet-row">
      <div class="wallet-name">
        <span class="wallet-icon">${icon}</span>
        <span>
          <div>${escapeHtml(name)}</div>
          <div class="wallet-meta">${escapeHtml(meta)}</div>
        </span>
      </div>
      <div style="display:flex;align-items:center;gap:12px;">
        <div class="${balCls}">${fmtAmount(w.balance_cents)}</div>
        <div class="wallet-actions">
          <button onclick="openWalletForm(${w.id})" title="${t('action.edit')}">✏️</button>
          <button class="btn-danger" onclick="confirmDeleteWallet(${w.id})" title="${t('action.delete')}">🗑</button>
        </div>
      </div>
    </div>`;
  }).join('');
}

let WALLET_FORM_MODE = 'create';

async function openWalletForm(walletId = null) {
  await ensureLookups();
  $('wallet-form-error').textContent = '';
  if (walletId == null) {
    WALLET_FORM_MODE = 'create';
    $('wallet-modal-title').textContent = 'New wallet';
    $('wallet-id').value = '';
    document.querySelector('input[name="wallet-type"][value="cash"]').checked = true;
    $('wallet-name-en').value = '';
    $('wallet-name-ar').value = '';
    $('wallet-initial').value = '0';
    $('wallet-karat').value = '';
    $('wallet-grams').value = '';
    $('wallet-price').value = '';
  } else {
    WALLET_FORM_MODE = 'edit';
    const w = (LOOKUPS.wallets || []).find(x => x.id === walletId);
    // Fetch full wallet data including gold fields from dashboard
    const data = await fetchJSON('/api/dashboard');
    const full = (data.wallets || []).find(x => x.id === walletId) || w || {};
    $('wallet-modal-title').textContent = `Edit ${full.name_en || full.name_ar || 'wallet'}`;
    $('wallet-id').value = walletId;
    const typeRadio = document.querySelector(`input[name="wallet-type"][value="${full.type}"]`);
    if (typeRadio) typeRadio.checked = true;
    $('wallet-name-en').value = full.name_en || '';
    $('wallet-name-ar').value = full.name_ar || '';
    // Can't directly edit initial_balance through UI in edit mode safely — show but allow
    $('wallet-initial').value = ((full.initial_balance_cents || 0) / 100).toFixed(2);
    $('wallet-karat').value = full.karat || '';
    $('wallet-grams').value = full.gold_grams_milligrams != null
      ? (full.gold_grams_milligrams / 1000).toString() : '';
    $('wallet-price').value = full.gold_price_per_gram_cents != null
      ? (full.gold_price_per_gram_cents / 100).toString() : '';
  }
  onWalletTypeChange();
  // In edit mode, disable the type radios — type isn't editable.
  document.querySelectorAll('input[name="wallet-type"]').forEach(r => {
    r.disabled = (WALLET_FORM_MODE === 'edit');
  });
  $('wallet-modal').classList.remove('hidden');
}

function closeWalletForm() { $('wallet-modal').classList.add('hidden'); }
function onWalletModalBgClick(e) {
  if (e.target.id === 'wallet-modal') closeWalletForm();
}

function onWalletTypeChange() {
  const t = document.querySelector('input[name="wallet-type"]:checked').value;
  $('wallet-gold-fields').classList.toggle('hidden', t !== 'asset_gold');
}

async function saveWalletForm() {
  const err = $('wallet-form-error');
  err.textContent = '';
  const type = document.querySelector('input[name="wallet-type"]:checked').value;
  const nameEn = $('wallet-name-en').value.trim();
  const nameAr = $('wallet-name-ar').value.trim();
  if (!nameEn && !nameAr) {
    err.textContent = 'Provide at least one name (English or Arabic).';
    return;
  }
  let initial = 0;
  try { initial = parseAmountToCents($('wallet-initial').value || '0'); }
  catch (e) { err.textContent = 'Initial balance: ' + e.message; return; }

  const body = {
    name_en: nameEn || null,
    name_ar: nameAr || null,
    initial_balance_cents: initial,
  };
  if (WALLET_FORM_MODE === 'create') body.type = type;

  if (type === 'asset_gold') {
    const karat = parseInt($('wallet-karat').value, 10);
    if (![18, 21, 24].includes(karat)) {
      err.textContent = 'Karat must be 18, 21 or 24.'; return;
    }
    body.karat = karat;
    const gramsStr = $('wallet-grams').value.trim();
    if (gramsStr) {
      const grams = parseFloat(gramsStr);
      if (isNaN(grams) || grams < 0) { err.textContent = 'Grams must be ≥ 0.'; return; }
      body.gold_grams_milligrams = Math.round(grams * 1000);
    }
    const priceStr = $('wallet-price').value.trim();
    if (priceStr) {
      try { body.gold_price_per_gram_cents = parseAmountToCents(priceStr); }
      catch (e) { err.textContent = 'Price: ' + e.message; return; }
    }
  }

  try {
    if (WALLET_FORM_MODE === 'create') {
      await fetchJSON('/api/wallets', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
      });
      toast('Wallet created', 'success');
    } else {
      const id = parseInt($('wallet-id').value, 10);
      await fetchJSON(`/api/wallets/${id}`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
      });
      toast('Wallet updated', 'success');
    }
    closeWalletForm();
    await ensureLookups(true);
    refreshCurrent();
  } catch (e) {
    err.textContent = e.message || 'save failed';
  }
}

async function confirmDeleteWallet(id) {
  const ok = await openConfirm(
    'Delete wallet?',
    'The wallet will be hidden. Existing transactions linked to it stay intact.',
    'Delete',
  );
  if (!ok) return;
  try {
    await fetchJSON(`/api/wallets/${id}`, { method: 'DELETE' });
    toast('Wallet deleted', 'success');
    await ensureLookups(true);
    refreshCurrent();
  } catch (e) {
    toast('Delete failed: ' + (e.message || ''), 'error');
  }
}

// ---------- Place edit (W5) ----------

async function openPlaceForm(placeId) {
  const p = (LOOKUPS.places || []).find(x => x.id === placeId);
  if (!p) return;
  $('place-form-error').textContent = '';
  $('place-modal-title').textContent = `Edit ${p.branch_name || 'place'}`;
  $('place-edit-id').value = placeId;
  $('place-edit-branch').value = p.branch_name || '';
  $('place-edit-chain').value = p.chain_name || '';
  $('place-modal').classList.remove('hidden');
}

function closePlaceForm() { $('place-modal').classList.add('hidden'); }
function onPlaceModalBgClick(e) {
  if (e.target.id === 'place-modal') closePlaceForm();
}

async function savePlaceForm() {
  const err = $('place-form-error');
  err.textContent = '';
  const id = parseInt($('place-edit-id').value, 10);
  const branch = $('place-edit-branch').value.trim();
  const chain = $('place-edit-chain').value.trim();
  if (!branch) { err.textContent = 'Branch name is required.'; return; }
  try {
    await fetchJSON(`/api/places/${id}`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ branch_name: branch, chain_name: chain || null }),
    });
    toast('Place updated', 'success');
    closePlaceForm();
    await ensureLookups(true);
    refreshCurrent();
  } catch (e) {
    err.textContent = e.message || 'save failed';
  }
}

async function confirmDeletePlace(id) {
  const ok = await openConfirm(
    'Delete place?',
    'The place will be hidden. Existing transactions linked to it stay intact.',
    'Delete',
  );
  if (!ok) return;
  try {
    await fetchJSON(`/api/places/${id}`, { method: 'DELETE' });
    toast('Place deleted', 'success');
    await ensureLookups(true);
    refreshCurrent();
  } catch (e) {
    toast('Delete failed: ' + (e.message || ''), 'error');
  }
}

// ---------- Item edit + aliases (W5) ----------

async function openItemForm(itemId) {
  await ensureLookups();
  const it = (LOOKUPS.items || []).find(x => x.id === itemId);
  if (!it) return;
  $('item-form-error').textContent = '';
  $('item-modal-title').textContent = `Edit ${it.canonical_name_en || it.canonical_name_ar || 'item'}`;
  $('item-edit-id').value = itemId;
  $('item-edit-name-en').value = it.canonical_name_en || '';
  $('item-edit-name-ar').value = it.canonical_name_ar || '';
  $('item-edit-size').value = it.size || '';
  $('item-edit-unit').value = it.unit || '';

  // Populate categories dropdown
  const cats = (LOOKUPS.categories || []);
  let opts = '<option value="">— None —</option>';
  const parents = cats.filter(c => c.parent_id == null);
  const childrenByParent = {};
  cats.filter(c => c.parent_id != null).forEach(c => {
    (childrenByParent[c.parent_id] = childrenByParent[c.parent_id] || []).push(c);
  });
  for (const p of parents) {
    opts += `<option value="${p.id}">${p.icon || '•'} ${escapeHtml(p.name_en || p.name_ar)}</option>`;
    for (const ch of (childrenByParent[p.id] || [])) {
      opts += `<option value="${ch.id}">  ↳ ${ch.icon || '·'} ${escapeHtml(ch.name_en || ch.name_ar)}</option>`;
    }
  }
  $('item-edit-category').innerHTML = opts;
  // Note: we don't store default_category_id in lookups currently — leave default

  $('item-modal').classList.remove('hidden');
}

function closeItemForm() { $('item-modal').classList.add('hidden'); }
function onItemModalBgClick(e) {
  if (e.target.id === 'item-modal') closeItemForm();
}

async function saveItemForm() {
  const err = $('item-form-error');
  err.textContent = '';
  const id = parseInt($('item-edit-id').value, 10);
  const nameEn = $('item-edit-name-en').value.trim();
  const nameAr = $('item-edit-name-ar').value.trim();
  if (!nameEn && !nameAr) {
    err.textContent = 'Provide at least one name.'; return;
  }
  const body = {
    canonical_name_en: nameEn || null,
    canonical_name_ar: nameAr || null,
    size: $('item-edit-size').value.trim() || null,
    unit: $('item-edit-unit').value.trim() || null,
    default_category_id: parseInt($('item-edit-category').value, 10) || null,
  };
  try {
    await fetchJSON(`/api/items/${id}`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    });
    toast('Item updated', 'success');
    closeItemForm();
    await ensureLookups(true);
    refreshCurrent();
  } catch (e) {
    err.textContent = e.message || 'save failed';
  }
}

async function confirmDeleteItem(id) {
  const ok = await openConfirm(
    'Delete item?',
    'The item will be hidden. Price-history and existing transactions stay intact.',
    'Delete',
  );
  if (!ok) return;
  try {
    await fetchJSON(`/api/items/${id}`, { method: 'DELETE' });
    toast('Item deleted', 'success');
    await ensureLookups(true);
    refreshCurrent();
  } catch (e) {
    toast('Delete failed: ' + (e.message || ''), 'error');
  }
}

async function loadAliasChips(itemId) {
  const container = $(`item-aliases-${itemId}`);
  if (!container) return;
  try {
    const data = await fetchJSON(`/api/items/${itemId}/aliases`);
    renderAliasChips(itemId, data.aliases || []);
  } catch (e) {
    container.innerHTML = `<div class="muted small">Error: ${escapeHtml(e.message)}</div>`;
  }
}

function renderAliasChips(itemId, aliases) {
  const chipsRoot = $(`alias-chips-${itemId}`);
  if (!chipsRoot) return;
  if (aliases.length === 0) {
    chipsRoot.innerHTML = '<span class="muted small">No aliases yet.</span>';
    return;
  }
  chipsRoot.innerHTML = aliases.map(a => `
    <span class="alias-chip">
      ${escapeHtml(a.alias_text)}
      <button onclick="removeAlias(${itemId}, ${a.id})" title="Remove">×</button>
    </span>
  `).join('');
}

async function addAlias(itemId) {
  const input = $(`alias-input-${itemId}`);
  const text = input.value.trim();
  if (!text) return;
  try {
    await fetchJSON(`/api/items/${itemId}/aliases`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ alias_text: text }),
    });
    input.value = '';
    await loadAliasChips(itemId);
  } catch (e) {
    toast('Add alias failed: ' + (e.message || ''), 'error');
  }
}

async function removeAlias(itemId, aliasId) {
  try {
    await fetchJSON(`/api/aliases/${aliasId}`, { method: 'DELETE' });
    await loadAliasChips(itemId);
  } catch (e) {
    toast('Remove alias failed: ' + (e.message || ''), 'error');
  }
}

// ---------- CSV export (W12) ----------

function downloadCSV() {
  const filters = readFilters();
  // Drop pagination params for export
  delete filters.page; delete filters.page_size;
  const url = '/api/transactions/export.csv?' + buildQuery(filters);
  // Native browser download — opens the URL which has Content-Disposition attachment
  window.location.href = url;
}

// ---------- Init ----------

async function init() {
  try { CONFIG = await fetchJSON('/api/config'); }
  catch (_) { CONFIG = { bot_username: 'Money_trackeer_bot' }; }

  try {
    ME = await fetchJSON('/api/me');
    renderHeader(ME);
    setLang(ME.language || 'en');
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
window.openTxForm = openTxForm;
window.closeTxForm = closeTxForm;
window.onTxModalBgClick = onTxModalBgClick;
window.onTypeChange = onTypeChange;
window.onPlaceChange = onPlaceChange;
window.onItemChange = onItemChange;
window.cancelInlinePlace = cancelInlinePlace;
window.cancelInlineItem = cancelInlineItem;
window.createInlinePlace = createInlinePlace;
window.createInlineItem = createInlineItem;
window.saveTxForm = saveTxForm;
window.confirmDeleteTx = confirmDeleteTx;
window.restoreTx = restoreTx;
window.closeConfirm = closeConfirm;
// W5 / W11 / W12
window.toggleLang = toggleLang;
window.openWalletForm = openWalletForm;
window.closeWalletForm = closeWalletForm;
window.onWalletModalBgClick = onWalletModalBgClick;
window.onWalletTypeChange = onWalletTypeChange;
window.saveWalletForm = saveWalletForm;
window.confirmDeleteWallet = confirmDeleteWallet;
window.openPlaceForm = openPlaceForm;
window.closePlaceForm = closePlaceForm;
window.onPlaceModalBgClick = onPlaceModalBgClick;
window.savePlaceForm = savePlaceForm;
window.confirmDeletePlace = confirmDeletePlace;
window.openItemForm = openItemForm;
window.closeItemForm = closeItemForm;
window.onItemModalBgClick = onItemModalBgClick;
window.saveItemForm = saveItemForm;
window.confirmDeleteItem = confirmDeleteItem;
window.addAlias = addAlias;
window.removeAlias = removeAlias;
window.downloadCSV = downloadCSV;
window.addEventListener('DOMContentLoaded', init);
