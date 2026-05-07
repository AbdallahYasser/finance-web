"""Read-only query helpers — balance math + monthly aggregation + recent ordering."""
from datetime import datetime, timezone

import aiosqlite
import pytest
import pytest_asyncio


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


@pytest_asyncio.fixture
async def finance_db(monkeypatch):
    """A temp SQLite file with finance-bot's full schema (the parts we query)."""
    import tempfile
    from pathlib import Path

    tmpdir = tempfile.mkdtemp()
    db_path = str(Path(tmpdir) / "finance_bot.db")

    async with aiosqlite.connect(db_path) as db:
        # Subset of the bot's schema sufficient for our queries
        await db.execute("""
            CREATE TABLE wallets (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name_en TEXT, name_ar TEXT,
                type TEXT NOT NULL,
                initial_balance_cents INTEGER NOT NULL DEFAULT 0,
                karat INTEGER, gold_grams_milligrams INTEGER,
                gold_price_per_gram_cents INTEGER, gold_price_updated_at TEXT,
                created_at TEXT DEFAULT (datetime('now')),
                deleted_at TEXT
            )
        """)
        await db.execute("""
            CREATE TABLE categories (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                parent_id INTEGER,
                name_en TEXT, name_ar TEXT,
                kind TEXT NOT NULL DEFAULT 'expense',
                icon TEXT, is_default INTEGER DEFAULT 0,
                deleted_at TEXT
            )
        """)
        await db.execute("""
            CREATE TABLE places (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                branch_name TEXT, chain_name TEXT, deleted_at TEXT
            )
        """)
        await db.execute("""
            CREATE TABLE items (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                canonical_name_en TEXT, canonical_name_ar TEXT,
                size TEXT, unit TEXT, default_category_id INTEGER,
                deleted_at TEXT
            )
        """)
        await db.execute("""
            CREATE TABLE transactions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                type TEXT NOT NULL,
                amount_cents INTEGER NOT NULL CHECK (amount_cents > 0),
                source_wallet_id INTEGER, dest_wallet_id INTEGER,
                category_id INTEGER, item_id INTEGER, place_id INTEGER,
                refund_of_id INTEGER, occurred_at TEXT NOT NULL,
                note TEXT, source TEXT DEFAULT 'manual',
                created_at TEXT DEFAULT (datetime('now')),
                deleted_at TEXT
            )
        """)
        await db.commit()

    from src import config
    monkeypatch.setattr(config, "DB_PATH", db_path)
    return db_path


async def _seed(path: str, *, wallets=(), categories=(), transactions=()):
    async with aiosqlite.connect(path) as db:
        for w in wallets:
            await db.execute(
                """INSERT INTO wallets
                   (name_en, type, initial_balance_cents,
                    karat, gold_grams_milligrams, gold_price_per_gram_cents)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (w["name"], w["type"], w.get("initial", 0),
                 w.get("karat"), w.get("grams_mg"), w.get("price")),
            )
        for c in categories:
            await db.execute(
                "INSERT INTO categories (name_en, kind, icon) VALUES (?, ?, ?)",
                (c["name"], c.get("kind", "expense"), c.get("icon", "•")),
            )
        for t in transactions:
            await db.execute(
                """INSERT INTO transactions
                   (type, amount_cents, source_wallet_id, dest_wallet_id,
                    category_id, occurred_at, note)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (t["type"], t["amount"], t.get("src"), t.get("dst"),
                 t.get("cat"), t.get("at", _now()), t.get("note")),
            )
        await db.commit()


# ---------- Wallets / net worth ----------

@pytest.mark.asyncio
async def test_balance_initial_only(finance_db):
    await _seed(finance_db, wallets=[
        {"name": "Cash", "type": "cash", "initial": 100000},
    ])
    from src.queries import wallets as q
    rows = await q.list_with_balances()
    assert len(rows) == 1
    assert rows[0]["balance_cents"] == 100000


@pytest.mark.asyncio
async def test_balance_with_in_and_out(finance_db):
    await _seed(finance_db,
        wallets=[
            {"name": "Bank", "type": "bank", "initial": 1000000},
            {"name": "Cash", "type": "cash", "initial": 0},
        ],
        transactions=[
            {"type": "spend",    "amount": 25000, "src": 1},
            {"type": "income",   "amount": 500000, "dst": 1},
            {"type": "transfer", "amount": 100000, "src": 1, "dst": 2},
        ],
    )
    from src.queries import wallets as q
    by_id = {w["id"]: w for w in await q.list_with_balances()}
    assert by_id[1]["balance_cents"] == 1000000 - 25000 + 500000 - 100000
    assert by_id[2]["balance_cents"] == 100000


@pytest.mark.asyncio
async def test_soft_deleted_wallet_excluded(finance_db):
    await _seed(finance_db, wallets=[
        {"name": "Old", "type": "cash", "initial": 50000},
    ])
    async with aiosqlite.connect(finance_db) as db:
        await db.execute("UPDATE wallets SET deleted_at = datetime('now') WHERE id = 1")
        await db.commit()

    from src.queries import wallets as q
    rows = await q.list_with_balances()
    assert rows == []
    assert await q.net_worth_cents() == 0


