"""Read-only item queries: summary list + per-item detail with price history."""
import aiosqlite

from src.db import db_uri


async def list_summary() -> list[dict]:
    """All active items with aggregate stats from item_prices and transactions.

    Returns one row per item with:
        id, name_en, name_ar, size, unit,
        tx_count          — how many transactions referenced this item
        total_spent_cents — sum of amount_cents across spend transactions
        last_observed_at  — most recent item_prices.observed_at
        last_price_cents  — price at the most recent observation
        place_count       — distinct places where this item was bought
    """
    async with aiosqlite.connect(db_uri(), uri=True) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            """
            SELECT
                i.id,
                i.canonical_name_en AS name_en,
                i.canonical_name_ar AS name_ar,
                i.size,
                i.unit,
                COALESCE(tx.tx_count, 0)          AS tx_count,
                COALESCE(tx.total_spent_cents, 0) AS total_spent_cents,
                pr.last_observed_at,
                pr.last_price_cents,
                COALESCE(pr.place_count, 0)       AS place_count
            FROM items i
            LEFT JOIN (
                SELECT item_id,
                       COUNT(*) AS tx_count,
                       SUM(CASE WHEN type='spend' THEN amount_cents
                                WHEN type='refund' THEN -amount_cents
                                ELSE 0 END) AS total_spent_cents
                FROM transactions
                WHERE deleted_at IS NULL AND item_id IS NOT NULL
                GROUP BY item_id
            ) tx ON tx.item_id = i.id
            LEFT JOIN (
                SELECT
                    p.item_id,
                    MAX(p.observed_at) AS last_observed_at,
                    (SELECT price_cents FROM item_prices p2
                     WHERE p2.item_id = p.item_id
                     ORDER BY p2.observed_at DESC, p2.id DESC LIMIT 1) AS last_price_cents,
                    COUNT(DISTINCT p.place_id) AS place_count
                FROM item_prices p
                GROUP BY p.item_id
            ) pr ON pr.item_id = i.id
            WHERE i.deleted_at IS NULL
            ORDER BY (pr.last_observed_at IS NULL), pr.last_observed_at DESC, i.id DESC
            """
        ) as cur:
            return [dict(r) for r in await cur.fetchall()]


async def get_detail(item_id: int) -> dict | None:
    """One item with full price history grouped by place + summary stats.

    Returns:
        {
          item: {id, name_en, name_ar, size, unit, default_category_id},
          places: [
             {place_id, branch_name, chain_name,
              observation_count, min_cents, max_cents, last_cents,
              observations: [{observed_at, price_cents, on_sale, transaction_id}]
             }, ...
          ],
          summary: {total_spent_cents, tx_count, place_count,
                    overall_min_cents, overall_max_cents, overall_avg_cents}
        }
    """
    async with aiosqlite.connect(db_uri(), uri=True) as db:
        db.row_factory = aiosqlite.Row

        async with db.execute(
            """
            SELECT id, canonical_name_en AS name_en, canonical_name_ar AS name_ar,
                   size, unit, default_category_id
            FROM items WHERE id = ? AND deleted_at IS NULL
            """,
            (item_id,),
        ) as cur:
            item_row = await cur.fetchone()
            if not item_row:
                return None
            item = dict(item_row)

        async with db.execute(
            """
            SELECT pr.id, pr.observed_at, pr.price_cents, pr.on_sale,
                   pr.transaction_id, pr.place_id,
                   pl.branch_name, pl.chain_name
            FROM item_prices pr
            LEFT JOIN places pl ON pl.id = pr.place_id
            WHERE pr.item_id = ?
            ORDER BY pr.place_id, pr.observed_at ASC, pr.id ASC
            """,
            (item_id,),
        ) as cur:
            obs_rows = [dict(r) for r in await cur.fetchall()]

        async with db.execute(
            """
            SELECT
                COUNT(*) AS tx_count,
                COALESCE(SUM(CASE WHEN type='spend' THEN amount_cents
                                  WHEN type='refund' THEN -amount_cents
                                  ELSE 0 END), 0) AS total_spent_cents
            FROM transactions
            WHERE item_id = ? AND deleted_at IS NULL
            """,
            (item_id,),
        ) as cur:
            tx_summary = dict(await cur.fetchone())

    # Group observations per place
    places_map: dict[int, dict] = {}
    for o in obs_rows:
        pid = o["place_id"]
        if pid not in places_map:
            places_map[pid] = {
                "place_id": pid,
                "branch_name": o["branch_name"],
                "chain_name": o["chain_name"],
                "observations": [],
            }
        places_map[pid]["observations"].append({
            "observed_at":     o["observed_at"],
            "price_cents":     o["price_cents"],
            "on_sale":         o["on_sale"],
            "transaction_id":  o["transaction_id"],
        })

    places: list[dict] = []
    overall_min = overall_max = None
    overall_sum = overall_count = 0
    for pid, p in places_map.items():
        prices = [obs["price_cents"] for obs in p["observations"]]
        p["observation_count"] = len(prices)
        p["min_cents"] = min(prices) if prices else None
        p["max_cents"] = max(prices) if prices else None
        p["last_cents"] = p["observations"][-1]["price_cents"] if prices else None
        if prices:
            overall_min = min(prices) if overall_min is None else min(overall_min, min(prices))
            overall_max = max(prices) if overall_max is None else max(overall_max, max(prices))
            overall_sum += sum(prices)
            overall_count += len(prices)
        places.append(p)

    # Sort places by most-recent observation
    places.sort(
        key=lambda p: p["observations"][-1]["observed_at"] if p["observations"] else "",
        reverse=True,
    )

    summary = {
        "tx_count":          tx_summary["tx_count"],
        "total_spent_cents": tx_summary["total_spent_cents"],
        "place_count":       len(places),
        "overall_min_cents": overall_min,
        "overall_max_cents": overall_max,
        "overall_avg_cents": (overall_sum // overall_count) if overall_count else None,
    }

    return {"item": item, "places": places, "summary": summary}
