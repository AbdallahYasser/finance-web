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
                created_at TEXT DEFAULT (datetime('now')),
                updated_at TEXT DEFAULT (datetime('now'))
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


@pytest_asyncio.fixture
async def w4_db(monkeypatch):
    """Full schema + seeded wallets/category/place/item, ready for write tests.
    Shared via conftest so both test_writes.py and test_endpoints.py can use it.
    """
    tmpdir = tempfile.mkdtemp()
    db_path = str(Path(tmpdir) / "finance_bot.db")

    async with aiosqlite.connect(db_path) as db:
        await db.execute("PRAGMA journal_mode=WAL")
        await db.execute("PRAGMA foreign_keys = ON")
        await db.execute("""
            CREATE TABLE wallets (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name_en TEXT, name_ar TEXT,
                type TEXT NOT NULL,
                initial_balance_cents INTEGER NOT NULL DEFAULT 0,
                karat INTEGER, gold_grams_milligrams INTEGER,
                gold_price_per_gram_cents INTEGER, gold_price_updated_at TEXT,
                created_at TEXT DEFAULT (datetime('now')),
                deleted_at TEXT
            )
        """)
        await db.execute("""
            CREATE TABLE categories (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                parent_id INTEGER, name_en TEXT, name_ar TEXT,
                kind TEXT NOT NULL DEFAULT 'expense',
                icon TEXT, is_default INTEGER DEFAULT 0,
                deleted_at TEXT
            )
        """)
        await db.execute("""
            CREATE TABLE places (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                branch_name TEXT, chain_name TEXT, deleted_at TEXT,
                UNIQUE(branch_name, chain_name)
            )
        """)
        await db.execute("""
            CREATE TABLE items (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                canonical_name_en TEXT, canonical_name_ar TEXT,
                size TEXT, unit TEXT, default_category_id INTEGER,
                deleted_at TEXT
            )
        """)
        await db.execute("""
            CREATE TABLE item_aliases (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                item_id INTEGER, alias_text TEXT, deleted_at TEXT,
                UNIQUE(item_id, alias_text)
            )
        """)
        await db.execute("""
            CREATE TABLE allowed_users (
                user_id INTEGER PRIMARY KEY,
                added_at TEXT DEFAULT (datetime('now'))
            )
        """)
        await db.execute("""
            CREATE TABLE users (
                user_id INTEGER PRIMARY KEY,
                language TEXT DEFAULT 'en',
                timezone TEXT DEFAULT 'Africa/Cairo',
                salary_day INTEGER,
                created_at TEXT DEFAULT (datetime('now')),
                updated_at TEXT DEFAULT (datetime('now'))
            )
        """)
        await db.execute("""
            CREATE TABLE transactions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                type TEXT NOT NULL,
                amount_cents INTEGER NOT NULL CHECK (amount_cents > 0),
                source_wallet_id INTEGER, dest_wallet_id INTEGER,
                category_id INTEGER, item_id INTEGER, place_id INTEGER,
                person_id INTEGER, debt_id INTEGER,
                refund_of_id INTEGER, occurred_at TEXT NOT NULL,
                note TEXT,
                source TEXT NOT NULL DEFAULT 'manual'
                  CHECK (source IN ('manual','sms','recurring','wizard')),
                created_at TEXT DEFAULT (datetime('now')),
                deleted_at TEXT
            )
        """)
        await db.execute("""
            CREATE TABLE item_prices (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                item_id INTEGER NOT NULL, place_id INTEGER NOT NULL,
                price_cents INTEGER NOT NULL,
                observed_at TEXT NOT NULL, on_sale INTEGER DEFAULT 0,
                transaction_id INTEGER,
                created_at TEXT DEFAULT (datetime('now'))
            )
        """)
        await db.execute("INSERT INTO wallets (name_en, type, initial_balance_cents) VALUES (?, ?, ?)",
                         ("Bank", "bank", 100000))
        await db.execute("INSERT INTO wallets (name_en, type, initial_balance_cents) VALUES (?, ?, ?)",
                         ("Cash", "cash", 50000))
        await db.execute("INSERT INTO categories (name_en, kind, icon) VALUES (?, ?, ?)",
                         ("Food", "expense", "🍴"))
        await db.execute("INSERT INTO places (branch_name, chain_name) VALUES (?, ?)",
                         ("7-Eleven Maadi", "7-Eleven"))
        await db.execute("INSERT INTO items (canonical_name_en, size) VALUES (?, ?)",
                         ("Water bottle", "500ml"))
        await db.execute("INSERT INTO allowed_users (user_id) VALUES (?)", (5904148250,))
        await db.execute("INSERT INTO users (user_id) VALUES (?)", (5904148250,))
        await db.commit()

    from src import config
    monkeypatch.setattr(config, "DB_PATH", db_path)
    return db_path
