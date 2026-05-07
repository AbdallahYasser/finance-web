// finance-web W1 — login + read-only dashboard.

let CONFIG = null;
let ME = null;

const TYPE_ICONS = {
  cash: '💵',
  bank: '🏦',
  e_wallet: '📱',
  asset_gold: '🥇',
};

// ---------- Helpers ----------

function show(id) {
  document.getElementById('login-screen').classList.add('hidden');
  document.getElementById('dashboard').classList.add('hidden');
  document.getElementById(id).classList.remove('hidden');
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
  // Accept "YYYY-MM-DDTHH:MM:SSZ" or "YYYY-MM-DD HH:MM:SS"
  const normalized = iso.replace(' ', 'T').replace(/Z?$/, 'Z');
  const dt = new Date(normalized);
  if (isNaN(dt.getTime())) return iso.slice(0, 10);

  const now = new Date();
  // Compute calendar-day delta in local tz
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
  // ISO date
  return dt.toISOString().slice(0, 10);
}

function txSign(type) {
  if (type === 'spend') return { sign: '−', cls: 'minus' };
  if (type === 'income' || type === 'refund') return { sign: '+', cls: 'plus' };
  if (type === 'transfer') return { sign: '↔', cls: 'transfer' };
  return { sign: '', cls: '' };
}

// ---------- Telegram login ----------

function mountTelegramWidget() {
  if (!CONFIG || !CONFIG.bot_username) return;
  const link = document.getElementById('bot-link');
  if (link) {
    link.textContent = '@' + CONFIG.bot_username;
    link.href = 'https://t.me/' + CONFIG.bot_username;
  }
  const container = document.getElementById('telegram-login-widget');
  container.innerHTML = '';
  const s = document.createElement('script');
  s.async = true;
  s.src = 'https://telegram.org/js/telegram-widget.js?22';
  s.setAttribute('data-telegram-login', CONFIG.bot_username);
  s.setAttribute('data-size', 'large');
  s.setAttribute('data-onauth', 'onTelegramAuth(user)');
  s.setAttribute('data-request-access', 'write');
  s.setAttribute('data-userpic', 'true');
  container.appendChild(s);
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

// ---------- Dashboard render ----------

function renderHeader(me) {
  document.getElementById('user-name').textContent = `User ${me.user_id}`;
}

function renderNetWorth(cents, walletCount) {
  document.getElementById('net-worth').textContent = fmtAmount(cents);
  const noun = walletCount === 1 ? 'wallet' : 'wallets';
  document.getElementById('net-worth-sub').textContent = `across ${walletCount} ${noun}`;
}

function renderWallets(wallets) {
  const root = document.getElementById('wallets-list');
  if (!wallets || wallets.length === 0) {
    root.innerHTML = '<div class="muted small">No wallets yet. Use the bot.</div>';
    return;
  }
  root.innerHTML = wallets.map(w => {
    const icon = TYPE_ICONS[w.type] || '•';
    const name = w.name_en || w.name_ar || `Wallet ${w.id}`;
    const balCls = w.balance_cents < 0 ? 'wallet-balance negative' : 'wallet-balance';
    return `
      <div class="wallet-row">
        <div class="wallet-name"><span class="wallet-icon">${icon}</span><span>${escapeHtml(name)}</span></div>
        <div class="${balCls}">${fmtAmount(w.balance_cents)}</div>
      </div>`;
  }).join('');
}

function renderMonthBreakdown(monthData) {
  const total = monthData.total_cents || 0;
  const totalEl = document.getElementById('month-total');
  totalEl.textContent = fmtAmount(total);

  const monthName = new Date().toLocaleString('en-US', { month: 'long' });
  document.getElementById('month-name').textContent = monthName;

  const root = document.getElementById('month-by-category');
  const rows = monthData.by_category || [];
  if (rows.length === 0) {
    root.innerHTML = '<div class="muted small">No spending this month yet.</div>';
    return;
  }
  const max = rows[0].total_cents || 1;
  root.innerHTML = rows.slice(0, 8).map(r => {
    const pct = Math.max(2, Math.round((r.total_cents / max) * 100));
    return `
      <div class="bar-row">
        <div class="bar-meta">
          <span class="bar-cat">${r.category_icon || '•'} ${escapeHtml(r.category_name)}</span>
          <span class="bar-amt">${fmtAmount(r.total_cents)}</span>
        </div>
        <div class="bar-track"><div class="bar-fill" style="width:${pct}%"></div></div>
      </div>`;
  }).join('');
}

function renderRecent(rows) {
  const root = document.getElementById('recent-list');
  if (!rows || rows.length === 0) {
    root.innerHTML = '<div class="muted small">No transactions yet.</div>';
    return;
  }
  root.innerHTML = rows.map(t => {
    const { sign, cls } = txSign(t.type);
    const cat = t.category_name || (t.type === 'transfer' ? 'Transfer' : '—');
    const icon = t.category_icon || (t.type === 'transfer' ? '↔' : (t.type === 'income' ? '💰' : '💸'));

    let line2parts = [];
    if (t.item_name) {
      let name = t.item_name;
      if (t.item_size) name += ` (${t.item_size})`;
      line2parts.push(name);
    }
    if (t.place_branch) line2parts.push(`@ ${t.place_branch}`);
    if (t.type === 'transfer' && t.source_wallet_name && t.dest_wallet_name) {
      line2parts.push(`${t.source_wallet_name} → ${t.dest_wallet_name}`);
    }
    if (t.note) line2parts.push(`<span class="tx-note">${escapeHtml(t.note)}</span>`);
    line2parts.push(fmtDateRelative(t.occurred_at));
    const line2 = line2parts.join(' · ');

    return `
      <div class="tx-row">
        <div class="tx-icon">${icon}</div>
        <div class="tx-mid">
          <div class="tx-line1">${escapeHtml(cat)}</div>
          <div class="tx-line2">${line2}</div>
        </div>
        <div class="tx-amount ${cls}">${sign}${fmtAmount(t.amount_cents).replace('-', '')}</div>
      </div>`;
  }).join('');
}

function escapeHtml(s) {
  if (s == null) return '';
  return String(s)
    .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;').replace(/'/g, '&#39;');
}

