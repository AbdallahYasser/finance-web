"""Transaction write helpers — happy paths, validation, item-prices side-effect."""
import aiosqlite
import pytest

# `w4_db` fixture lives in conftest.py


# ---------- Insert ----------

@pytest.mark.asyncio
async def test_insert_spend_basic(w4_db):
    from src.writes import transactions as w
    tx_id = await w.insert_transaction(
        type="spend", amount_cents=500, source_wallet_id=1, category_id=1,
    )
    assert tx_id > 0


@pytest.mark.asyncio
async def test_insert_spend_writes_item_price(w4_db):
    """When item_id and place_id are both set on a spend, item_prices gets a row."""
    from src.writes import transactions as w
    tx_id = await w.insert_transaction(
        type="spend", amount_cents=500, source_wallet_id=1, category_id=1,
        item_id=1, place_id=1,
    )
    async with aiosqlite.connect(w4_db) as db:
        async with db.execute(
            "SELECT item_id, place_id, price_cents, transaction_id FROM item_prices "
            "WHERE transaction_id = ?", (tx_id,)
        ) as cur:
            row = await cur.fetchone()
    assert row == (1, 1, 500, tx_id)


@pytest.mark.asyncio
async def test_insert_spend_no_item_price_when_only_place(w4_db):
    from src.writes import transactions as w
    tx_id = await w.insert_transaction(
        type="spend", amount_cents=500, source_wallet_id=1, category_id=1,
        place_id=1,
    )
    async with aiosqlite.connect(w4_db) as db:
        async with db.execute(
            "SELECT COUNT(*) FROM item_prices WHERE transaction_id = ?", (tx_id,)
        ) as cur:
            n = (await cur.fetchone())[0]
    assert n == 0


@pytest.mark.asyncio
async def test_insert_income_writes_no_item_price(w4_db):
    """Income with item_id+place_id should NOT create a price observation."""
    from src.writes import transactions as w
    tx_id = await w.insert_transaction(
        type="income", amount_cents=5000, dest_wallet_id=1,
        item_id=1, place_id=1,
    )
    async with aiosqlite.connect(w4_db) as db:
        async with db.execute(
            "SELECT COUNT(*) FROM item_prices WHERE transaction_id = ?", (tx_id,)
        ) as cur:
            n = (await cur.fetchone())[0]
    assert n == 0


@pytest.mark.asyncio
async def test_insert_transfer(w4_db):
    from src.writes import transactions as w
    tx_id = await w.insert_transaction(
        type="transfer", amount_cents=1000, source_wallet_id=1, dest_wallet_id=2,
    )
    assert tx_id > 0


@pytest.mark.asyncio
async def test_insert_refund(w4_db):
    from src.writes import transactions as w
    spend_id = await w.insert_transaction(
        type="spend", amount_cents=500, source_wallet_id=1, category_id=1,
    )
    refund_id = await w.insert_transaction(
        type="refund", amount_cents=500, dest_wallet_id=1, refund_of_id=spend_id,
    )
    assert refund_id > spend_id


# ---------- Validation ----------

@pytest.mark.asyncio
async def test_insert_negative_amount_rejected(w4_db):
    from src.writes import transactions as w
    with pytest.raises(ValueError):
        await w.insert_transaction(type="spend", amount_cents=-1, source_wallet_id=1)


@pytest.mark.asyncio
async def test_insert_zero_amount_rejected(w4_db):
    from src.writes import transactions as w
    with pytest.raises(ValueError):
        await w.insert_transaction(type="spend", amount_cents=0, source_wallet_id=1)


@pytest.mark.asyncio
async def test_insert_spend_without_source_rejected(w4_db):
    from src.writes import transactions as w
    with pytest.raises(ValueError):
        await w.insert_transaction(type="spend", amount_cents=500)


@pytest.mark.asyncio
async def test_insert_income_without_dest_rejected(w4_db):
    from src.writes import transactions as w
    with pytest.raises(ValueError):
        await w.insert_transaction(type="income", amount_cents=500)


@pytest.mark.asyncio
async def test_insert_transfer_same_wallet_rejected(w4_db):
    from src.writes import transactions as w
    with pytest.raises(ValueError):
        await w.insert_transaction(
            type="transfer", amount_cents=500,
            source_wallet_id=1, dest_wallet_id=1,
        )


@pytest.mark.asyncio
async def test_insert_refund_without_refund_of_rejected(w4_db):
    from src.writes import transactions as w
    with pytest.raises(ValueError):
        await w.insert_transaction(type="refund", amount_cents=500, dest_wallet_id=1)


