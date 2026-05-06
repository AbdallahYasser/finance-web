# CLAUDE.md — finance-web

Repo conventions and gotchas for future Claude Code sessions.

## What this is

Web companion to the `finance-bot` Telegram bot. Same single user (chat_id 5904148250). Same EGP / Africa/Cairo / bilingual semantics. Same Coolify project on the same EC2.

## Stack

- FastAPI + uvicorn (async)
- Vanilla JS + CSS, single `src/static/index.html` — no build step, no SPA framework
- Telegram Login Widget → HMAC-SHA256 verify with `BOT_TOKEN` → JWT cookie (`python-jose`)
- aiosqlite reading the bot's DB via `file:{DB_PATH}?immutable=1` URI (W0–W3 read-only)

## Conventions

- **Read-only by default** through W3. Writes (forms, edits) land in W4 — at which point we drop `:ro` from the bind mount and add proper transactional helpers.
- **All amounts as INTEGER cents** (matches the bot). Display layer formats with `f"{cents/100:,.2f} EGP"` until W3 brings a Babel-aware helper.
- **Timestamps stored as UTC ISO** (matches the bot). Display in `Africa/Cairo` via pytz.
- **Auth gate**: every data route depends on `Depends(auth.get_current_user)` which validates the JWT cookie. `auth.is_user_allowed` checks the `allowed_users` table — the same one the bot seeds. Outside `ALLOWED_USERS` → 403.
- **Cache busting**: `_DEPLOY_TS` set once at startup; `index.html` is rewritten to inject `?v={ts}` on `app.js` and `style.css`. `NoCacheStaticFiles` sets `Cache-Control: no-store` on every asset. Mirrors the prayer-web fix for Cloudflare edge caching.

## Layout

```
src/
  main.py        FastAPI app, routes, cache-busting, static mount
  config.py      env loading
  auth.py        Telegram hash verify + JWT issue/verify + get_current_user dep
  db.py          aiosqlite read-only URI + low-level helpers
  queries/       one module per resource (wallets, transactions, items, places, prices)
  static/
    index.html   SPA shell — login + dashboard sections
    style.css    dark theme
    app.js       state + fetch + render
tests/
  conftest.py
  test_auth.py   hash verify, JWT round-trip, allowlist
```

## DB sharing — critical

The bot owns the data. The web mounts the same Coolify Docker volume (`h84occok4wk4gs4888woc8kc_finance-bot-data`) at `/app/data:ro` via `docker-compose.yml`. **Never run migrations from this side** — the bot is the schema authority.

The `?immutable=1` URI flag lets aiosqlite open a WAL-mode DB read-only without needing `.db-shm` files. Required because `:ro` mounts can't create those.

For W4: drop `:ro`, add `PRAGMA journal_mode=WAL` confirmation in db.py, never use raw `DELETE FROM transactions` (soft-delete only — the bot enforces this convention).

## Coolify

- Project: `Finance Bot` (UUID `wk04kwoo00wkw0wc0wwwsk80`) — same as the bot
- App: created via `/applications/public` API (see deploy guide section "Fully API-Driven Setup")
- Domain: `https://finance.bode1.site` (auto Let's Encrypt cert)
- Env vars (`is_preview: false`): BOT_TOKEN, BOT_USERNAME, SECRET_KEY, DB_PATH, ALLOWED_USERS, LOG_LEVEL
- Telegram pre/post deploy notifications via the existing notify bot (8168…)

## Don't

- Don't mock the DB in tests with a different schema — fixtures must reuse the bot's schema (we'll borrow `init_db` from finance-bot for fixtures, OR copy the SQL).
- Don't write to the DB before W4 (mount is `:ro` — writes will fail with `attempt to write a readonly database` anyway, but don't author code that intends to).
- Don't ship a non-Telegram login mechanism. The single-user gate is via `ALLOWED_USERS`; Telegram's signed widget is the authentication.
- Don't put BOT_TOKEN, SECRET_KEY, or any secret in the repo — env vars only, injected by Coolify with `is_preview: false`.
