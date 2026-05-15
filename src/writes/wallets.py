"""Wallet write helpers — insert / update / soft-delete / restore."""
from typing import Optional

import aiosqlite

from src.db import write_db_uri

WALLET_TYPES = ("cash", "bank", "e_wallet", "asset_gold")

# Fields update_wallet() may touch. `type` is intentionally not updatable —
# changing the type silently can corrupt net-worth calculations.
_UPDATABLE = {
    "name_en", "name_ar", "initial_balance_cents",
    "karat", "gold_grams_milligrams", "gold_price_per_gram_cents",
    "gold_price_updated_at",
}


def _validate_gold(karat, grams_mg, price_cents) -> None:
    """For asset_gold wallets: karat must be 18/21/24 if set, others must be non-negative ints."""
    if karat is not None and karat not in (18, 21, 24):
        raise ValueError("karat must be 18, 21 or 24")
    if grams_mg is not None and grams_mg < 0:
        raise ValueError("gold_grams_milligrams must be >= 0")
    if price_cents is not None and price_cents < 0:
        raise ValueError("gold_price_per_gram_cents must be >= 0")


async def insert_wallet(
    *,
    name_en: Optional[str] = None,
    name_ar: Optional[str] = None,
    type: str,
    initial_balance_cents: int = 0,
    karat: Optional[int] = None,
    gold_grams_milligrams: Optional[int] = None,
    gold_price_per_gram_cents: Optional[int] = None,
) -> int:
    if type not in WALLET_TYPES:
        raise ValueError(f"invalid wallet type: {type!r}")
    en = (name_en or "").strip() or None
    ar = (name_ar or "").strip() or None
    if not en and not ar:
        raise ValueError("at least one of name_en / name_ar required")
    _validate_gold(karat, gold_grams_milligrams, gold_price_per_gram_cents)

    async with aiosqlite.connect(write_db_uri(), uri=True) as db:
        cur = await db.execute(
            """
            INSERT INTO wallets
              (name_en, name_ar, type, initial_balance_cents,
               karat, gold_grams_milligrams, gold_price_per_gram_cents)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (en, ar, type, initial_balance_cents,
             karat, gold_grams_milligrams, gold_price_per_gram_cents),
        )
        await db.commit()
        return cur.lastrowid


async def update_wallet(wallet_id: int, **fields) -> bool:
    bad = set(fields) - _UPDATABLE
    if bad:
        raise ValueError(f"cannot update fields: {sorted(bad)}")
    if not fields:
        return False
    if "karat" in fields or "gold_grams_milligrams" in fields or "gold_price_per_gram_cents" in fields:
        _validate_gold(
            fields.get("karat"),
            fields.get("gold_grams_milligrams"),
            fields.get("gold_price_per_gram_cents"),
        )
    # Trim string names if provided
    for k in ("name_en", "name_ar"):
        if k in fields and fields[k] is not None:
            fields[k] = fields[k].strip() or None

    cols = list(fields.keys())
    set_sql = ", ".join(f"{c} = ?" for c in cols)
    values = [fields[c] for c in cols] + [wallet_id]

    async with aiosqlite.connect(write_db_uri(), uri=True) as db:
        cur = await db.execute(
            f"UPDATE wallets SET {set_sql} WHERE id = ? AND deleted_at IS NULL",
            values,
        )
        await db.commit()
        return cur.rowcount > 0


async def soft_delete(wallet_id: int) -> bool:
    async with aiosqlite.connect(write_db_uri(), uri=True) as db:
        cur = await db.execute(
            "UPDATE wallets SET deleted_at = datetime('now') "
            "WHERE id = ? AND deleted_at IS NULL",
            (wallet_id,),
        )
        await db.commit()
        return cur.rowcount > 0


async def restore(wallet_id: int) -> bool:
    async with aiosqlite.connect(write_db_uri(), uri=True) as db:
        cur = await db.execute(
            "UPDATE wallets SET deleted_at = NULL "
            "WHERE id = ? AND deleted_at IS NOT NULL",
            (wallet_id,),
        )
        await db.commit()
        return cur.rowcount > 0
