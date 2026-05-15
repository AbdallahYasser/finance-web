"""Item writes — insert / update / soft-delete / restore + alias management."""
from typing import Optional

import aiosqlite

from src.db import write_db_uri

_UPDATABLE = {
    "canonical_name_en", "canonical_name_ar",
    "size", "unit", "default_category_id",
}


async def insert_item(
    canonical_name_en: Optional[str] = None,
    canonical_name_ar: Optional[str] = None,
    size: Optional[str] = None,
    unit: Optional[str] = None,
    default_category_id: Optional[int] = None,
) -> int:
    en = (canonical_name_en or "").strip() or None
    ar = (canonical_name_ar or "").strip() or None
    if not en and not ar:
        raise ValueError("at least one canonical name required")
    if en and len(en) > 80:
        raise ValueError("name too long (max 80)")
    size = (size or "").strip() or None
    unit = (unit or "").strip() or None
    if size and len(size) > 30:
        raise ValueError("size too long (max 30)")
    if unit and len(unit) > 30:
        raise ValueError("unit too long (max 30)")

    async with aiosqlite.connect(write_db_uri(), uri=True) as db:
        cur = await db.execute(
            """
            INSERT INTO items
              (canonical_name_en, canonical_name_ar, size, unit, default_category_id)
            VALUES (?, ?, ?, ?, ?)
            """,
            (en, ar, size, unit, default_category_id),
        )
        item_id = cur.lastrowid
        # Auto-alias from canonical names so fuzzy search finds them.
        for alias in (en, ar):
            if alias:
                await db.execute(
                    "INSERT OR IGNORE INTO item_aliases (item_id, alias_text) VALUES (?, ?)",
                    (item_id, alias),
                )
        await db.commit()
        return item_id


async def update_item(item_id: int, **fields) -> bool:
    bad = set(fields) - _UPDATABLE
    if bad:
        raise ValueError(f"cannot update fields: {sorted(bad)}")
    if not fields:
        return False
    for k in ("canonical_name_en", "canonical_name_ar", "size", "unit"):
        if k in fields and fields[k] is not None:
            fields[k] = fields[k].strip() or None
    # Length sanity
    for k, lim in (("canonical_name_en", 80), ("canonical_name_ar", 80),
                   ("size", 30), ("unit", 30)):
        if k in fields and fields[k] is not None and len(fields[k]) > lim:
            raise ValueError(f"{k} too long (max {lim})")

    cols = list(fields.keys())
    set_sql = ", ".join(f"{c} = ?" for c in cols)
    values = [fields[c] for c in cols] + [item_id]

    async with aiosqlite.connect(write_db_uri(), uri=True) as db:
        cur = await db.execute(
            f"UPDATE items SET {set_sql} WHERE id = ? AND deleted_at IS NULL",
            values,
        )
        # If a canonical name changed and is non-null, add it as an alias too
        # so fuzzy search picks up the new label.
        for k in ("canonical_name_en", "canonical_name_ar"):
            if k in fields and fields[k]:
                await db.execute(
                    "INSERT OR IGNORE INTO item_aliases (item_id, alias_text) VALUES (?, ?)",
                    (item_id, fields[k]),
                )
        await db.commit()
        return cur.rowcount > 0


async def soft_delete(item_id: int) -> bool:
    async with aiosqlite.connect(write_db_uri(), uri=True) as db:
        cur = await db.execute(
            "UPDATE items SET deleted_at = datetime('now') "
            "WHERE id = ? AND deleted_at IS NULL",
            (item_id,),
        )
        await db.commit()
        return cur.rowcount > 0


async def restore(item_id: int) -> bool:
    async with aiosqlite.connect(write_db_uri(), uri=True) as db:
        cur = await db.execute(
            "UPDATE items SET deleted_at = NULL "
            "WHERE id = ? AND deleted_at IS NOT NULL",
            (item_id,),
        )
        await db.commit()
        return cur.rowcount > 0


async def list_aliases(item_id: int) -> list[dict]:
    async with aiosqlite.connect(write_db_uri(), uri=True) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT id, alias_text FROM item_aliases "
            "WHERE item_id = ? AND deleted_at IS NULL ORDER BY id",
            (item_id,),
        ) as cur:
            return [dict(r) for r in await cur.fetchall()]


async def add_alias(item_id: int, alias_text: str) -> int:
    alias_text = (alias_text or "").strip()
    if not alias_text:
        raise ValueError("alias text required")
    if len(alias_text) > 80:
        raise ValueError("alias too long (max 80)")
    async with aiosqlite.connect(write_db_uri(), uri=True) as db:
        # Check for existing (incl soft-deleted — un-delete instead of duplicating)
        async with db.execute(
            "SELECT id, deleted_at FROM item_aliases "
            "WHERE item_id = ? AND alias_text = ?",
            (item_id, alias_text),
        ) as cur:
            row = await cur.fetchone()
        if row:
            alias_id = row[0]
            if row[1]:  # was soft-deleted → restore
                await db.execute(
                    "UPDATE item_aliases SET deleted_at = NULL WHERE id = ?",
                    (alias_id,),
                )
                await db.commit()
            return alias_id
        cur = await db.execute(
            "INSERT INTO item_aliases (item_id, alias_text) VALUES (?, ?)",
            (item_id, alias_text),
        )
        await db.commit()
        return cur.lastrowid


async def remove_alias(alias_id: int) -> bool:
    async with aiosqlite.connect(write_db_uri(), uri=True) as db:
        cur = await db.execute(
            "UPDATE item_aliases SET deleted_at = datetime('now') "
            "WHERE id = ? AND deleted_at IS NULL",
            (alias_id,),
        )
        await db.commit()
        return cur.rowcount > 0
