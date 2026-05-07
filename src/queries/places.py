"""Read-only place queries: summary list + per-place detail with top items."""
import aiosqlite

from src.db import db_uri


async def list_summary() -> list[dict]:
    """All active places with aggregate stats:
        id, branch_name, chain_name,
        tx_count          — how many transactions occurred here
        total_spent_cents — net spend (spend − refund) at this place
        last_used         — most recent transaction occurred_at
        item_count        — distinct items bought here
    """
    async with aiosqlite.connect(db_uri(), uri=True) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            """
            SELECT
                p.id, p.branch_name, p.chain_name,
                COALESCE(t.tx_count, 0)          AS tx_count,
                COALESCE(t.total_spent_cents, 0) AS total_spent_cents,
                t.last_used,
                COALESCE(t.item_count, 0)        AS item_count
            FROM places p
            LEFT JOIN (
                SELECT
                    place_id,
                    COUNT(*) AS tx_count,
                    MAX(occurred_at) AS last_used,
                    SUM(CASE WHEN type='spend' THEN amount_cents
                             WHEN type='refund' THEN -amount_cents
                             ELSE 0 END) AS total_spent_cents,
                    COUNT(DISTINCT item_id) AS item_count
                FROM transactions
                WHERE deleted_at IS NULL AND place_id IS NOT NULL
                GROUP BY place_id
            ) t ON t.place_id = p.id
            WHERE p.deleted_at IS NULL
            ORDER BY (t.last_used IS NULL), t.last_used DESC, p.id DESC
            """
        ) as cur:
            return [dict(r) for r in await cur.fetchall()]


async def get_detail(place_id: int, recent_limit: int = 10, top_items_limit: int = 10) -> dict | None:
    """One place with: top items by spend, recent transactions, summary stats."""
    async with aiosqlite.connect(db_uri(), uri=True) as db:
        db.row_factory = aiosqlite.Row

        async with db.execute(
            """
            SELECT id, branch_name, chain_name
            FROM places WHERE id = ? AND deleted_at IS NULL
            """,
            (place_id,),
        ) as cur:
            place_row = await cur.fetchone()
            if not place_row:
                return None
            place = dict(place_row)

        async with db.execute(
            """
            SELECT
                COUNT(*) AS tx_count,
                COALESCE(SUM(CASE WHEN type='spend' THEN amount_cents
                                  WHEN type='refund' THEN -amount_cents
                                  ELSE 0 END), 0) AS total_spent_cents,
                MAX(occurred_at) AS last_used,
                MIN(occurred_at) AS first_used
            FROM transactions
            WHERE place_id = ? AND deleted_at IS NULL
            """,
            (place_id,),
        ) as cur:
            summary = dict(await cur.fetchone())

        async with db.execute(
            """
            SELECT
                i.id AS item_id,
                i.canonical_name_en AS name_en,
                i.size,
                COUNT(*) AS tx_count,
                SUM(CASE WHEN t.type='spend' THEN t.amount_cents
                         WHEN t.type='refund' THEN -t.amount_cents
                         ELSE 0 END) AS total_spent_cents,
                MAX(t.occurred_at) AS last_used,
                (SELECT price_cents FROM item_prices p
                 WHERE p.item_id = i.id AND p.place_id = ?
                 ORDER BY p.observed_at DESC, p.id DESC LIMIT 1) AS last_price_cents
            FROM transactions t
            JOIN items i ON i.id = t.item_id
            WHERE t.place_id = ? AND t.deleted_at IS NULL AND t.item_id IS NOT NULL
            GROUP BY i.id
            ORDER BY total_spent_cents DESC
            LIMIT ?
            """,
            (place_id, place_id, top_items_limit),
        ) as cur:
            top_items = [dict(r) for r in await cur.fetchall()]

        async with db.execute(
            """
            SELECT
                t.id, t.type, t.amount_cents, t.occurred_at, t.note,
                c.name_en  AS category_name,  c.icon AS category_icon,
                i.canonical_name_en AS item_name, i.size AS item_size,
                sw.name_en AS source_wallet_name,
                dw.name_en AS dest_wallet_name
            FROM transactions t
            LEFT JOIN categories c  ON c.id  = t.category_id
            LEFT JOIN items     i  ON i.id  = t.item_id
            LEFT JOIN wallets   sw ON sw.id = t.source_wallet_id
            LEFT JOIN wallets   dw ON dw.id = t.dest_wallet_id
            WHERE t.place_id = ? AND t.deleted_at IS NULL
            ORDER BY t.occurred_at DESC, t.id DESC
            LIMIT ?
            """,
            (place_id, recent_limit),
        ) as cur:
            recent = [dict(r) for r in await cur.fetchall()]

    return {
        "place":   place,
        "summary": summary,
        "top_items": top_items,
        "recent":   recent,
    }