// ---------- Loaders ----------

async function loadDashboard() {
  const btn = document.getElementById('refresh-btn');
  if (btn) btn.classList.add('spinning');
  try {
    const data = await fetchJSON('/api/dashboard');
    renderNetWorth(data.net_worth_cents, (data.wallets || []).length);
    renderWallets(data.wallets);
    renderMonthBreakdown(data.this_month || { total_cents: 0, by_category: [] });
    renderRecent(data.recent_transactions);
  } catch (e) {
    if (e.status === 401 || e.status === 403) {
      show('login-screen');
      mountTelegramWidget();
      return;
    }
    alert('Failed to load: ' + (e.message || 'unknown'));
  } finally {
    if (btn) btn.classList.remove('spinning');
  }
}

async function init() {
  try {
    CONFIG = await fetchJSON('/api/config');
  } catch (_) {
    CONFIG = { bot_username: 'Money_trackeer_bot' };
  }

  try {
    ME = await fetchJSON('/api/me');
    renderHeader(ME);
    show('dashboard');
    await loadDashboard();
  } catch (e) {
    if (e.status === 401 || e.status === 403) {
      show('login-screen');
      mountTelegramWidget();
    } else {
      alert('Error loading: ' + (e.message || 'unknown'));
      show('login-screen');
      mountTelegramWidget();
    }
  }
}

window.onTelegramAuth = onTelegramAuth;
window.logout = logout;
window.loadDashboard = loadDashboard;
window.addEventListener('DOMContentLoaded', init);
