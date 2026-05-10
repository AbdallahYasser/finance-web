"""Transaction write helpers.

Constraints (mirror finance-bot's M1 logic):
- spend     → source_wallet_id required, no dest_wallet_id
- income    → dest_wallet_id required, no source_wallet_id
- transfer  → both required, must differ
- refund    → dest_wallet_id required, refund_of_id required
- amount_cents > 0 (DB CHECK enforces too)

When a write produces (item_id != null AND place_id != null AND type IN spend),
also insert into `item_prices` linking back via `transaction_id` so the
price-history feature gets the new observation. On UPDATE we leave existing
`item_prices` rows alone — historical observations are immutable.
"""
from datetime import datetime, timezone
from typing import Optional

import aiosqlite

from src.db import write_db_uri

ALLOWED_TYPES = {"spend", "income", "transfer", "refund"}


def _now_utc_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _validate_for_insert(
    *, type: str, amount_cents: int,
    source_wallet_id: Optional[int], dest_wallet_id: Optional[int],
    refund_of_id: Optional[int],
) -> None:
    if type not in ALLOWED_TYPES:
        raise ValueError(f"unsupported transaction type from web: {type!r}")
    if amount_cents <= 0:
        raise ValueError("amount must be > 0")
    if type == "spend":
        if not source_wallet_id:
            raise ValueError("spend requires source_wallet_id")
    elif type == "income":
        if not dest_wallet_id:
            raise ValueError("income requires dest_wallet_id")
    elif type == "transfer":
        if not source_wallet_id or not dest_wallet_id:
            raise ValueError("transfer requires both source and dest wallets")
        if source_wallet_id == dest_wallet_id:
            raise ValueError("source and destination wallets must differ")
    elif type == "refund":
        if not dest_wallet_id:
            raise ValueError("refund requires dest_wallet_id")
        if not refund_of_id:
            raise ValueError("refund requires refund_of_id")


async def insert_transaction(
    *,
    type: str,
    amount_cents: int,
    source_wallet_id: Optional[int] = None,
    dest_wallet_id: Optional[int] = None,
    category_id: Optional[int] = None,
    item_id: Optional[int] = None,
    place_id: Optional[int] = None,
    refund_of_id: Optional[int] = None,
    occurred_at: Optional[str] = None,
    note: Optional[str] = None,
) -> int:
    """Insert a transaction. Returns the new tx id."""
    _validate_for_insert(
        type=type, amount_cents=amount_cents,
        source_wallet_id=source_wallet_id, dest_wallet_id=dest_wallet_id,
        refund_of_id=refund_of_id,
    )

    occurred_at = occurred_at or _now_utc_iso()
    note = (note or "").strip() or None

    async with aiosqlite.connect(write_db_uri(), uri=True) as db:
        cur = await db.execute(
            """
            INSERT INTO transactions
              (type, amount_cents,
               source_wallet_id, dest_wallet_id,
               category_id, item_id, place_id,
               refund_of_id,
               occurred_at, note,
               source)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'manual')
            """,
            (
                type, amount_cents,
                source_wallet_id, dest_wallet_id,
                category_id, item_id, place_id,
                refund_of_id,
                occurred_at, note,
            ),
        )
        tx_id = cur.lastrowid

        # Item-price observation side-effect (only for spends with both ids).
        # Refunds don't generate a price observation — that would distort the
        # price history. Income/transfer never have item_id set.
        if type == "spend" and item_id and place_id:
            await db.execute(
                """
                INSERT INTO item_prices
                  (item_id, place_id, price_cents, observed_at, on_sale, transaction_id)
                VALUES (?, ?, ?, ?, 0, ?)
                """,
                (item_id, place_id, amount_cents, occurred_at, tx_id),
            )

        await db.commit()
        return tx_id


# Fields that update_transaction is allowed to touch.
_UPDATABLE_FIELDS = {
    "type", "amount_cents",
    "source_wallet_id", "dest_wallet_id",
    "category_id", "item_id", "place_id",
    "refund_of_id",
    "occurred_at", "note",
}


async def update_transaction(tx_id: int, **fields) -> bool:
    """Partial update. Only fields in `_UPDATABLE_FIELDS` apply.

    Returns True iff a row was updated. Leaves existing `item_prices` rows
    alone — historical observations are immutable.
    """
    bad = set(fields) - _UPDATABLE_FIELDS
    if bad:
        raise ValueError(f"cannot update fields: {sorted(bad)}")
    if not fields:
        return False

    if "amount_cents" in fields and fields["amount_cents"] is not None and fields["amount_cents"] <= 0:
        raise ValueError("amount must be > 0")
    if "type" in fields and fields["type"] not in ALLOWED_TYPES:
        raise ValueError(f"unsupported type: {fields['type']!r}")

    cols = list(fields.keys())
    set_sql = ", ".join(f"{c} = ?" for c in cols)
    values = [fields[c] for c in cols] + [tx_id]

    async with aiosqlite.connect(write_db_uri(), uri=True) as db:
        cur = await db.execute(
            f"""
            UPDATE transactions
               SET {set_sql}
             WHERE id = ? AND deleted_at IS NULL
            """,
            values,
        )
        await db.commit()
        return cur.rowcount > 0


async def soft_delete(tx_id: int) -> bool:
    async with aiosqlite.connect(write_db_uri(), uri=True) as db:
        cur = await db.execute(
            "UPDATE transactions SET deleted_at = datetime('now') "
            "WHERE id = ? AND deleted_at IS NULL",
            (tx_id,),
        )
        await db.commit()
        return cur.rowcount > 0


async def restore(tx_id: int) -> bool:
    async with aiosqlite.connect(write_db_uri(), uri=True) as db:
        cur = await db.execute(
            "UPDATE transactions SET deleted_at = NULL "
            "WHERE id = ? AND deleted_at IS NOT NULL",
            (tx_id,),
        )
        await db.commit()
        return cur.rowcount > 0
