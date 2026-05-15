"""People (debt counterparties) CRUD."""
from typing import Optional

import aiosqlite

from src.db import write_db_uri

_UPDATABLE = {"name", "telegram_username", "phone", "note"}


async def insert_person(
    *, name: str,
    telegram_username: Optional[str] = None,
    phone: Optional[str] = None,
    note: Optional[str] = None,
) -> int:
    name = (name or "").strip()
    if not name:
        raise ValueError("name required")
    if len(name) > 80:
        raise ValueError("name too long (max 80)")
    async with aiosqlite.connect(write_db_uri(), uri=True) as db:
        cur = await db.execute(
            """
            INSERT INTO people (name, telegram_username, phone, note)
            VALUES (?, ?, ?, ?)
            """,
            (name,
             (telegram_username or "").strip() or None,
             (phone or "").strip() or None,
             (note or "").strip() or None),
        )
        await db.commit()
        return cur.lastrowid


async def update_person(person_id: int, **fields) -> bool:
    bad = set(fields) - _UPDATABLE
    if bad:
        raise ValueError(f"cannot update fields: {sorted(bad)}")
    if not fields:
        return False
    for k in ("name", "telegram_username", "phone", "note"):
        if k in fields and fields[k] is not None:
            fields[k] = fields[k].strip() or None
    if "name" in fields and not fields["name"]:
        raise ValueError("name required")
    cols = list(fields.keys())
    set_sql = ", ".join(f"{c} = ?" for c in cols)
    values = [fields[c] for c in cols] + [person_id]
    async with aiosqlite.connect(write_db_uri(), uri=True) as db:
        cur = await db.execute(
            f"UPDATE people SET {set_sql} WHERE id = ? AND deleted_at IS NULL",
            values,
        )
        await db.commit()
        return cur.rowcount > 0


async def soft_delete(person_id: int) -> bool:
    async with aiosqlite.connect(write_db_uri(), uri=True) as db:
        cur = await db.execute(
            "UPDATE people SET deleted_at = datetime('now') "
            "WHERE id = ? AND deleted_at IS NULL",
            (person_id,),
        )
        await db.commit()
        return cur.rowcount > 0


async def restore(person_id: int) -> bool:
    async with aiosqlite.connect(write_db_uri(), uri=True) as db:
        cur = await db.execute(
            "UPDATE people SET deleted_at = NULL "
            "WHERE id = ? AND deleted_at IS NOT NULL",
            (person_id,),
        )
        await db.commit()
        return cur.rowcount > 0
