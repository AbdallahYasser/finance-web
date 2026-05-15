"""User-settings writes — language toggle for now."""
import aiosqlite

from src.db import write_db_uri

ALLOWED_LANGUAGES = ("en", "ar")


async def set_language(user_id: int, language: str) -> bool:
    if language not in ALLOWED_LANGUAGES:
        raise ValueError(f"invalid language: {language!r}")
    async with aiosqlite.connect(write_db_uri(), uri=True) as db:
        cur = await db.execute(
            "UPDATE users SET language = ?, updated_at = datetime('now') "
            "WHERE user_id = ?",
            (language, user_id),
        )
        await db.commit()
        return cur.rowcount > 0
