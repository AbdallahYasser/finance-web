// finance-web W0 — login + profile placeholder.

let CONFIG = null;

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
    alert('Login failed: ' + (e.message || 'unknown error'));
  }
}

async function logout() {
  try {
    await fetchJSON('/api/logout', { method: 'POST' });
  } catch (_) {}
  location.reload();
}

function renderProfile(me) {
  const set = (id, v) => { const el = document.getElementById(id); if (el) el.textContent = v ?? '—'; };
  set('user-name', 'User ' + me.user_id);
  set('hello-name', 'User ' + me.user_id);
  set('profile-user-id', String(me.user_id));
  set('profile-language', me.language || 'en');
  set('profile-timezone', me.timezone || '—');
  set('profile-salary-day', me.salary_day != null ? String(me.salary_day) : '—');
  set('profile-created', me.created_at ? me.created_at.replace('T', ' ').slice(0, 19) : '—');
}

async function init() {
  try {
    CONFIG = await fetchJSON('/api/config');
  } catch (e) {
    CONFIG = { bot_username: 'Money_trackeer_bot' };
  }

  try {
    const me = await fetchJSON('/api/me');
    renderProfile(me);
    show('dashboard');
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
window.addEventListener('DOMContentLoaded', init);
