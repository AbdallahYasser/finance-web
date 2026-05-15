"""People + per-person debt balance queries."""
import aiosqlite

from src.db import db_uri


async def list_with_balances() -> list[dict]:
    """Active people with their net debt position:
        balance_cents > 0  → they owe you (receivable)
        balance_cents < 0  → you owe them (payable)
        balance_cents == 0 → settled

    Forgiven debts excluded from the balance.
    """
    async with aiosqlite.connect(db_uri(), uri=True) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            """
            SELECT
                p.id, p.name, p.telegram_username, p.phone, p.note,
                COALESCE(SUM(
                    CASE
                        WHEN d.status = 'forgiven' THEN 0
                        WHEN d.direction = 'lent' THEN
                            (d.original_amount_cents -
                             COALESCE((SELECT SUM(amount_cents) FROM transactions
                                       WHERE debt_id = d.id AND type = 'repay_in'
                                         AND deleted_at IS NULL), 0))
                        WHEN d.direction = 'borrowed' THEN -1 * (
                            d.original_amount_cents -
                            COALESCE((SELECT SUM(amount_cents) FROM transactions
                                      WHERE debt_id = d.id AND type = 'repay_out'
                                        AND deleted_at IS NULL), 0))
                        ELSE 0
                    END
                ), 0) AS balance_cents,
                COUNT(d.id) AS debt_count,
                MAX(d.opened_at) AS last_debt_at
            FROM people p
            LEFT JOIN debts d ON d.person_id = p.id
            WHERE p.deleted_at IS NULL
            GROUP BY p.id
            ORDER BY ABS(balance_cents) DESC, p.name COLLATE NOCASE
            """
        ) as cur:
            return [dict(r) for r in await cur.fetchall()]


async def list_active() -> list[dict]:
    async with aiosqlite.connect(db_uri(), uri=True) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            """
            SELECT id, name, telegram_username, phone
            FROM people WHERE deleted_at IS NULL
            ORDER BY name COLLATE NOCASE
            """
        ) as cur:
            return [dict(r) for r in await cur.fetchall()]


async def net_receivables_cents() -> int:
    """Sum of all open + partial debts where you're owed money."""
    async with aiosqlite.connect(db_uri(), uri=True) as db:
        async with db.execute(
            """
            SELECT COALESCE(SUM(
                d.original_amount_cents -
                COALESCE((SELECT SUM(amount_cents) FROM transactions
                          WHERE debt_id = d.id AND type = 'repay_in'
                            AND deleted_at IS NULL), 0)
            ), 0)
            FROM debts d
            WHERE d.direction = 'lent' AND d.status IN ('open', 'partial')
            """
        ) as cur:
            (n,) = await cur.fetchone()
            return n or 0


async def net_payables_cents() -> int:
    """Sum of all open + partial debts where you owe money."""
    async with aiosqlite.connect(db_uri(), uri=True) as db:
        async with db.execute(
            """
            SELECT COALESCE(SUM(
                d.original_amount_cents -
                COALESCE((SELECT SUM(amount_cents) FROM transactions
                          WHERE debt_id = d.id AND type = 'repay_out'
                            AND deleted_at IS NULL), 0)
            ), 0)
            FROM debts d
            WHERE d.direction = 'borrowed' AND d.status IN ('open', 'partial')
            """
        ) as cur:
            (n,) = await cur.fetchone()
            return n or 0
