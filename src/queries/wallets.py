"""Read-only wallet queries against finance-bot's DB.

Balance math mirrors the bot's `db/wallets.get_balance_cents`:
    balance = initial_balance + Σ(dest_wallet_id = w) − Σ(source_wallet_id = w)
across non-deleted transactions.

Net worth = sum of liquid wallet balances + gold valuation
(grams_milligrams / 1000 × price_per_gram_cents).
"""
import aiosqlite

from src.db import db_uri


async def list_with_balances() -> list[dict]:
    """Return all active wallets with computed balance_cents per row.

    One round-trip via three subqueries — keeps it cheap even for many wallets.
    """
    async with aiosqlite.connect(db_uri(), uri=True) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            """
            SELECT
                w.id,
                w.name_en,
                w.name_ar,
                w.type,
                w.initial_balance_cents,
                w.karat,
                w.gold_grams_milligrams,
                w.gold_price_per_gram_cents,
                COALESCE((
                    SELECT SUM(amount_cents) FROM transactions
                    WHERE dest_wallet_id = w.id AND deleted_at IS NULL
                ), 0) AS in_cents,
                COALESCE((
                    SELECT SUM(amount_cents) FROM transactions
                    WHERE source_wallet_id = w.id AND deleted_at IS NULL
                ), 0) AS out_cents
            FROM wallets w
            WHERE w.deleted_at IS NULL
            ORDER BY w.id
            """
        ) as cur:
            rows = [dict(r) for r in await cur.fetchall()]

    out: list[dict] = []
    for r in rows:
        balance = r["initial_balance_cents"] + r["in_cents"] - r["out_cents"]
        out.append({
            "id": r["id"],
            "name_en": r["name_en"],
            "name_ar": r["name_ar"],
            "type": r["type"],
            "balance_cents": balance,
            "karat": r.get("karat"),
            "gold_grams_milligrams": r.get("gold_grams_milligrams"),
            "gold_price_per_gram_cents": r.get("gold_price_per_gram_cents"),
        })
    return out


async def net_worth_cents() -> int:
    """Sum of liquid balances + gold valuation."""
    total = 0
    for w in await list_with_balances():
        if w["type"] in ("cash", "bank", "e_wallet"):
            total += w["balance_cents"]
        elif w["type"] == "asset_gold":
            grams_mg = w.get("gold_grams_milligrams") or 0
            price_cents = w.get("gold_price_per_gram_cents") or 0
            total += (grams_mg * price_cents) // 1000
    return total
