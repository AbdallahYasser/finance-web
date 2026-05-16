"""Reports + free-to-spend forecast queries."""
from calendar import monthrange
from datetime import date, datetime, timedelta, timezone

import aiosqlite
import pytz

from src import config
from src.db import db_uri


def _local_tz():
    return pytz.timezone(config.TIMEZONE)


def _walk_months(months_back: int) -> list[tuple[int, int]]:
    """Return [(year, month), ...] oldest → newest spanning `months_back` months
    inclusive of the current month."""
    tz = _local_tz()
    now = datetime.now(tz)
    out: list[tuple[int, int]] = []
    for i in range(months_back - 1, -1, -1):
        year, month = now.year, now.month - i
        while month <= 0:
            month += 12
            year -= 1
        out.append((year, month))
    return out


def _month_bounds_iso(year: int, month: int) -> tuple[str, str]:
    """UTC-ISO start and end (exclusive) for the given local-month."""
    start = f"{year:04d}-{month:02d}-01T00:00:00Z"
    if month == 12:
        ny, nm = year + 1, 1
    else:
        ny, nm = year, month + 1
    end = f"{ny:04d}-{nm:02d}-01T00:00:00Z"
    return start, end


async def monthly_summary(months_back: int = 6) -> list[dict]:
    """For each of the last N months: income, spend, net savings."""
    months = _walk_months(months_back)
    out: list[dict] = []
    async with aiosqlite.connect(db_uri(), uri=True) as db:
        for (year, month) in months:
            start, end = _month_bounds_iso(year, month)
            async with db.execute(
                """
                SELECT
                    COALESCE(SUM(CASE WHEN type='income' THEN amount_cents ELSE 0 END), 0)
                      AS income,
                    COALESCE(SUM(CASE WHEN type='spend'  THEN amount_cents ELSE 0 END), 0)
                    - COALESCE(SUM(CASE WHEN type='refund' THEN amount_cents ELSE 0 END), 0)
                      AS spend
                FROM transactions
                WHERE deleted_at IS NULL
                  AND occurred_at >= ? AND occurred_at < ?
                """,
                (start, end),
            ) as cur:
                row = await cur.fetchone()
                income = row[0] or 0
                spend = max(0, row[1] or 0)
            out.append({
                "month": f"{year:04d}-{month:02d}",
                "income_cents": income,
                "spend_cents": spend,
                "net_cents": income - spend,
            })
    return out


async def category_trend(months_back: int = 6) -> dict:
    """Per-month, per-category spend totals (for a stacked bar chart).

    Returns:
      {
        months: ['YYYY-MM', ...],   # axis labels
        categories: [{id, name, icon}, ...],
        series: { '<cat_name>': [cents_jan, cents_feb, ...] }
      }
    """
    months = [f"{y:04d}-{m:02d}" for (y, m) in _walk_months(months_back)]
    earliest_start = f"{months[0]}-01T00:00:00Z"

    async with aiosqlite.connect(db_uri(), uri=True) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            """
            SELECT
                strftime('%Y-%m', t.occurred_at) AS month,
                COALESCE(c.id, 0) AS category_id,
                COALESCE(c.name_en, 'Uncategorized') AS category_name,
                COALESCE(c.icon, '•') AS category_icon,
                SUM(CASE WHEN t.type='spend'  THEN t.amount_cents ELSE 0 END)
                  - SUM(CASE WHEN t.type='refund' THEN t.amount_cents ELSE 0 END)
                  AS total_cents
            FROM transactions t
            LEFT JOIN categories c ON c.id = t.category_id
            WHERE t.deleted_at IS NULL
              AND t.type IN ('spend','refund')
              AND t.occurred_at >= ?
            GROUP BY month, COALESCE(c.id, 0)
            HAVING total_cents > 0
            ORDER BY month
            """,
            (earliest_start,),
        ) as cur:
            rows = [dict(r) for r in await cur.fetchall()]

    # Pivot to series
    cat_meta: dict[str, dict] = {}
    series: dict[str, list[int]] = {}
    for r in rows:
        name = r["category_name"]
        if name not in series:
            series[name] = [0] * len(months)
            cat_meta[name] = {"name": name, "icon": r["category_icon"]}
        if r["month"] in months:
            idx = months.index(r["month"])
            series[name][idx] = r["total_cents"]

    # Order categories by total (desc) so the chart legend reads top-down
    order = sorted(series.keys(), key=lambda k: -sum(series[k]))
    return {
        "months": months,
        "categories": [cat_meta[n] for n in order],
        "series": {n: series[n] for n in order},
    }


