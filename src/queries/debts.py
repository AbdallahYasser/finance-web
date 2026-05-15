"""Debt detail + listings + per-debt payment timeline."""
import aiosqlite

from src.db import db_uri


async def list_for_person(person_id: int) -> list[dict]:
    """All debts for a person, each with remaining + repaid cents."""
    async with aiosqlite.connect(db_uri(), uri=True) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            """
            SELECT
                d.id, d.person_id, d.direction, d.original_amount_cents,
                d.opened_at, d.due_at, d.status, d.note,
                COALESCE((SELECT SUM(amount_cents) FROM transactions
                          WHERE debt_id = d.id
                            AND type IN ('repay_in','repay_out')
                            AND deleted_at IS NULL), 0) AS repaid_cents
            FROM debts d
            WHERE d.person_id = ?
            ORDER BY d.opened_at DESC, d.id DESC
            """,
            (person_id,),
        ) as cur:
            rows = [dict(r) for r in await cur.fetchall()]
    for r in rows:
        r["remaining_cents"] = max(0, r["original_amount_cents"] - r["repaid_cents"])
    return rows


async def list_open() -> list[dict]:
    async with aiosqlite.connect(db_uri(), uri=True) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            """
            SELECT
                d.id, d.person_id, p.name AS person_name,
                d.direction, d.original_amount_cents, d.opened_at, d.due_at,
                d.status, d.note,
                COALESCE((SELECT SUM(amount_cents) FROM transactions
                          WHERE debt_id = d.id
                            AND type IN ('repay_in','repay_out')
                            AND deleted_at IS NULL), 0) AS repaid_cents
            FROM debts d
            JOIN people p ON p.id = d.person_id
            WHERE d.status IN ('open','partial') AND p.deleted_at IS NULL
            ORDER BY d.opened_at DESC
            """
        ) as cur:
            rows = [dict(r) for r in await cur.fetchall()]
    for r in rows:
        r["remaining_cents"] = max(0, r["original_amount_cents"] - r["repaid_cents"])
    return rows


async def get(debt_id: int) -> dict | None:
    async with aiosqlite.connect(db_uri(), uri=True) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            """
            SELECT
                d.*, p.name AS person_name,
                COALESCE((SELECT SUM(amount_cents) FROM transactions
                          WHERE debt_id = d.id
                            AND type IN ('repay_in','repay_out')
                            AND deleted_at IS NULL), 0) AS repaid_cents
            FROM debts d
            JOIN people p ON p.id = d.person_id
            WHERE d.id = ?
            """,
            (debt_id,),
        ) as cur:
            row = await cur.fetchone()
            if not row:
                return None
            r = dict(row)
            r["remaining_cents"] = max(0, r["original_amount_cents"] - r["repaid_cents"])
            return r


async def payments_for(debt_id: int) -> list[dict]:
    """Linked repay/forgive transactions for a debt, oldest first."""
    async with aiosqlite.connect(db_uri(), uri=True) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            """
            SELECT id, type, amount_cents, occurred_at, note,
                   source_wallet_id, dest_wallet_id
            FROM transactions
            WHERE debt_id = ? AND deleted_at IS NULL
              AND type IN ('lend','borrow','repay_in','repay_out','forgive')
            ORDER BY occurred_at ASC, id ASC
            """,
            (debt_id,),
        ) as cur:
            return [dict(r) for r in await cur.fetchall()]
