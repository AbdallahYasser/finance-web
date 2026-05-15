"""W7 debt lifecycle — lend / repay / forgive / net worth math."""
import aiosqlite
import pytest
import pytest_asyncio


@pytest_asyncio.fixture
async def debt_db(w4_db):
    """Re-use w4_db and add the W7 people + debts tables."""
    async with aiosqlite.connect(w4_db) as db:
        await db.execute("""
            CREATE TABLE people (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                telegram_username TEXT, phone TEXT, note TEXT,
                created_at TEXT DEFAULT (datetime('now')),
                deleted_at TEXT
            )
        """)
        await db.execute("""
            CREATE TABLE debts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                person_id INTEGER NOT NULL,
                direction TEXT NOT NULL CHECK (direction IN ('lent','borrowed')),
                original_amount_cents INTEGER NOT NULL CHECK (original_amount_cents > 0),
                opened_at TEXT NOT NULL,
                due_at TEXT,
                status TEXT NOT NULL DEFAULT 'open' CHECK (status IN ('open','partial','closed','forgiven')),
                note TEXT,
                created_at TEXT DEFAULT (datetime('now'))
            )
        """)
        await db.execute("INSERT INTO people (name) VALUES (?)", ("Ahmed",))
        await db.execute("INSERT INTO people (name) VALUES (?)", ("Sara",))
        await db.commit()
    return w4_db


@pytest.mark.asyncio
async def test_lend_creates_debt_and_transaction(debt_db):
    from src.writes import debts as w
    debt_id = await w.insert_debt(
        person_id=1, direction="lent", amount_cents=100000, wallet_id=1,
    )
    async with aiosqlite.connect(debt_db) as db:
        async with db.execute("SELECT status, original_amount_cents FROM debts WHERE id = ?",
                              (debt_id,)) as cur:
            (status, orig) = await cur.fetchone()
        async with db.execute(
            "SELECT type, source_wallet_id, dest_wallet_id, debt_id, person_id "
            "FROM transactions WHERE debt_id = ?",
            (debt_id,),
        ) as cur:
            tx = await cur.fetchone()
    assert status == "open"
    assert orig == 100000
    assert tx == ("lend", 1, None, debt_id, 1)


@pytest.mark.asyncio
async def test_borrow_creates_correct_transaction(debt_db):
    from src.writes import debts as w
    debt_id = await w.insert_debt(
        person_id=2, direction="borrowed", amount_cents=50000, wallet_id=2,
    )
    async with aiosqlite.connect(debt_db) as db:
        async with db.execute(
            "SELECT type, source_wallet_id, dest_wallet_id FROM transactions WHERE debt_id = ?",
            (debt_id,),
        ) as cur:
            tx = await cur.fetchone()
    # borrow = money into a wallet, no source
    assert tx == ("borrow", None, 2)


@pytest.mark.asyncio
async def test_partial_repay_keeps_open_partial(debt_db):
    from src.writes import debts as w
    debt_id = await w.insert_debt(
        person_id=1, direction="lent", amount_cents=1000, wallet_id=1,
    )
    await w.repay(debt_id=debt_id, amount_cents=400, wallet_id=1)
    async with aiosqlite.connect(debt_db) as db:
        async with db.execute("SELECT status FROM debts WHERE id = ?", (debt_id,)) as cur:
            (status,) = await cur.fetchone()
    assert status == "partial"


@pytest.mark.asyncio
async def test_full_repay_closes_debt(debt_db):
    from src.writes import debts as w
    debt_id = await w.insert_debt(
        person_id=1, direction="lent", amount_cents=1000, wallet_id=1,
    )
    await w.repay(debt_id=debt_id, amount_cents=400, wallet_id=1)
    await w.repay(debt_id=debt_id, amount_cents=600, wallet_id=1)
    async with aiosqlite.connect(debt_db) as db:
        async with db.execute("SELECT status FROM debts WHERE id = ?", (debt_id,)) as cur:
            (status,) = await cur.fetchone()
    assert status == "closed"


