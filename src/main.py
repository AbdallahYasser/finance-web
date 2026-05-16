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
from src.writes import places as w_places
from src.writes import items as w_items
from src.writes import wallets as w_wallets
from src.writes import users as w_users
from src.writes import people as w_people
from src.writes import debts as w_debts
from src.queries import people as q_people
from src.queries import debts as q_debts
from src.queries import reports as q_reports
from src.web_schema import apply_web_migrations

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


@app.on_event("startup")
async def _startup_migrations():
    """Run web-side migrations (W7 people/debts tables, etc.) on boot."""
    try:
        await apply_web_migrations()
    except Exception as e:
        logger.exception("apply_web_migrations failed: %s", e)


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


# ---------- W5: Wallet / Place / Item CRUD + aliases ----------

@app.post("/api/wallets", status_code=201)
async def wallets_create(
    request: Request,
    user_id: int = Depends(auth.get_current_user),
):
    rate_limit("write", user_id, max_per_minute=30)
    body = await request.json()
    try:
        wallet_id = await w_wallets.insert_wallet(
            name_en=body.get("name_en"),
            name_ar=body.get("name_ar"),
            type=body.get("type"),
            initial_balance_cents=int(body.get("initial_balance_cents", 0)),
            karat=body.get("karat"),
            gold_grams_milligrams=body.get("gold_grams_milligrams"),
            gold_price_per_gram_cents=body.get("gold_price_per_gram_cents"),
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    for w in await q_wallets.list_with_balances():
        if w["id"] == wallet_id:
            return w
    raise HTTPException(status_code=500, detail="Wallet created but not retrievable")


@app.put("/api/wallets/{wallet_id}")
async def wallets_update(
    wallet_id: int,
    request: Request,
    user_id: int = Depends(auth.get_current_user),
):
    rate_limit("write", user_id, max_per_minute=30)
    body = await request.json()
    fields = {k: body[k] for k in (
        "name_en", "name_ar", "initial_balance_cents",
        "karat", "gold_grams_milligrams", "gold_price_per_gram_cents",
    ) if k in body}
    try:
        ok = await w_wallets.update_wallet(wallet_id, **fields)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    if not ok:
        raise HTTPException(status_code=404, detail="Wallet not found")
    for w in await q_wallets.list_with_balances():
        if w["id"] == wallet_id:
            return w
    raise HTTPException(status_code=404, detail="Wallet not found")


@app.delete("/api/wallets/{wallet_id}", status_code=204)
async def wallets_delete(
    wallet_id: int,
    user_id: int = Depends(auth.get_current_user),
):
    rate_limit("write", user_id, max_per_minute=30)
    ok = await w_wallets.soft_delete(wallet_id)
    if not ok:
        raise HTTPException(status_code=404, detail="Wallet not found or already deleted")
    return Response(status_code=204)


@app.post("/api/wallets/{wallet_id}/restore")
async def wallets_restore(
    wallet_id: int,
    user_id: int = Depends(auth.get_current_user),
):
    rate_limit("write", user_id, max_per_minute=30)
    ok = await w_wallets.restore(wallet_id)
    if not ok:
        raise HTTPException(status_code=404, detail="Wallet not found or not deleted")
    return {"ok": True, "id": wallet_id}


@app.put("/api/places/{place_id}")
async def places_update(
    place_id: int,
    request: Request,
    user_id: int = Depends(auth.get_current_user),
):
    rate_limit("write", user_id, max_per_minute=30)
    body = await request.json()
    fields = {k: body[k] for k in ("branch_name", "chain_name") if k in body}
    try:
        ok = await w_places.update_place(place_id, **fields)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    if not ok:
        raise HTTPException(status_code=404, detail="Place not found")
    return {"ok": True, "id": place_id}


@app.delete("/api/places/{place_id}", status_code=204)
async def places_delete(
    place_id: int,
    user_id: int = Depends(auth.get_current_user),
):
    rate_limit("write", user_id, max_per_minute=30)
    ok = await w_places.soft_delete(place_id)
    if not ok:
        raise HTTPException(status_code=404, detail="Place not found or already deleted")
    return Response(status_code=204)


@app.post("/api/places/{place_id}/restore")
async def places_restore(
    place_id: int,
    user_id: int = Depends(auth.get_current_user),
):
    rate_limit("write", user_id, max_per_minute=30)
    ok = await w_places.restore(place_id)
    if not ok:
        raise HTTPException(status_code=404, detail="Place not found or not deleted")
    return {"ok": True, "id": place_id}


@app.put("/api/items/{item_id}")
async def items_update(
    item_id: int,
    request: Request,
    user_id: int = Depends(auth.get_current_user),
):
    rate_limit("write", user_id, max_per_minute=30)
    body = await request.json()
    fields = {k: body[k] for k in (
        "canonical_name_en", "canonical_name_ar",
        "size", "unit", "default_category_id",
    ) if k in body}
    try:
        ok = await w_items.update_item(item_id, **fields)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    if not ok:
        raise HTTPException(status_code=404, detail="Item not found")
    return {"ok": True, "id": item_id}


@app.delete("/api/items/{item_id}", status_code=204)
async def items_delete(
    item_id: int,
    user_id: int = Depends(auth.get_current_user),
):
    rate_limit("write", user_id, max_per_minute=30)
    ok = await w_items.soft_delete(item_id)
    if not ok:
        raise HTTPException(status_code=404, detail="Item not found or already deleted")
    return Response(status_code=204)


@app.post("/api/items/{item_id}/restore")
async def items_restore(
    item_id: int,
    user_id: int = Depends(auth.get_current_user),
):
    rate_limit("write", user_id, max_per_minute=30)
    ok = await w_items.restore(item_id)
    if not ok:
        raise HTTPException(status_code=404, detail="Item not found or not deleted")
    return {"ok": True, "id": item_id}


@app.get("/api/items/{item_id}/aliases")
async def aliases_list(
    item_id: int,
    user_id: int = Depends(auth.get_current_user),
):
    return {"aliases": await w_items.list_aliases(item_id)}


@app.post("/api/items/{item_id}/aliases", status_code=201)
async def aliases_add(
    item_id: int,
    request: Request,
    user_id: int = Depends(auth.get_current_user),
):
    rate_limit("write", user_id, max_per_minute=30)
    body = await request.json()
    try:
        alias_id = await w_items.add_alias(item_id, body.get("alias_text", ""))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return {"id": alias_id, "alias_text": (body.get("alias_text") or "").strip()}


@app.delete("/api/aliases/{alias_id}", status_code=204)
async def aliases_remove(
    alias_id: int,
    user_id: int = Depends(auth.get_current_user),
):
    rate_limit("write", user_id, max_per_minute=30)
    ok = await w_items.remove_alias(alias_id)
    if not ok:
        raise HTTPException(status_code=404, detail="Alias not found or already removed")
    return Response(status_code=204)


# ---------- W7: People + Debts ----------

@app.get("/api/people")
async def people_list_endpoint(user_id: int = Depends(auth.get_current_user)):
    return {"people": await q_people.list_with_balances()}


@app.post("/api/people", status_code=201)
async def people_create(
    request: Request,
    user_id: int = Depends(auth.get_current_user),
):
    rate_limit("write", user_id, max_per_minute=30)
    body = await request.json()
    try:
        person_id = await w_people.insert_person(
            name=body.get("name", ""),
            telegram_username=body.get("telegram_username"),
            phone=body.get("phone"),
            note=body.get("note"),
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    for p in await q_people.list_with_balances():
        if p["id"] == person_id:
            return p
    raise HTTPException(status_code=500, detail="Person created but not retrievable")


@app.put("/api/people/{person_id}")
async def people_update(
    person_id: int,
    request: Request,
    user_id: int = Depends(auth.get_current_user),
):
    rate_limit("write", user_id, max_per_minute=30)
    body = await request.json()
    fields = {k: body[k] for k in ("name", "telegram_username", "phone", "note") if k in body}
    try:
        ok = await w_people.update_person(person_id, **fields)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    if not ok:
        raise HTTPException(status_code=404, detail="Person not found")
    return {"ok": True, "id": person_id}


@app.delete("/api/people/{person_id}", status_code=204)
async def people_delete(
    person_id: int,
    user_id: int = Depends(auth.get_current_user),
):
    rate_limit("write", user_id, max_per_minute=30)
    ok = await w_people.soft_delete(person_id)
    if not ok:
        raise HTTPException(status_code=404, detail="Person not found or already deleted")
    return Response(status_code=204)


@app.get("/api/people/{person_id}/debts")
async def people_debts(
    person_id: int,
    user_id: int = Depends(auth.get_current_user),
):
    return {"debts": await q_debts.list_for_person(person_id)}


@app.get("/api/debts")
async def debts_list(user_id: int = Depends(auth.get_current_user)):
    return {"debts": await q_debts.list_open()}


@app.get("/api/debts/{debt_id}")
async def debts_detail(
    debt_id: int,
    user_id: int = Depends(auth.get_current_user),
):
    detail = await q_debts.get(debt_id)
    if not detail:
        raise HTTPException(status_code=404, detail="Debt not found")
    detail["payments"] = await q_debts.payments_for(debt_id)
    return detail


@app.post("/api/debts", status_code=201)
async def debts_create(
    request: Request,
    user_id: int = Depends(auth.get_current_user),
):
    rate_limit("write", user_id, max_per_minute=30)
    body = await request.json()
    try:
        debt_id = await w_debts.insert_debt(
            person_id=body.get("person_id"),
            direction=body.get("direction"),
            amount_cents=int(body.get("amount_cents", 0)),
            wallet_id=body.get("wallet_id"),
            opened_at=body.get("opened_at"),
            due_at=body.get("due_at"),
            note=body.get("note"),
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return {"id": debt_id, "debt": await q_debts.get(debt_id)}


@app.post("/api/debts/{debt_id}/repay", status_code=201)
async def debts_repay(
    debt_id: int,
    request: Request,
    user_id: int = Depends(auth.get_current_user),
):
    rate_limit("write", user_id, max_per_minute=30)
    body = await request.json()
    try:
        tx_id = await w_debts.repay(
            debt_id=debt_id,
            amount_cents=int(body.get("amount_cents", 0)),
            wallet_id=body.get("wallet_id"),
            occurred_at=body.get("occurred_at"),
            note=body.get("note"),
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return {"tx_id": tx_id, "debt": await q_debts.get(debt_id)}


@app.post("/api/debts/{debt_id}/forgive", status_code=201)
async def debts_forgive(
    debt_id: int,
    request: Request,
    user_id: int = Depends(auth.get_current_user),
):
    rate_limit("write", user_id, max_per_minute=30)
    body = await request.json()
    try:
        tx_id = await w_debts.forgive(
            debt_id=debt_id,
            note=body.get("note"),
            forgive_category_id=body.get("forgive_category_id"),
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return {"tx_id": tx_id, "debt": await q_debts.get(debt_id)}


# ---------- W8: Reports + forecast ----------

@app.get("/api/reports")
async def reports(user_id: int = Depends(auth.get_current_user)):
    return {
        "monthly":        await q_reports.monthly_summary(months_back=6),
        "category_trend": await q_reports.category_trend(months_back=6),
        "top_items":      await q_reports.top_items_recent(days=90, limit=5),
        "top_places":     await q_reports.top_places_recent(days=90, limit=5),
        "free_to_spend":  await q_reports.free_to_spend(user_id),
    }


# ---------- W11: language toggle ----------

@app.put("/api/me/language")
async def set_language(
    request: Request,
    user_id: int = Depends(auth.get_current_user),
):
    rate_limit("write", user_id, max_per_minute=30)
    body = await request.json()
    language = body.get("language")
    try:
        ok = await w_users.set_language(user_id, language)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    if not ok:
        raise HTTPException(status_code=404, detail="User not found")
    return {"ok": True, "language": language}


# ---------- W12: CSV export ----------

import csv as _csv
import io as _io
from datetime import datetime as _dt, timezone as _tz
from fastapi.responses import StreamingResponse


def _csv_format_amount(cents: int) -> str:
    sign = "-" if cents < 0 else ""
    cents = abs(cents)
    whole, frac = divmod(cents, 100)
    return f"{sign}{whole}.{frac:02d}"


async def _csv_row_generator(rows: list[dict]):
    buf = _io.StringIO()
    writer = _csv.writer(buf)
    writer.writerow([
        "id", "date", "type", "amount_egp",
        "category", "item", "size", "place", "chain",
        "source_wallet", "dest_wallet", "note", "occurred_at_utc",
    ])
    yield buf.getvalue()
    buf.seek(0); buf.truncate()

    for t in rows:
        date_local = (t.get("occurred_at") or "")[:10]
        writer.writerow([
            t.get("id", ""),
            date_local,
            t.get("type", ""),
            _csv_format_amount(t.get("amount_cents") or 0),
            t.get("category_name") or "",
            t.get("item_name") or "",
            t.get("item_size") or "",
            t.get("place_branch") or "",
            t.get("place_chain") or "",
            t.get("source_wallet_name") or "",
            t.get("dest_wallet_name") or "",
            (t.get("note") or "").replace("\r", " ").replace("\n", " "),
            t.get("occurred_at") or "",
        ])
        yield buf.getvalue()
        buf.seek(0); buf.truncate()


@app.get("/api/transactions/export.csv")
async def transactions_export_csv(
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
    include_deleted: bool = False,
):
    rate_limit("export", user_id, max_per_minute=5)
    payload = await q_tx.search(
        date_from=date_from, date_to=date_to,
        category_id=category_id, place_id=place_id,
        item_id=item_id, wallet_id=wallet_id,
        tx_type=type, q=q, sort=sort,
        page=1, page_size=10_000,
        include_deleted=include_deleted,
    )
    stamp = _dt.now(_tz.utc).strftime("%Y-%m-%d")
    return StreamingResponse(
        _csv_row_generator(payload["rows"]),
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="transactions-{stamp}.csv"'},
    )
    return Response(status_code=204)


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
