"""finance-web — FastAPI backend.

W0: serves a login page and exposes /api/me.
W1+ adds dashboard data routes.
"""
import logging
import time
from pathlib import Path

from dotenv import load_dotenv
load_dotenv()

from fastapi import Depends, FastAPI, HTTPException, Request, Response
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles

from src import auth, config, db
from src.queries import wallets as q_wallets
from src.queries import transactions as q_tx

logging.basicConfig(
    level=getattr(logging, config.LOG_LEVEL.upper(), logging.INFO),
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

# Set once at container start. Injected into asset URLs as ?v=… so the CDN
# (Cloudflare) sees a fresh cache key on every Coolify deploy.
_DEPLOY_TS = str(int(time.time()))

app = FastAPI(docs_url=None, redoc_url=None)
STATIC_DIR = Path(__file__).parent / "static"


# ---------------------------------------------------------------------------
# Auth
# ---------------------------------------------------------------------------

@app.post("/api/auth/telegram")
async def telegram_auth(request: Request, response: Response):
    data = await request.json()

    if not auth.verify_telegram_hash(data):
        raise HTTPException(status_code=403, detail="Invalid Telegram auth")

    user_id = int(data["id"])

    if not await auth.is_user_allowed(user_id):
        raise HTTPException(status_code=403, detail="Access denied")

    token = auth.create_session_token(user_id)
    response.set_cookie(
        key="session",
        value=token,
        httponly=True,
        secure=True,
        samesite="lax",
        max_age=auth.SESSION_DAYS * 86400,
    )
    return {"ok": True, "first_name": data.get("first_name", "")}


@app.post("/api/logout")
async def logout(response: Response):
    response.delete_cookie("session")
    return {"ok": True}


# ---------------------------------------------------------------------------
# Data
# ---------------------------------------------------------------------------

@app.get("/api/config")
async def api_config():
    """Public — bot username for the Telegram Login Widget."""
    return {"bot_username": config.BOT_USERNAME}


@app.get("/api/me")
async def me(user_id: int = Depends(auth.get_current_user)):
    user = await db.get_user(user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not in bot DB")
    return {
        "user_id":  user_id,
        "language": user.get("language") or "en",
        "timezone": user.get("timezone") or "Africa/Cairo",
        "salary_day": user.get("salary_day"),
        "created_at": user.get("created_at") or "",
    }


@app.get("/api/dashboard")
async def dashboard(user_id: int = Depends(auth.get_current_user)):
    """Composite payload — one round-trip for the whole W1 dashboard."""
    wallets = await q_wallets.list_with_balances()
    net_worth = await q_wallets.net_worth_cents()
    by_category = await q_tx.this_month_by_category()
    month_total = sum(r["total_cents"] for r in by_category)
    recent = await q_tx.recent(limit=20)

    return {
        "net_worth_cents": net_worth,
        "wallets": wallets,
        "this_month": {
            "total_cents": month_total,
            "by_category": by_category,
        },
        "recent_transactions": recent,
    }


# ---------------------------------------------------------------------------
# Static frontend (mounted last so /api/* takes precedence)
# ---------------------------------------------------------------------------

@app.get("/", response_class=HTMLResponse)
async def index():
    content = (STATIC_DIR / "index.html").read_text()
    content = content.replace('src="./app.js"',     f'src="./app.js?v={_DEPLOY_TS}"')
    content = content.replace('href="./style.css"', f'href="./style.css?v={_DEPLOY_TS}"')
    return HTMLResponse(content=content, headers={"Cache-Control": "no-store"})


class NoCacheStaticFiles(StaticFiles):
    async def get_response(self, path: str, scope):
        response = await super().get_response(path, scope)
        response.headers["Cache-Control"] = "no-store"
        return response


app.mount("/", NoCacheStaticFiles(directory=str(STATIC_DIR), html=True), name="static")
