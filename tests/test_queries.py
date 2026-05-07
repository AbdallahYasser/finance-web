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


# ---------- Search (W2) ----------

@pytest_asyncio.fixture
async def search_db(finance_db):
    """Seed a richer dataset for search filter tests."""
    await _seed(finance_db,
        wallets=[
            {"name": "Bank",  "type": "bank", "initial": 1000000},
            {"name": "Cash",  "type": "cash", "initial": 50000},
            {"name": "VCash", "type": "e_wallet", "initial": 0},
        ],
        categories=[
            {"name": "Food",      "kind": "expense", "icon": "🍴"},  # id=1 (parent)
            {"name": "Transport", "kind": "expense", "icon": "🚗"},  # id=2
            {"name": "Salary",    "kind": "income",  "icon": "💰"},  # id=3
        ],
    )
    # Add a subcategory of Food (id=4)
    async with aiosqlite.connect(finance_db) as db:
        await db.execute(
            "INSERT INTO categories (name_en, parent_id, kind, icon) VALUES (?, ?, ?, ?)",
            ("Snacks", 1, "expense", "🍿"),
        )
        await db.execute(
            "INSERT INTO places (branch_name, chain_name) VALUES (?, ?)",
            ("7-Eleven Maadi", "7-Eleven"),
        )
        await db.execute(
            "INSERT INTO items (canonical_name_en, size) VALUES (?, ?)",
            ("Water bottle", "500ml"),
        )
        await db.commit()

    await _seed(finance_db, transactions=[
        # 5 spends across Food/Snacks/Transport, Bank/Cash, varied amounts
        {"type": "spend", "amount":  5000, "src": 1, "cat": 1, "at": "2026-04-10T10:00:00Z", "note": "lunch"},
        {"type": "spend", "amount":  3000, "src": 1, "cat": 4, "at": "2026-04-15T10:00:00Z", "note": "ice cream"},
        {"type": "spend", "amount":  2500, "src": 2, "cat": 2, "at": "2026-04-20T10:00:00Z", "note": "Uber"},
        {"type": "spend", "amount":  9000, "src": 1, "cat": 4, "at": "2026-04-25T10:00:00Z"},
        {"type": "spend", "amount":   500, "src": 2, "cat": 1, "at": "2026-05-01T10:00:00Z"},
        # 1 income
        {"type": "income", "amount": 800000, "dst": 1, "cat": 3, "at": "2026-04-28T10:00:00Z"},
        # 1 transfer
        {"type": "transfer", "amount": 100000, "src": 1, "dst": 2, "at": "2026-04-30T10:00:00Z"},
    ])
    # Item-tagged spend at 7-Eleven
    async with aiosqlite.connect(finance_db) as db:
        await db.execute(
            """INSERT INTO transactions
               (type, amount_cents, source_wallet_id, category_id, item_id, place_id, occurred_at, source)
               VALUES ('spend', 600, 2, 4, 1, 1, '2026-05-02T10:00:00Z', 'manual')""",
        )
        await db.commit()
    return finance_db


@pytest.mark.asyncio
async def test_search_default_returns_all(search_db):
    from src.queries import transactions as q
    r = await q.search()
    assert r["total"] == 8
    assert len(r["rows"]) == 8
    # Newest-first by default
    assert r["rows"][0]["amount_cents"] == 600  # 2026-05-02


@pytest.mark.asyncio
async def test_search_by_type(search_db):
    from src.queries import transactions as q
    assert (await q.search(tx_type="income"))["total"] == 1
    assert (await q.search(tx_type="transfer"))["total"] == 1
    assert (await q.search(tx_type="spend"))["total"] == 6


@pytest.mark.asyncio
async def test_search_by_wallet_matches_source_or_dest(search_db):
    from src.queries import transactions as q
    # Bank (id=1): 3 spends (src) + 1 income (dst) + 1 transfer (src) = 5
    assert (await q.search(wallet_id=1))["total"] == 5
    # Cash (id=2): 2 spends (src) + 1 transfer (dst) + 1 item-tagged spend (src) = 4
    assert (await q.search(wallet_id=2))["total"] == 4


@pytest.mark.asyncio
async def test_search_by_category_includes_children(search_db):
    from src.queries import transactions as q
    # Food (id=1) directly: 2 transactions (lunch + 500-spend)
    # Plus Snacks children (id=4): 3 transactions (ice cream, 9000, 600)
    # Total: 5
    r = await q.search(category_id=1)
    assert r["total"] == 5
    # Picking the Snacks child specifically returns 3
    r = await q.search(category_id=4)
    assert r["total"] == 3


