"""Place creation. (Edit/delete lands in W5.)"""
from typing import Optional

import aiosqlite

from src.db import write_db_uri


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
