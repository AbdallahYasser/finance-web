"""Read-only transaction queries: recent list + monthly category aggregation."""
from datetime import datetime, timedelta, timezone

import aiosqlite

from src.db import db_uri


async def recent(limit: int = 20) -> list[dict]:
    """Latest non-deleted transactions with category, item, place joined."""
    async with aiosqlite.connect(db_uri(), uri=True) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            """
            SELECT
                t.id, t.type, t.amount_cents, t.occurred_at, t.note,
                t.source_wallet_id, t.dest_wallet_id,
                c.name_en AS category_name, c.icon AS category_icon,
                i.canonical_name_en AS item_name, i.size AS item_size,
                p.branch_name AS place_branch, p.chain_name AS place_chain,
                sw.name_en AS source_wallet_name,
                dw.name_en AS dest_wallet_name
            FROM transactions t
            LEFT JOIN categories c  ON c.id  = t.category_id
            LEFT JOIN items     i  ON i.id  = t.item_id
            LEFT JOIN places    p  ON p.id  = t.place_id
            LEFT JOIN wallets   sw ON sw.id = t.source_wallet_id
            LEFT JOIN wallets   dw ON dw.id = t.dest_wallet_id
            WHERE t.deleted_at IS NULL
            ORDER BY t.occurred_at DESC, t.id DESC
            LIMIT ?
            """,
            (limit,),
        ) as cur:
            return [dict(r) for r in await cur.fetchall()]


async def this_month_by_category() -> list[dict]:
    """Spend totals for the current calendar month (UTC), grouped by category.

    Treats spends as positive outflow; refunds subtract back. Income/transfer
    are excluded from this view since it's strictly an expense breakdown.

    Note: month boundary uses UTC. Once we add a /api/timezone-aware version,
    this can swap to using the user's tz. Single-user app, low priority.
    """
    now = datetime.now(timezone.utc)
    # First day of current UTC month
    month_start = datetime(now.year, now.month, 1, tzinfo=timezone.utc).strftime(
        "%Y-%m-%dT%H:%M:%SZ"
    )

    async with aiosqlite.connect(db_uri(), uri=True) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            """
            SELECT
                COALESCE(c.id, 0) AS category_id,
                COALESCE(c.name_en, 'Uncategorized') AS category_name,
                COALESCE(c.icon, '•') AS category_icon,
                SUM(
                    CASE
                        WHEN t.type = 'spend'  THEN t.amount_cents
                        WHEN t.type = 'refund' THEN -t.amount_cents
                        ELSE 0
                    END
                ) AS total_cents,
                COUNT(*) AS tx_count
            FROM transactions t
            LEFT JOIN categories c ON c.id = t.category_id
            WHERE t.deleted_at IS NULL
              AND t.type IN ('spend', 'refund')
              AND t.occurred_at >= ?
            GROUP BY COALESCE(c.id, 0)
            HAVING total_cents > 0
            ORDER BY total_cents DESC
            """,
            (month_start,),
        ) as cur:
            return [dict(r) for r in await cur.fetchall()]


async def this_month_total_cents() -> int:
    rows = await this_month_by_category()
    return sum(r["total_cents"] for r in rows)
