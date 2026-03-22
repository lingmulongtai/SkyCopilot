"""
utils/database.py
-----------------
SQLite helper utilities for SkyCopilot.

Schema
------
users(discord_id TEXT PRIMARY KEY, minecraft_uuid TEXT NOT NULL, minecraft_name TEXT NOT NULL)
"""

import sqlite3
import logging
from pathlib import Path

logger = logging.getLogger(__name__)

DB_PATH = Path(__file__).parent.parent / "skyCopilot.db"


def get_connection() -> sqlite3.Connection:
    """Return a connection to the SQLite database with row_factory set."""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
    """Create tables if they do not already exist."""
    with get_connection() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS users (
                discord_id    TEXT PRIMARY KEY,
                minecraft_uuid TEXT NOT NULL,
                minecraft_name TEXT NOT NULL
            )
            """
        )
        conn.commit()
    logger.info("Database initialised at %s", DB_PATH)


def upsert_user(discord_id: str, minecraft_uuid: str, minecraft_name: str) -> None:
    """Insert or update the Minecraft ID / UUID for a Discord user."""
    with get_connection() as conn:
        conn.execute(
            """
            INSERT INTO users (discord_id, minecraft_uuid, minecraft_name)
            VALUES (?, ?, ?)
            ON CONFLICT(discord_id) DO UPDATE SET
                minecraft_uuid = excluded.minecraft_uuid,
                minecraft_name = excluded.minecraft_name
            """,
            (discord_id, minecraft_uuid, minecraft_name),
        )
        conn.commit()


def get_user(discord_id: str) -> sqlite3.Row | None:
    """Return the stored row for *discord_id*, or ``None`` if not registered."""
    with get_connection() as conn:
        return conn.execute(
            "SELECT * FROM users WHERE discord_id = ?", (discord_id,)
        ).fetchone()


def delete_user(discord_id: str) -> bool:
    """Delete the row for *discord_id*.  Returns ``True`` if a row was deleted."""
    with get_connection() as conn:
        cursor = conn.execute(
            "DELETE FROM users WHERE discord_id = ?", (discord_id,)
        )
        conn.commit()
    return cursor.rowcount > 0