@pytest.mark.asyncio
async def test_net_worth_includes_gold(finance_db):
    # 10g of gold @ 4000 EGP/g = 40,000 EGP = 4_000_000 cents
    await _seed(finance_db, wallets=[
        {"name": "Bank", "type": "bank", "initial": 500000},
        {"name": "Gold", "type": "asset_gold", "initial": 0,
         "karat": 21, "grams_mg": 10000, "price": 400000},
    ])
    from src.queries import wallets as q
    nw = await q.net_worth_cents()
    assert nw == 500000 + 4_000_000


# ---------- Recent transactions ----------

@pytest.mark.asyncio
async def test_recent_returns_newest_first(finance_db):
    await _seed(finance_db,
        wallets=[{"name": "Cash", "type": "cash", "initial": 0}],
        transactions=[
            {"type": "spend", "amount": 100, "src": 1, "at": "2026-05-01T10:00:00Z"},
            {"type": "spend", "amount": 200, "src": 1, "at": "2026-05-03T10:00:00Z"},
            {"type": "spend", "amount": 300, "src": 1, "at": "2026-05-02T10:00:00Z"},
        ],
    )
    from src.queries import transactions as q
    rows = await q.recent(limit=10)
    assert [r["amount_cents"] for r in rows] == [200, 300, 100]


@pytest.mark.asyncio
async def test_recent_excludes_soft_deleted(finance_db):
    await _seed(finance_db,
        wallets=[{"name": "Cash", "type": "cash", "initial": 0}],
        transactions=[
            {"type": "spend", "amount": 100, "src": 1},
            {"type": "spend", "amount": 200, "src": 1},
        ],
    )
    async with aiosqlite.connect(finance_db) as db:
        await db.execute("UPDATE transactions SET deleted_at = datetime('now') WHERE id = 1")
        await db.commit()
    from src.queries import transactions as q
    rows = await q.recent(limit=10)
    assert len(rows) == 1
    assert rows[0]["amount_cents"] == 200


@pytest.mark.asyncio
async def test_recent_joins_category(finance_db):
    await _seed(finance_db,
        wallets=[{"name": "Cash", "type": "cash", "initial": 0}],
        categories=[{"name": "Food", "icon": "🍴"}],
        transactions=[{"type": "spend", "amount": 100, "src": 1, "cat": 1}],
    )
    from src.queries import transactions as q
    rows = await q.recent(limit=1)
    assert rows[0]["category_name"] == "Food"
    assert rows[0]["category_icon"] == "🍴"


# ---------- Monthly aggregation ----------

@pytest.mark.asyncio
async def test_monthly_aggregation(finance_db):
    now = datetime.now(timezone.utc)
    this_month = now.strftime("%Y-%m")
    last_month_dt = datetime(now.year, now.month, 1, tzinfo=timezone.utc).replace(
        month=now.month - 1 if now.month > 1 else 12,
        year=now.year if now.month > 1 else now.year - 1,
    )
    last_month = last_month_dt.strftime("%Y-%m")

    await _seed(finance_db,
        wallets=[{"name": "Cash", "type": "cash", "initial": 0}],
        categories=[
            {"name": "Food", "icon": "🍴"},
            {"name": "Transport", "icon": "🚗"},
        ],
        transactions=[
            # This month
            {"type": "spend", "amount": 5000, "src": 1, "cat": 1, "at": f"{this_month}-15T10:00:00Z"},
            {"type": "spend", "amount": 3000, "src": 1, "cat": 2, "at": f"{this_month}-16T10:00:00Z"},
            {"type": "spend", "amount": 2000, "src": 1, "cat": 1, "at": f"{this_month}-17T10:00:00Z"},
            # Last month — should be excluded
            {"type": "spend", "amount": 9999, "src": 1, "cat": 1, "at": f"{last_month}-15T10:00:00Z"},
            # Income/transfer should be excluded
            {"type": "income", "amount": 50000, "dst": 1, "cat": None, "at": f"{this_month}-10T10:00:00Z"},
        ],
    )
    from src.queries import transactions as q
    rows = await q.this_month_by_category()
    by_cat = {r["category_name"]: r["total_cents"] for r in rows}
    assert by_cat == {"Food": 7000, "Transport": 3000}


@pytest.mark.asyncio
async def test_monthly_refunds_subtract(finance_db):
    now = datetime.now(timezone.utc).strftime("%Y-%m")
    await _seed(finance_db,
        wallets=[{"name": "Cash", "type": "cash", "initial": 0}],
        categories=[{"name": "Shopping", "icon": "🛍"}],
        transactions=[
            {"type": "spend",  "amount": 5000, "src": 1, "cat": 1, "at": f"{now}-10T10:00:00Z"},
            {"type": "refund", "amount": 5000, "dst": 1, "cat": 1, "at": f"{now}-11T10:00:00Z"},
        ],
    )
    from src.queries import transactions as q
    rows = await q.this_month_by_category()
    # Spend 5000 − refund 5000 = 0 → row filtered out by HAVING > 0
    assert rows == []
