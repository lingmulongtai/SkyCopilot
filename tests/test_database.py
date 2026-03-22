"""
tests/test_database.py
----------------------
Unit tests for utils/database.py using a temporary in-memory SQLite database.
"""

import sqlite3
import sys
import os
from pathlib import Path
from unittest.mock import patch

import pytest

# Ensure the project root is on the path
sys.path.insert(0, str(Path(__file__).parent.parent))

from utils import database as db_module
from utils.database import init_db, upsert_user, get_user, delete_user


@pytest.fixture(autouse=True)
def _tmp_db(tmp_path, monkeypatch):
    """Redirect DB_PATH to a fresh temp file for every test."""
    tmp_db = tmp_path / "test_skyCopilot.db"
    monkeypatch.setattr(db_module, "DB_PATH", tmp_db)
    init_db()
    yield


class TestInitDb:
    def test_creates_users_table(self):
        with db_module.get_connection() as conn:
            tables = conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name='users'"
            ).fetchone()
        assert tables is not None


class TestUpsertUser:
    def test_insert_new_user(self):
        upsert_user("111", "uuid-abc", "Steve")
        row = get_user("111")
        assert row is not None
        assert row["minecraft_uuid"] == "uuid-abc"
        assert row["minecraft_name"] == "Steve"

    def test_update_existing_user(self):
        upsert_user("111", "uuid-abc", "Steve")
        upsert_user("111", "uuid-xyz", "Alex")
        row = get_user("111")
        assert row["minecraft_uuid"] == "uuid-xyz"
        assert row["minecraft_name"] == "Alex"


class TestGetUser:
    def test_returns_none_for_unknown_user(self):
        assert get_user("999") is None

    def test_returns_row_for_known_user(self):
        upsert_user("222", "uuid-def", "Notch")
        row = get_user("222")
        assert row is not None
        assert row["discord_id"] == "222"


class TestDeleteUser:
    def test_delete_existing_user_returns_true(self):
        upsert_user("333", "uuid-ghi", "Herobrine")
        result = delete_user("333")
        assert result is True
        assert get_user("333") is None

    def test_delete_nonexistent_user_returns_false(self):
        result = delete_user("9999")
        assert result is False

    def test_delete_does_not_affect_other_users(self):
        upsert_user("444", "uuid-aaa", "PlayerA")
        upsert_user("555", "uuid-bbb", "PlayerB")
        delete_user("444")
        assert get_user("555") is not None