@pytest.mark.asyncio
async def test_repay_exceeds_remaining_rejected(debt_db):
    from src.writes import debts as w
    debt_id = await w.insert_debt(
        person_id=1, direction="lent", amount_cents=1000, wallet_id=1,
    )
    with pytest.raises(ValueError):
        await w.repay(debt_id=debt_id, amount_cents=2000, wallet_id=1)


@pytest.mark.asyncio
async def test_forgive_writes_transaction_and_marks_forgiven(debt_db):
    from src.writes import debts as w
    debt_id = await w.insert_debt(
        person_id=1, direction="lent", amount_cents=1000, wallet_id=1,
    )
    await w.repay(debt_id=debt_id, amount_cents=300, wallet_id=1)
    await w.forgive(debt_id=debt_id)
    async with aiosqlite.connect(debt_db) as db:
        async with db.execute("SELECT status FROM debts WHERE id = ?", (debt_id,)) as cur:
            (status,) = await cur.fetchone()
        async with db.execute(
            "SELECT amount_cents FROM transactions WHERE debt_id = ? AND type = 'forgive'",
            (debt_id,),
        ) as cur:
            (amt,) = await cur.fetchone()
    assert status == "forgiven"
    assert amt == 700  # remaining at time of forgive


@pytest.mark.asyncio
async def test_cannot_repay_forgiven_or_closed(debt_db):
    from src.writes import debts as w
    debt_id = await w.insert_debt(
        person_id=1, direction="lent", amount_cents=1000, wallet_id=1,
    )
    await w.forgive(debt_id=debt_id)
    with pytest.raises(ValueError):
        await w.repay(debt_id=debt_id, amount_cents=100, wallet_id=1)


@pytest.mark.asyncio
async def test_person_balance_aggregation(debt_db):
    from src.writes import debts as w
    # Lent Ahmed 1000, he repaid 400 → 600 receivable
    debt_a = await w.insert_debt(person_id=1, direction="lent",
                                 amount_cents=1000, wallet_id=1)
    await w.repay(debt_id=debt_a, amount_cents=400, wallet_id=1)
    # Borrowed from Sara 500 → 500 payable (negative balance)
    await w.insert_debt(person_id=2, direction="borrowed",
                        amount_cents=500, wallet_id=2)

    from src.queries import people as qp
    rows = await qp.list_with_balances()
    by_name = {r["name"]: r for r in rows}
    assert by_name["Ahmed"]["balance_cents"] == 600
    assert by_name["Sara"]["balance_cents"] == -500


@pytest.mark.asyncio
async def test_forgiven_debt_excluded_from_person_balance(debt_db):
    from src.writes import debts as w
    debt_id = await w.insert_debt(person_id=1, direction="lent",
                                  amount_cents=1000, wallet_id=1)
    await w.forgive(debt_id=debt_id)

    from src.queries import people as qp
    rows = await qp.list_with_balances()
    by_name = {r["name"]: r for r in rows}
    assert by_name["Ahmed"]["balance_cents"] == 0


@pytest.mark.asyncio
async def test_net_worth_includes_debts(debt_db):
    from src.writes import debts as w
    # Start: Bank 100000 + Cash 50000 = 150000
    # Lent 30000 → wallet drops by 30000 to 70000+50000=120000
    #            → +30000 receivable. Net = 150000.
    await w.insert_debt(person_id=1, direction="lent",
                        amount_cents=30000, wallet_id=1)
    from src.queries import wallets as qw
    nw = await qw.net_worth_cents()
    assert nw == 150000  # liquid 120000 + receivable 30000

    # Borrow 10000 → wallet up to 160000, payable 10000
    await w.insert_debt(person_id=2, direction="borrowed",
                        amount_cents=10000, wallet_id=2)
    nw = await qw.net_worth_cents()
    # liquid: bank 70000 + cash 50000+10000 = 130000
    # + receivable 30000 - payable 10000 = 150000
    assert nw == 150000