@pytest.mark.asyncio
async def test_search_date_range(search_db):
    from src.queries import transactions as q
    # April only
    r = await q.search(date_from="2026-04-01T00:00:00Z", date_to="2026-04-30T23:59:59Z")
    assert r["total"] == 6
    # May only
    r = await q.search(date_from="2026-05-01T00:00:00Z")
    assert r["total"] == 2


@pytest.mark.asyncio
async def test_search_q_matches_note(search_db):
    from src.queries import transactions as q
    r = await q.search(q="ice cream")
    assert r["total"] == 1


@pytest.mark.asyncio
async def test_search_q_matches_place(search_db):
    from src.queries import transactions as q
    r = await q.search(q="7-Eleven")
    assert r["total"] == 1


@pytest.mark.asyncio
async def test_search_q_matches_item(search_db):
    from src.queries import transactions as q
    r = await q.search(q="Water")
    assert r["total"] == 1


@pytest.mark.asyncio
async def test_search_sort_amount_asc(search_db):
    from src.queries import transactions as q
    r = await q.search(sort="amount_asc", page_size=3)
    amounts = [row["amount_cents"] for row in r["rows"]]
    assert amounts == sorted(amounts)
    assert amounts[0] == 500


@pytest.mark.asyncio
async def test_search_sort_amount_desc(search_db):
    from src.queries import transactions as q
    r = await q.search(sort="amount_desc", page_size=3)
    amounts = [row["amount_cents"] for row in r["rows"]]
    assert amounts == sorted(amounts, reverse=True)
    assert amounts[0] == 800000  # the income


@pytest.mark.asyncio
async def test_search_pagination(search_db):
    from src.queries import transactions as q
    r1 = await q.search(page=1, page_size=3)
    r2 = await q.search(page=2, page_size=3)
    r3 = await q.search(page=3, page_size=3)
    assert r1["total"] == 8
    assert r1["total_pages"] == 3
    assert len(r1["rows"]) == 3
    assert len(r2["rows"]) == 3
    assert len(r3["rows"]) == 2
    # No overlap across pages
    ids = {r["id"] for r in r1["rows"] + r2["rows"] + r3["rows"]}
    assert len(ids) == 8


@pytest.mark.asyncio
async def test_search_combined_filters(search_db):
    from src.queries import transactions as q
    # Bank spends in April under Food (incl Snacks) → 3 (lunch, ice cream, 9000)
    r = await q.search(
        wallet_id=1, tx_type="spend",
        category_id=1,
        date_from="2026-04-01T00:00:00Z",
        date_to="2026-04-30T23:59:59Z",
    )
    assert r["total"] == 3


@pytest.mark.asyncio
async def test_search_page_size_clamped(search_db):
    from src.queries import transactions as q
    r = await q.search(page_size=5000)  # cap at 200
    assert r["page_size"] == 200


@pytest.mark.asyncio
async def test_search_unknown_type_ignored(search_db):
    from src.queries import transactions as q
    # tx_type='bogus' should NOT crash, just be ignored → return all 8
    r = await q.search(tx_type="bogus")
    assert r["total"] == 8


# ---------- Lookups ----------

@pytest.mark.asyncio
async def test_lookups_categories_tree(search_db):
    from src.queries import lookups as q
    cats = await q.categories_tree()
    parents = [c for c in cats if c["parent_id"] is None]
    children = [c for c in cats if c["parent_id"] is not None]
    assert len(parents) >= 3
    assert len(children) == 1
    assert children[0]["name_en"] == "Snacks"


@pytest.mark.asyncio
async def test_lookups_wallets_excludes_deleted(search_db):
    from src.queries import lookups as q
    async with aiosqlite.connect(search_db) as db:
        await db.execute("UPDATE wallets SET deleted_at = datetime('now') WHERE id = 3")
        await db.commit()
    ws = await q.wallets_list()
    assert {w["id"] for w in ws} == {1, 2}


@pytest.mark.asyncio
async def test_lookups_places_and_items(search_db):
    from src.queries import lookups as q
    places = await q.places_list()
    items = await q.items_list()
    assert len(places) == 1
    assert places[0]["branch_name"] == "7-Eleven Maadi"
    assert len(items) == 1
    assert items[0]["canonical_name_en"] == "Water bottle"
