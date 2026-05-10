"""finance-web — FastAPI backend.

W0: serves a login page and exposes /api/me.
W1+ adds dashboard data routes.
"""
import logging
import time
from pathlib import Path

from dotenv import load_dotenv
load_dotenv()

from fastapi import Depends, FastAPI, HTTPException, Query, Request, Response
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles

from src import auth, config, db
from src.middleware import rate_limit
from src.queries import wallets as q_wallets
from src.queries import transactions as q_tx
from src.queries import lookups as q_lookups
from src.queries import items as q_items
from src.queries import places as q_places
from src.writes import transactions as w_tx

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


@app.get("/api/transactions")
async def transactions_search(
    user_id: int = Depends(auth.get_current_user),
    date_from: str | None = None,
    date_to:   str | None = None,
    category_id: int | None = None,
    place_id:    int | None = None,
    item_id:     int | None = None,
    wallet_id:   int | None = None,
    type:        str | None = None,
    q:           str | None = None,
    sort:        str = "date_desc",
    page:        int = 1,
    page_size:   int = 50,
    include_deleted: bool = False,
):
    return await q_tx.search(
        date_from=date_from, date_to=date_to,
        category_id=category_id, place_id=place_id,
        item_id=item_id, wallet_id=wallet_id,
        tx_type=type, q=q, sort=sort,
        page=page, page_size=page_size,
        include_deleted=include_deleted,
    )


# ---------- Writes (W4) ----------

@app.post("/api/transactions", status_code=201)
async def transactions_create(
    request: Request,
    user_id: int = Depends(auth.get_current_user),
):
    rate_limit("write", user_id, max_per_minute=30)
    body = await request.json()
    try:
        tx_id = await w_tx.insert_transaction(
            type=body.get("type"),
            amount_cents=int(body.get("amount_cents", 0)),
            source_wallet_id=body.get("source_wallet_id"),
            dest_wallet_id=body.get("dest_wallet_id"),
            category_id=body.get("category_id"),
            item_id=body.get("item_id"),
            place_id=body.get("place_id"),
            refund_of_id=body.get("refund_of_id"),
            occurred_at=body.get("occurred_at"),
            note=body.get("note"),
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return {"id": tx_id, "row": await q_tx.get(tx_id)}


@app.put("/api/transactions/{tx_id}")
async def transactions_update(
    tx_id: int,
    request: Request,
    user_id: int = Depends(auth.get_current_user),
):
    rate_limit("write", user_id, max_per_minute=30)
    body = await request.json()
    # Filter to known fields, drop None / empty
    fields = {}
    for k in ("type", "amount_cents", "source_wallet_id", "dest_wallet_id",
              "category_id", "item_id", "place_id", "refund_of_id",
              "occurred_at", "note"):
        if k in body:
            fields[k] = body[k]
    try:
        ok = await w_tx.update_transaction(tx_id, **fields)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    if not ok:
        raise HTTPException(status_code=404, detail="Transaction not found")
    row = await q_tx.get(tx_id)
    return {"id": tx_id, "row": row}


@app.delete("/api/transactions/{tx_id}", status_code=204)
async def transactions_delete(
    tx_id: int,
    user_id: int = Depends(auth.get_current_user),
):
    rate_limit("write", user_id, max_per_minute=30)
    ok = await w_tx.soft_delete(tx_id)
    if not ok:
        raise HTTPException(status_code=404, detail="Transaction not found or already deleted")
    return Response(status_code=204)


@app.post("/api/transactions/{tx_id}/restore")
async def transactions_restore(
    tx_id: int,
    user_id: int = Depends(auth.get_current_user),
):
    rate_limit("write", user_id, max_per_minute=30)
    ok = await w_tx.restore(tx_id)
    if not ok:
        raise HTTPException(status_code=404, detail="Transaction not found or not deleted")
    return {"id": tx_id, "row": await q_tx.get(tx_id)}


@app.get("/api/lookups")
async def lookups(user_id: int = Depends(auth.get_current_user)):
    """Filter dropdown data — wallets, categories, places, items."""
    return {
        "wallets":    await q_lookups.wallets_list(),
        "categories": await q_lookups.categories_tree(),
        "places":     await q_lookups.places_list(),
        "items":      await q_lookups.items_list(),
    }


@app.get("/api/items")
async def items_list(user_id: int = Depends(auth.get_current_user)):
    return {"items": await q_items.list_summary()}


@app.get("/api/items/{item_id}")
async def item_detail(item_id: int, user_id: int = Depends(auth.get_current_user)):
    detail = await q_items.get_detail(item_id)
    if not detail:
        raise HTTPException(status_code=404, detail="Item not found")
    return detail


@app.get("/api/places")
async def places_list(user_id: int = Depends(auth.get_current_user)):
    return {"places": await q_places.list_summary()}


@app.get("/api/places/{place_id}")
async def place_detail(place_id: int, user_id: int = Depends(auth.get_current_user)):
    detail = await q_places.get_detail(place_id)
    if not detail:
        raise HTTPException(status_code=404, detail="Place not found")
    return detail


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
