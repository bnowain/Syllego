"""
db/test_history.py — Tests for the SQLite history layer.

All tests use tmp_db_path so they never touch the real DB.
"""
import re
import sqlite3

import pytest

from mmi.db.history import _connect, get_recent, record_download


class TestConnect:
    def test_creates_db_file(self, tmp_db_path):
        _connect(tmp_db_path)
        assert tmp_db_path.exists()

    def test_creates_parent_dirs(self, tmp_path):
        nested = tmp_path / "a" / "b" / "c" / "test.db"
        _connect(nested)
        assert nested.exists()

    def test_wal_mode(self, tmp_db_path):
        conn = _connect(tmp_db_path)
        mode = conn.execute("PRAGMA journal_mode;").fetchone()[0]
        conn.close()
        assert mode == "wal"

    def test_foreign_keys_on(self, tmp_db_path):
        conn = _connect(tmp_db_path)
        fk = conn.execute("PRAGMA foreign_keys;").fetchone()[0]
        conn.close()
        assert fk == 1

    def test_creates_download_history_table(self, tmp_db_path):
        conn = _connect(tmp_db_path)
        tables = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()
        conn.close()
        table_names = [t[0] for t in tables]
        assert "download_history" in table_names


class TestRecordDownload:
    def test_returns_int(self, tmp_db_path):
        row_id = record_download("https://example.com", "success", db_path=tmp_db_path)
        assert isinstance(row_id, int)

    def test_auto_increments(self, tmp_db_path):
        id1 = record_download("https://a.com", "success", db_path=tmp_db_path)
        id2 = record_download("https://b.com", "failed", db_path=tmp_db_path)
        assert id2 > id1

    def test_stores_all_fields(self, tmp_db_path):
        record_download(
            url="https://example.com",
            download_status="success",
            worker_name="TestWorker",
            filename="/path/to/file.mp4",
            error_message=None,
            db_path=tmp_db_path,
        )
        conn = _connect(tmp_db_path)
        row = conn.execute("SELECT * FROM download_history").fetchone()
        conn.close()
        assert row["url"] == "https://example.com"
        assert row["download_status"] == "success"
        assert row["worker_name"] == "TestWorker"
        assert row["filename"] == "/path/to/file.mp4"

    def test_iso_timestamp(self, tmp_db_path):
        record_download("https://example.com", "success", db_path=tmp_db_path)
        conn = _connect(tmp_db_path)
        row = conn.execute("SELECT timestamp FROM download_history").fetchone()
        conn.close()
        ts = row["timestamp"]
        # Expect format: YYYY-MM-DDTHH:MM:SS
        assert re.match(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}", ts)

    def test_nullable_fields_default_to_none(self, tmp_db_path):
        record_download("https://example.com", "success", db_path=tmp_db_path)
        conn = _connect(tmp_db_path)
        row = conn.execute("SELECT * FROM download_history").fetchone()
        conn.close()
        assert row["worker_name"] is None
        assert row["filename"] is None
        assert row["error_message"] is None

    def test_column_is_download_status_not_status(self, tmp_db_path):
        _connect(tmp_db_path)
        conn = sqlite3.connect(str(tmp_db_path))
        cols = [c[1] for c in conn.execute("PRAGMA table_info(download_history)").fetchall()]
        conn.close()
        assert "download_status" in cols
        assert "status" not in cols


class TestGetRecent:
    def test_empty_table_returns_empty_list(self, tmp_db_path):
        result = get_recent(db_path=tmp_db_path)
        assert result == []

    def test_returns_list_of_dicts(self, tmp_db_path):
        record_download("https://example.com", "success", db_path=tmp_db_path)
        rows = get_recent(db_path=tmp_db_path)
        assert len(rows) == 1
        assert isinstance(rows[0], dict)

    def test_desc_order_by_id(self, tmp_db_path):
        record_download("https://a.com", "success", db_path=tmp_db_path)
        record_download("https://b.com", "success", db_path=tmp_db_path)
        rows = get_recent(db_path=tmp_db_path)
        assert rows[0]["url"] == "https://b.com"
        assert rows[1]["url"] == "https://a.com"

    def test_respects_limit(self, tmp_db_path):
        for i in range(5):
            record_download(f"https://example.com/{i}", "success", db_path=tmp_db_path)
        rows = get_recent(limit=3, db_path=tmp_db_path)
        assert len(rows) == 3

    def test_correct_dict_keys(self, tmp_db_path):
        record_download("https://example.com", "success", db_path=tmp_db_path)
        rows = get_recent(db_path=tmp_db_path)
        expected_keys = {
            "id", "url", "download_status", "worker_name",
            "filename", "timestamp", "error_message",
        }
        assert set(rows[0].keys()) == expected_keys
