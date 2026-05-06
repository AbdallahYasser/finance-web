# finance-web

Web companion to [`finance-bot`](https://github.com/AbdallahYasser/finance-bot) — view, search, and (soon) edit your financial data on a real screen instead of through Telegram FSM flows.

Runs at https://finance.bode1.site (Coolify on the same EC2 as the bot).

## Architecture

- **Backend**: FastAPI (async) + uvicorn
- **Frontend**: vanilla JS + CSS, single `index.html` SPA — no build step
- **Auth**: Telegram Login Widget → HMAC-verified by bot token → JWT cookie (httponly, secure, 30-day)
- **DB access**: opens `finance-bot`'s SQLite file via the same Coolify-managed Docker volume, mounted **read-only** for W0–W3 and read-write from W4 onward. The bot writes; the web reads. WAL mode (set on the bot side) handles concurrent access.

Mirrors the existing [`prayer-web`](https://prayer.bode1.site) pattern verbatim.

## Roadmap

- **W0** ▶️ skeleton + deploy + login (`/api/me` returns `{user_id, ...}`)
- **W1** read-only dashboard (net worth, wallets, monthly category spend, recent transactions)
- **W2** transactions table (filter / sort / paginate / search)
- **W3** entity detail pages (wallets / categories / places / **items + price-history charts** — the M3 killer view)
- **W4** edit/create flows (read-write mount, full forms)

After W4, bot M3+ resumes with the web in mind.

## Local dev

```bash
cp .env.example .env
# Fill in BOT_TOKEN (same as finance-bot's), BOT_USERNAME, SECRET_KEY (random hex)
# Point DB_PATH at a local copy of finance_bot.db
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
uvicorn src.main:app --reload --port 8080
```

## Deploy

Auto-deploy via Coolify on push to `main`. Telegram pre/post deploy notifications fire. See `/Users/abdullahwafik/Downloads/projects/COOLIFY_DEPLOY_GUIDE.md` for the full API-driven setup.
