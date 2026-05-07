"""Read-only transaction queries: recent list + monthly category aggregation + search."""
from datetime import datetime, timezone

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


# ---------- Search (W2) ----------

_SORT_SQL = {
    "date_desc":   "t.occurred_at DESC, t.id DESC",
    "date_asc":    "t.occurred_at ASC,  t.id ASC",
    "amount_desc": "t.amount_cents DESC, t.id DESC",
    "amount_asc":  "t.amount_cents ASC,  t.id ASC",
}

ALLOWED_TYPES = {
    "spend", "income", "transfer", "refund",
    "lend", "borrow", "repay_in", "repay_out", "forgive",
    "gold_buy", "gold_sell", "reconcile_adjust",
}


async def search(
    *,
    date_from: str | None = None,
    date_to: str | None = None,
    category_id: int | None = None,
    place_id: int | None = None,
    item_id: int | None = None,
    wallet_id: int | None = None,
    tx_type: str | None = None,
    q: str | None = None,
    sort: str = "date_desc",
    page: int = 1,
    page_size: int = 50,
) -> dict:
    """Filterable, sortable, paginated transaction search.

    Returns: {total, page, page_size, total_pages, rows}.
    All string params are parameterized — never interpolated into SQL.
    `category_id` matches the category OR any of its direct children.
    `wallet_id` matches transactions where the wallet is source OR destination.
    `q` LIKEs against note + canonical item names + place branch/chain names.
    """
    where = ["t.deleted_at IS NULL"]
    params: list = []

    if date_from:
        where.append("t.occurred_at >= ?")
        params.append(date_from)
    if date_to:
        where.append("t.occurred_at <= ?")
        params.append(date_to)
    if category_id:
        where.append(
            "(t.category_id = ? OR t.category_id IN "
            "(SELECT id FROM categories WHERE parent_id = ?))"
        )
        params.extend([category_id, category_id])
    if place_id:
        where.append("t.place_id = ?")
        params.append(place_id)
    if item_id:
        where.append("t.item_id = ?")
        params.append(item_id)
    if wallet_id:
        where.append("(t.source_wallet_id = ? OR t.dest_wallet_id = ?)")
        params.extend([wallet_id, wallet_id])
    if tx_type and tx_type in ALLOWED_TYPES:
        where.append("t.type = ?")
        params.append(tx_type)
    if q:
        like = f"%{q.strip()}%"
        where.append(
            "(t.note LIKE ? OR i.canonical_name_en LIKE ? "
            "OR i.canonical_name_ar LIKE ? "
            "OR p.branch_name LIKE ? OR p.chain_name LIKE ?)"
        )
        params.extend([like, like, like, like, like])

    sort_sql = _SORT_SQL.get(sort, _SORT_SQL["date_desc"])

    page_size = max(1, min(int(page_size), 200))
    page = max(1, int(page))
    offset = (page - 1) * page_size

    where_sql = " AND ".join(where)

    count_sql = f"""
        SELECT COUNT(*)
        FROM transactions t
        LEFT JOIN items  i ON i.id = t.item_id
        LEFT JOIN places p ON p.id = t.place_id
        WHERE {where_sql}
    """

    rows_sql = f"""
        SELECT
            t.id, t.type, t.amount_cents, t.occurred_at, t.note,
            t.source_wallet_id, t.dest_wallet_id, t.category_id,
            t.item_id, t.place_id,
            c.name_en  AS category_name,  c.icon AS category_icon,
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
        WHERE {where_sql}
        ORDER BY {sort_sql}
        LIMIT ? OFFSET ?
    """

    async with aiosqlite.connect(db_uri(), uri=True) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(count_sql, params) as cur:
            total = (await cur.fetchone())[0]
        async with db.execute(rows_sql, params + [page_size, offset]) as cur:
            rows = [dict(r) for r in await cur.fetchall()]

    total_pages = max(1, (total + page_size - 1) // page_size)
    return {
        "total": total,
        "page": page,
        "page_size": page_size,
        "total_pages": total_pages,
        "rows": rows,
    }
