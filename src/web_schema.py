"""Web-side migrations.

The bot owns `schema_migrations` and its `M_*` namespace. The web reuses
the same table to record `W_*` migrations — different prefix, so the two
processes never step on each other.

These migrations run on FastAPI startup (idempotent via the tracking row).
"""
import logging

import aiosqlite

from src.db import write_db_uri

logger = logging.getLogger(__name__)


WEB_MIGRATIONS: list[tuple[str, str]] = [
    ("W7_0001_create_people", """
        CREATE TABLE IF NOT EXISTS people (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            telegram_username TEXT,
            phone TEXT,
            note TEXT,
            created_at TEXT NOT NULL DEFAULT (datetime('now')),
            deleted_at TEXT
        )
    """),
    ("W7_0002_create_debts", """
        CREATE TABLE IF NOT EXISTS debts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            person_id INTEGER NOT NULL REFERENCES people(id),
            direction TEXT NOT NULL CHECK (direction IN ('lent','borrowed')),
            original_amount_cents INTEGER NOT NULL CHECK (original_amount_cents > 0),
            opened_at TEXT NOT NULL,
            due_at TEXT,
            status TEXT NOT NULL DEFAULT 'open'
              CHECK (status IN ('open','partial','closed','forgiven')),
            note TEXT,
            created_at TEXT NOT NULL DEFAULT (datetime('now'))
        )
    """),
    ("W7_0003_idx_debts_status",
     "CREATE INDEX IF NOT EXISTS idx_debts_status ON debts(status, opened_at)"),
    ("W7_0004_idx_debts_person",
     "CREATE INDEX IF NOT EXISTS idx_debts_person ON debts(person_id, status)"),
]


async def apply_web_migrations() -> None:
    """Apply W_* migrations idempotently, tracking via schema_migrations."""
    async with aiosqlite.connect(write_db_uri(), uri=True) as db:
        # schema_migrations is created by the bot. If somehow the web boots
        # before the bot has ever run, create it defensively.
        await db.execute("""
            CREATE TABLE IF NOT EXISTS schema_migrations (
                name TEXT PRIMARY KEY,
                applied_at TEXT NOT NULL DEFAULT (datetime('now'))
            )
        """)
        await db.commit()

        for name, stmt in WEB_MIGRATIONS:
            async with db.execute(
                "SELECT 1 FROM schema_migrations WHERE name = ?", (name,)
            ) as cur:
                if await cur.fetchone():
                    continue
            try:
                await db.execute(stmt)
                await db.execute(
                    "INSERT INTO schema_migrations (name) VALUES (?)", (name,)
                )
                logger.info("Applied web migration: %s", name)
            except Exception as e:
                logger.warning("Web migration %s skipped or failed: %s", name, e)
        await db.commit()
