"""Item creation. (Edit/delete/aliases land in W5.)"""
from typing import Optional

import aiosqlite

from src.db import write_db_uri


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
