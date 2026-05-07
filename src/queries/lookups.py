"""Lookup lists for filter dropdowns — categories tree, wallets, places, items."""
import aiosqlite

from src.db import db_uri


async def categories_tree() -> list[dict]:
    """All active categories with parent_id, ordered for grouped display."""
    async with aiosqlite.connect(db_uri(), uri=True) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            """
            SELECT id, parent_id, name_en, name_ar, kind, icon
            FROM categories
            WHERE deleted_at IS NULL
            ORDER BY (parent_id IS NULL) DESC, parent_id, id
            """
        ) as cur:
            return [dict(r) for r in await cur.fetchall()]


async def wallets_list() -> list[dict]:
    async with aiosqlite.connect(db_uri(), uri=True) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            """
            SELECT id, name_en, name_ar, type
            FROM wallets
            WHERE deleted_at IS NULL
            ORDER BY id
            """
        ) as cur:
            return [dict(r) for r in await cur.fetchall()]


async def places_list() -> list[dict]:
    async with aiosqlite.connect(db_uri(), uri=True) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            """
            SELECT id, branch_name, chain_name
            FROM places
            WHERE deleted_at IS NULL
            ORDER BY branch_name COLLATE NOCASE
            """
        ) as cur:
            return [dict(r) for r in await cur.fetchall()]


async def items_list() -> list[dict]:
    async with aiosqlite.connect(db_uri(), uri=True) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            """
            SELECT id, canonical_name_en, canonical_name_ar, size, unit
            FROM items
            WHERE deleted_at IS NULL
            ORDER BY canonical_name_en COLLATE NOCASE
            """
        ) as cur:
            return [dict(r) for r in await cur.fetchall()]
