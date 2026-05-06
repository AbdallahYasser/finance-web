"""Read-only aiosqlite access to finance-bot's database.

The `?immutable=1` URI flag lets us open a WAL-mode DB on a read-only
bind mount without needing the `.db-shm` file (which can't be created
on a read-only filesystem).
"""
import aiosqlite

from src import config


def db_uri() -> str:
    return f"file:{config.DB_PATH}?immutable=1"


async def get_user(user_id: int) -> dict | None:
    async with aiosqlite.connect(db_uri(), uri=True) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT * FROM users WHERE user_id = ?", (user_id,)
        ) as cur:
            row = await cur.fetchone()
            return dict(row) if row else None