async def top_items_recent(days: int = 90, limit: int = 5) -> list[dict]:
    cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).strftime(
        "%Y-%m-%dT%H:%M:%SZ"
    )
    async with aiosqlite.connect(db_uri(), uri=True) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            """
            SELECT
                i.id, i.canonical_name_en AS name_en,
                i.canonical_name_ar AS name_ar, i.size,
                COUNT(*) AS tx_count,
                COALESCE(SUM(CASE WHEN t.type='spend' THEN t.amount_cents
                                  WHEN t.type='refund' THEN -t.amount_cents
                                  ELSE 0 END), 0) AS total_cents
            FROM transactions t
            JOIN items i ON i.id = t.item_id
            WHERE t.deleted_at IS NULL
              AND t.type IN ('spend','refund')
              AND t.occurred_at >= ?
              AND i.deleted_at IS NULL
            GROUP BY i.id
            HAVING total_cents > 0
            ORDER BY total_cents DESC
            LIMIT ?
            """,
            (cutoff, limit),
        ) as cur:
            return [dict(r) for r in await cur.fetchall()]


async def top_places_recent(days: int = 90, limit: int = 5) -> list[dict]:
    cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).strftime(
        "%Y-%m-%dT%H:%M:%SZ"
    )
    async with aiosqlite.connect(db_uri(), uri=True) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            """
            SELECT
                p.id, p.branch_name, p.chain_name,
                COUNT(*) AS tx_count,
                COALESCE(SUM(CASE WHEN t.type='spend' THEN t.amount_cents
                                  WHEN t.type='refund' THEN -t.amount_cents
                                  ELSE 0 END), 0) AS total_cents
            FROM transactions t
            JOIN places p ON p.id = t.place_id
            WHERE t.deleted_at IS NULL
              AND t.type IN ('spend','refund')
              AND t.occurred_at >= ?
              AND p.deleted_at IS NULL
            GROUP BY p.id
            HAVING total_cents > 0
            ORDER BY total_cents DESC
            LIMIT ?
            """,
            (cutoff, limit),
        ) as cur:
            return [dict(r) for r in await cur.fetchall()]


async def free_to_spend(user_id: int) -> dict:
    """How much you can spend per day until your next paycheck.

    Strategy:
      - liquid_cents = sum of cash + bank + e_wallet wallet balances.
      - next_salary_date = next occurrence of `users.salary_day`
        (clamped to last-day-of-month for short months).
      - days_until = (next_salary_date - today_in_cairo).days
      - per_day = liquid_cents // max(days_until, 1)

    If salary_day isn't set, falls back to "remaining days in this month".
    """
    tz = _local_tz()
    today = datetime.now(tz).date()

    async with aiosqlite.connect(db_uri(), uri=True) as db:
        async with db.execute(
            "SELECT salary_day FROM users WHERE user_id = ?", (user_id,)
        ) as cur:
            row = await cur.fetchone()
            salary_day = row[0] if row else None

    if not salary_day or not (1 <= salary_day <= 31):
        # Fallback: remainder of current calendar month
        if today.month == 12:
            next_date = date(today.year + 1, 1, 1)
        else:
            next_date = date(today.year, today.month + 1, 1)
        salary_known = False
    else:
        def _clamp(y: int, m: int, d: int) -> int:
            return min(d, monthrange(y, m)[1])

        this_month_target = date(
            today.year, today.month, _clamp(today.year, today.month, salary_day)
        )
        if this_month_target > today:
            next_date = this_month_target
        else:
            if today.month == 12:
                ny, nm = today.year + 1, 1
            else:
                ny, nm = today.year, today.month + 1
            next_date = date(ny, nm, _clamp(ny, nm, salary_day))
        salary_known = True

    days_until = max((next_date - today).days, 1)

    # Liquid balance
    from src.queries import wallets as qw
    total_liquid = 0
    for w in await qw.list_with_balances():
        if w["type"] in ("cash", "bank", "e_wallet"):
            total_liquid += w["balance_cents"]

    per_day = total_liquid // days_until if days_until > 0 else 0

    return {
        "next_salary_date": next_date.strftime("%Y-%m-%d"),
        "days_until_salary": days_until,
        "liquid_cents": total_liquid,
        "per_day_cents": per_day,
        "salary_day_configured": salary_known,
    }
