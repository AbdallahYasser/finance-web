"""Shared pytest fixtures."""
import tempfile
from pathlib import Path

import aiosqlite
import pytest
import pytest_asyncio


@pytest_asyncio.fixture
async def seeded_bot_db(monkeypatch):
    """A temp SQLite file mimicking finance-bot's schema (just the parts auth touches)."""
    tmpdir = tempfile.mkdtemp()
    db_path = str(Path(tmpdir) / "finance_bot.db")

    async with aiosqlite.connect(db_path) as db:
        await db.execute("""
            CREATE TABLE users (
                user_id INTEGER PRIMARY KEY,
                language TEXT DEFAULT 'en',
                timezone TEXT DEFAULT 'Africa/Cairo',
                salary_day INTEGER,
                created_at TEXT DEFAULT (datetime('now'))
            )
        """)
        await db.execute("""
            CREATE TABLE allowed_users (user_id INTEGER PRIMARY KEY)
        """)
        await db.execute("INSERT INTO allowed_users (user_id) VALUES (?)", (5904148250,))
        await db.execute(
            "INSERT INTO users (user_id, language, salary_day) VALUES (?, ?, ?)",
            (5904148250, "en", 28),
        )
        await db.commit()

    from src import config
    monkeypatch.setattr(config, "DB_PATH", db_path)
    monkeypatch.setattr(config, "BOT_TOKEN", "test-bot-token")
    monkeypatch.setattr(config, "SECRET_KEY", "test-secret-key-32-characters-long")
    monkeypatch.setattr(config, "ALLOWED_USERS", {5904148250})
    return db_path
