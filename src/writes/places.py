"""Place writes — insert / update / soft-delete / restore."""
from typing import Optional

import aiosqlite

from src.db import write_db_uri

_UPDATABLE = {"branch_name", "chain_name"}


async def insert_place(branch_name: str, chain_name: Optional[str] = None) -> int:
    branch_name = (branch_name or "").strip()
    if not branch_name:
        raise ValueError("branch_name required")
    if len(branch_name) > 80:
        raise ValueError("branch_name too long (max 80)")
    chain = (chain_name or "").strip() or None
    if chain and len(chain) > 80:
        raise ValueError("chain_name too long (max 80)")

    async with aiosqlite.connect(write_db_uri(), uri=True) as db:
        # If exact branch+chain already exists (active), return it instead of failing.
        if chain is None:
            async with db.execute(
                "SELECT id FROM places WHERE branch_name = ? AND chain_name IS NULL "
                "AND deleted_at IS NULL",
                (branch_name,),
            ) as cur:
                row = await cur.fetchone()
        else:
            async with db.execute(
                "SELECT id FROM places WHERE branch_name = ? AND chain_name = ? "
                "AND deleted_at IS NULL",
                (branch_name, chain),
            ) as cur:
                row = await cur.fetchone()
        if row:
            return row[0]
        cur = await db.execute(
            "INSERT INTO places (branch_name, chain_name) VALUES (?, ?)",
            (branch_name, chain),
        )
        await db.commit()
        return cur.lastrowid


async def update_place(place_id: int, **fields) -> bool:
    bad = set(fields) - _UPDATABLE
    if bad:
        raise ValueError(f"cannot update fields: {sorted(bad)}")
    if not fields:
        return False
    for k in ("branch_name", "chain_name"):
        if k in fields and fields[k] is not None:
            fields[k] = fields[k].strip() or None
    if "branch_name" in fields and not fields["branch_name"]:
        raise ValueError("branch_name required")
    if "branch_name" in fields and len(fields["branch_name"]) > 80:
        raise ValueError("branch_name too long (max 80)")
    if "chain_name" in fields and fields["chain_name"] and len(fields["chain_name"]) > 80:
        raise ValueError("chain_name too long (max 80)")

    cols = list(fields.keys())
    set_sql = ", ".join(f"{c} = ?" for c in cols)
    values = [fields[c] for c in cols] + [place_id]

    async with aiosqlite.connect(write_db_uri(), uri=True) as db:
        try:
            cur = await db.execute(
                f"UPDATE places SET {set_sql} WHERE id = ? AND deleted_at IS NULL",
                values,
            )
            await db.commit()
        except aiosqlite.IntegrityError as e:
            # UNIQUE(branch_name, chain_name) clash
            raise ValueError("a place with that branch + chain already exists") from e
        return cur.rowcount > 0


async def soft_delete(place_id: int) -> bool:
    async with aiosqlite.connect(write_db_uri(), uri=True) as db:
        cur = await db.execute(
            "UPDATE places SET deleted_at = datetime('now') "
            "WHERE id = ? AND deleted_at IS NULL",
            (place_id,),
        )
        await db.commit()
        return cur.rowcount > 0


async def restore(place_id: int) -> bool:
    async with aiosqlite.connect(write_db_uri(), uri=True) as db:
        cur = await db.execute(
            "UPDATE places SET deleted_at = NULL "
            "WHERE id = ? AND deleted_at IS NOT NULL",
            (place_id,),
        )
        await db.commit()
        return cur.rowcount > 0
