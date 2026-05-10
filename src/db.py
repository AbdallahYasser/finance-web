"""aiosqlite access to finance-bot's database.

`db_uri()` returns a read-only URI with `?immutable=1` — used for all query
helpers. `write_db_uri()` returns a plain file: URI for write paths.
The bind mount is now read-write (W4); WAL mode (set by the bot) handles
both processes writing concurrently.
"""
import aiosqlite

from src import config


def db_uri() -> str:
    """Read-only URI — used by query modules."""
    return f"file:{config.DB_PATH}?immutable=1"


def write_db_uri() -> str:
    """Read-write URI — used only by `src.writes.*`."""
    return f"file:{config.DB_PATH}"


async def get_user(user_id: int) -> dict | None:
    async with aiosqlite.connect(db_uri(), uri=True) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT * FROM users WHERE user_id = ?", (user_id,)
        ) as cur:
            row = await cur.fetchone()
            return dict(row) if row else None
