"""W8 reports + free-to-spend forecast."""
from datetime import datetime, timezone

import aiosqlite
import pytest


def _now_month() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m")


@pytest.mark.asyncio
async def test_monthly_summary_excludes_transfers(w4_db):
    """Transfers should not be counted as income or spend."""
    from src.writes import transactions as wt
    now = _now_month()
    # 1000 income, 300 spend, 500 transfer (should be ignored)
    await wt.insert_transaction(type="income", amount_cents=100000,
                                dest_wallet_id=1, occurred_at=f"{now}-10T12:00:00Z")
    await wt.insert_transaction(type="spend", amount_cents=30000,
                                source_wallet_id=1, occurred_at=f"{now}-11T12:00:00Z")
    await wt.insert_transaction(type="transfer", amount_cents=50000,
                                source_wallet_id=1, dest_wallet_id=2,
                                occurred_at=f"{now}-12T12:00:00Z")
    from src.queries import reports as r
    rows = await r.monthly_summary(months_back=1)
    assert len(rows) == 1
    assert rows[0]["income_cents"] == 100000
    assert rows[0]["spend_cents"] == 30000
    assert rows[0]["net_cents"] == 70000


@pytest.mark.asyncio
async def test_monthly_summary_refunds_subtract(w4_db):
    """Refunds reduce the spend total."""
    from src.writes import transactions as wt
    now = _now_month()
    await wt.insert_transaction(type="spend", amount_cents=50000,
                                source_wallet_id=1, occurred_at=f"{now}-10T12:00:00Z")
    spend_id = await wt.insert_transaction(type="spend", amount_cents=20000,
                                           source_wallet_id=1,
                                           occurred_at=f"{now}-11T12:00:00Z")
    await wt.insert_transaction(type="refund", amount_cents=10000,
                                dest_wallet_id=1, refund_of_id=spend_id,
                                occurred_at=f"{now}-12T12:00:00Z")
    from src.queries import reports as r
    rows = await r.monthly_summary(months_back=1)
    # 50000 + 20000 - 10000 = 60000
    assert rows[0]["spend_cents"] == 60000


@pytest.mark.asyncio
async def test_category_trend_pivots_to_series(w4_db):
    from src.writes import transactions as wt
    now = _now_month()
    await wt.insert_transaction(type="spend", amount_cents=3000,
                                source_wallet_id=1, category_id=1,
                                occurred_at=f"{now}-10T12:00:00Z")
    await wt.insert_transaction(type="spend", amount_cents=2000,
                                source_wallet_id=1, category_id=1,
                                occurred_at=f"{now}-15T12:00:00Z")
    from src.queries import reports as r
    trend = await r.category_trend(months_back=2)
    assert "Food" in trend["series"]
    # Should sum the two same-month-same-cat spends
    assert sum(trend["series"]["Food"]) == 5000
    assert trend["months"][-1] == now


@pytest.mark.asyncio
async def test_top_items_recent(w4_db):
    from src.writes import transactions as wt
    now_iso = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    await wt.insert_transaction(type="spend", amount_cents=5000,
                                source_wallet_id=1, item_id=1, place_id=1,
                                occurred_at=now_iso)
    await wt.insert_transaction(type="spend", amount_cents=3000,
                                source_wallet_id=1, item_id=1, place_id=1,
                                occurred_at=now_iso)
    from src.queries import reports as r
    items = await r.top_items_recent(days=90, limit=5)
    assert len(items) == 1
    assert items[0]["total_cents"] == 8000
    assert items[0]["tx_count"] == 2


@pytest.mark.asyncio
async def test_top_items_excludes_deleted_items(w4_db):
    from src.writes import transactions as wt, items as wi
    now_iso = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    await wt.insert_transaction(type="spend", amount_cents=5000,
                                source_wallet_id=1, item_id=1, place_id=1,
                                occurred_at=now_iso)
    await wi.soft_delete(1)
    from src.queries import reports as r
    items = await r.top_items_recent(days=90, limit=5)
    assert items == []


@pytest.mark.asyncio
async def test_free_to_spend_with_salary_day(w4_db):
    """User has salary_day=28, liquid balance from fixture is 150000.
    days_until = whatever; per_day = liquid // days_until."""
    from src.queries import reports as r
    async with aiosqlite.connect(w4_db) as db:
        await db.execute("UPDATE users SET salary_day = 28 WHERE user_id = 5904148250")
        await db.commit()
    fts = await r.free_to_spend(5904148250)
    assert fts["salary_day_configured"] is True
    assert fts["liquid_cents"] == 150000  # 100k bank + 50k cash, gold-only fixture has no gold
    assert fts["days_until_salary"] >= 1
    assert fts["per_day_cents"] == fts["liquid_cents"] // fts["days_until_salary"]


@pytest.mark.asyncio
async def test_free_to_spend_without_salary_day(w4_db):
    """Falls back to remaining days in current month."""
    from src.queries import reports as r
    async with aiosqlite.connect(w4_db) as db:
        await db.execute("UPDATE users SET salary_day = NULL WHERE user_id = 5904148250")
        await db.commit()
    fts = await r.free_to_spend(5904148250)
    assert fts["salary_day_configured"] is False
    assert fts["days_until_salary"] >= 1


@pytest.mark.asyncio
async def test_free_to_spend_uses_liquid_only(w4_db):
    """Gold wallet value is excluded from liquid (you can't spend the gold
    bar at the supermarket)."""
    from src.writes import wallets as ww
    async with aiosqlite.connect(w4_db) as db:
        await db.execute("UPDATE users SET salary_day = 15 WHERE user_id = 5904148250")
        await db.commit()
    await ww.insert_wallet(name_en="Gold 21k", type="asset_gold",
                           karat=21,
                           gold_grams_milligrams=10000,
                           gold_price_per_gram_cents=400000)
    from src.queries import reports as r
    fts = await r.free_to_spend(5904148250)
    # Still 150000 liquid — gold doesn't count
    assert fts["liquid_cents"] == 150000