@pytest.mark.asyncio
async def test_insert_unknown_type_rejected(w4_db):
    from src.writes import transactions as w
    with pytest.raises(ValueError):
        await w.insert_transaction(type="bogus", amount_cents=500, source_wallet_id=1)


# ---------- Update ----------

@pytest.mark.asyncio
async def test_update_partial_fields(w4_db):
    from src.writes import transactions as w
    tx_id = await w.insert_transaction(
        type="spend", amount_cents=500, source_wallet_id=1, category_id=1,
        note="initial",
    )
    ok = await w.update_transaction(tx_id, amount_cents=750, note="updated")
    assert ok is True
    async with aiosqlite.connect(w4_db) as db:
        async with db.execute(
            "SELECT amount_cents, note, source_wallet_id, category_id FROM transactions WHERE id = ?",
            (tx_id,),
        ) as cur:
            row = await cur.fetchone()
    assert row == (750, "updated", 1, 1)  # source_wallet + category preserved


@pytest.mark.asyncio
async def test_update_does_not_create_new_item_price(w4_db):
    """Updating an existing tx must NOT add a new item_prices row — historical
    observations stay immutable."""
    from src.writes import transactions as w
    tx_id = await w.insert_transaction(
        type="spend", amount_cents=500, source_wallet_id=1, category_id=1,
        item_id=1, place_id=1,
    )
    async with aiosqlite.connect(w4_db) as db:
        async with db.execute(
            "SELECT COUNT(*) FROM item_prices WHERE transaction_id = ?", (tx_id,)
        ) as cur:
            n_before = (await cur.fetchone())[0]
    await w.update_transaction(tx_id, amount_cents=600)
    async with aiosqlite.connect(w4_db) as db:
        async with db.execute(
            "SELECT COUNT(*) FROM item_prices WHERE transaction_id = ?", (tx_id,)
        ) as cur:
            n_after = (await cur.fetchone())[0]
    assert n_before == 1
    assert n_after == 1  # untouched


@pytest.mark.asyncio
async def test_update_unknown_field_rejected(w4_db):
    from src.writes import transactions as w
    with pytest.raises(ValueError):
        await w.update_transaction(1, deleted_at="2020-01-01")


@pytest.mark.asyncio
async def test_update_missing_returns_false(w4_db):
    from src.writes import transactions as w
    ok = await w.update_transaction(99999, note="x")
    assert ok is False


@pytest.mark.asyncio
async def test_update_negative_amount_rejected(w4_db):
    from src.writes import transactions as w
    tx_id = await w.insert_transaction(
        type="spend", amount_cents=500, source_wallet_id=1,
    )
    with pytest.raises(ValueError):
        await w.update_transaction(tx_id, amount_cents=-1)


# ---------- Soft-delete + restore ----------

@pytest.mark.asyncio
async def test_soft_delete_and_restore(w4_db):
    from src.writes import transactions as w
    tx_id = await w.insert_transaction(
        type="spend", amount_cents=500, source_wallet_id=1,
    )
    assert await w.soft_delete(tx_id) is True
    # Re-deleting is a no-op (returns False, doesn't crash)
    assert await w.soft_delete(tx_id) is False

    assert await w.restore(tx_id) is True
    assert await w.restore(tx_id) is False  # not deleted any more

    async with aiosqlite.connect(w4_db) as db:
        async with db.execute("SELECT deleted_at FROM transactions WHERE id = ?", (tx_id,)) as cur:
            row = await cur.fetchone()
    assert row[0] is None


# ---------- Place + item create helpers ----------

@pytest.mark.asyncio
async def test_insert_place_returns_existing(w4_db):
    from src.writes import places as w
    pid1 = await w.insert_place("Carrefour Maadi", "Carrefour")
    pid2 = await w.insert_place("Carrefour Maadi", "Carrefour")
    assert pid1 == pid2  # idempotent


@pytest.mark.asyncio
async def test_insert_place_validation(w4_db):
    from src.writes import places as w
    with pytest.raises(ValueError):
        await w.insert_place("")
    with pytest.raises(ValueError):
        await w.insert_place("x" * 200)


@pytest.mark.asyncio
async def test_insert_item_basic_with_alias(w4_db):
    from src.writes import items as w
    iid = await w.insert_item(canonical_name_en="Pepsi", size="330ml", unit="can",
                              default_category_id=1)
    async with aiosqlite.connect(w4_db) as db:
        async with db.execute(
            "SELECT alias_text FROM item_aliases WHERE item_id = ?", (iid,)
        ) as cur:
            aliases = [r[0] for r in await cur.fetchall()]
    assert "Pepsi" in aliases


@pytest.mark.asyncio
async def test_insert_item_requires_at_least_one_name(w4_db):
    from src.writes import items as w
    with pytest.raises(ValueError):
        await w.insert_item()
