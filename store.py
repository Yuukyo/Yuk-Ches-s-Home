from __future__ import annotations

import json
import sqlite3
import threading
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def clean_fields(data: dict[str, Any], allowed: set[str]) -> dict[str, Any]:
    return {key: value for key, value in data.items() if key in allowed}


class Store:
    """Small persistence facade. Supabase is used in production; SQLite is a local fallback."""

    message_fields = {
        "role",
        "content",
        "status",
        "parent_id",
        "deletion_reason",
        "metadata",
        "created_at",
        "updated_at",
    }
    item_fields = {
        "kind",
        "title",
        "content",
        "value",
        "status",
        "happened_at",
        "metadata",
        "created_at",
        "updated_at",
    }

    def __init__(
        self,
        supabase_url: str = "",
        supabase_key: str = "",
        sqlite_path: str | Path = "instance/home.db",
    ) -> None:
        self.supabase = None
        self.sqlite_path = Path(sqlite_path)
        self._lock = threading.RLock()
        if supabase_url and supabase_key:
            from supabase import create_client

            self.supabase = create_client(supabase_url, supabase_key)
        else:
            self.sqlite_path.parent.mkdir(parents=True, exist_ok=True)
            self._init_sqlite()

    @property
    def backend(self) -> str:
        return "supabase" if self.supabase else "sqlite"

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.sqlite_path, check_same_thread=False)
        connection.row_factory = sqlite3.Row
        return connection

    @contextmanager
    def _connection(self) -> Iterator[sqlite3.Connection]:
        connection = self._connect()
        try:
            yield connection
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def _init_sqlite(self) -> None:
        with self._connection() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS messages (
                    id TEXT PRIMARY KEY,
                    role TEXT NOT NULL,
                    content TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'active',
                    parent_id TEXT,
                    deletion_reason TEXT,
                    metadata TEXT NOT NULL DEFAULT '{}',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS items (
                    id TEXT PRIMARY KEY,
                    kind TEXT NOT NULL,
                    title TEXT NOT NULL DEFAULT '',
                    content TEXT NOT NULL DEFAULT '',
                    value REAL NOT NULL DEFAULT 0,
                    status TEXT NOT NULL DEFAULT 'active',
                    happened_at TEXT,
                    metadata TEXT NOT NULL DEFAULT '{}',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS app_settings (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_messages_created
                    ON messages(created_at);
                CREATE INDEX IF NOT EXISTS idx_items_kind_created
                    ON items(kind, created_at);
                """
            )

    @staticmethod
    def _decode(row: dict[str, Any]) -> dict[str, Any]:
        result = dict(row)
        metadata = result.get("metadata")
        if isinstance(metadata, str):
            try:
                result["metadata"] = json.loads(metadata)
            except json.JSONDecodeError:
                result["metadata"] = {}
        return result

    def list_messages(
        self,
        *,
        statuses: tuple[str, ...] = ("active",),
        limit: int = 200,
    ) -> list[dict[str, Any]]:
        limit = min(max(int(limit), 1), 1000)
        if self.supabase:
            query = (
                self.supabase.table("messages")
                .select("*")
                .in_("status", list(statuses))
                .order("created_at")
                .limit(limit)
            )
            return query.execute().data or []
        placeholders = ",".join("?" for _ in statuses)
        with self._connection() as connection:
            rows = connection.execute(
                f"""
                SELECT * FROM (
                    SELECT * FROM messages
                    WHERE status IN ({placeholders})
                    ORDER BY created_at DESC
                    LIMIT ?
                ) ORDER BY created_at ASC
                """,
                (*statuses, limit),
            ).fetchall()
        return [self._decode(dict(row)) for row in rows]

    def get_message(self, message_id: str) -> dict[str, Any] | None:
        if self.supabase:
            rows = (
                self.supabase.table("messages")
                .select("*")
                .eq("id", message_id)
                .limit(1)
                .execute()
                .data
                or []
            )
            return rows[0] if rows else None
        with self._connection() as connection:
            row = connection.execute(
                "SELECT * FROM messages WHERE id = ?", (message_id,)
            ).fetchone()
        return self._decode(dict(row)) if row else None

    def create_message(
        self,
        role: str,
        content: str,
        *,
        metadata: dict[str, Any] | None = None,
        parent_id: str | None = None,
        created_at: str | None = None,
    ) -> dict[str, Any]:
        now = created_at or utc_now()
        row = {
            "id": str(uuid.uuid4()),
            "role": role,
            "content": content,
            "status": "active",
            "parent_id": parent_id,
            "deletion_reason": None,
            "metadata": metadata or {},
            "created_at": now,
            "updated_at": now,
        }
        if self.supabase:
            return self.supabase.table("messages").insert(row).execute().data[0]
        encoded = dict(row, metadata=json.dumps(row["metadata"], ensure_ascii=False))
        with self._lock, self._connection() as connection:
            connection.execute(
                """
                INSERT INTO messages
                (id, role, content, status, parent_id, deletion_reason,
                 metadata, created_at, updated_at)
                VALUES (:id, :role, :content, :status, :parent_id,
                        :deletion_reason, :metadata, :created_at, :updated_at)
                """,
                encoded,
            )
        return row

    def update_message(self, message_id: str, data: dict[str, Any]) -> dict[str, Any]:
        values = clean_fields(data, self.message_fields - {"created_at"})
        values["updated_at"] = utc_now()
        if self.supabase:
            rows = (
                self.supabase.table("messages")
                .update(values)
                .eq("id", message_id)
                .execute()
                .data
                or []
            )
            if not rows:
                raise KeyError("message not found")
            return rows[0]
        if "metadata" in values:
            values["metadata"] = json.dumps(values["metadata"], ensure_ascii=False)
        assignments = ", ".join(f"{key} = ?" for key in values)
        with self._lock, self._connection() as connection:
            cursor = connection.execute(
                f"UPDATE messages SET {assignments} WHERE id = ?",
                (*values.values(), message_id),
            )
            if not cursor.rowcount:
                raise KeyError("message not found")
        result = self.get_message(message_id)
        assert result is not None
        return result

    def list_items(
        self,
        *,
        kind: str | None = None,
        statuses: tuple[str, ...] = ("active", "done"),
        limit: int = 500,
    ) -> list[dict[str, Any]]:
        limit = min(max(int(limit), 1), 2000)
        if self.supabase:
            query = (
                self.supabase.table("items")
                .select("*")
                .in_("status", list(statuses))
                .order("created_at", desc=True)
                .limit(limit)
            )
            if kind:
                query = query.eq("kind", kind)
            return query.execute().data or []
        clauses = [f"status IN ({','.join('?' for _ in statuses)})"]
        args: list[Any] = list(statuses)
        if kind:
            clauses.append("kind = ?")
            args.append(kind)
        args.append(limit)
        with self._connection() as connection:
            rows = connection.execute(
                f"""
                SELECT * FROM items
                WHERE {' AND '.join(clauses)}
                ORDER BY created_at DESC LIMIT ?
                """,
                args,
            ).fetchall()
        return [self._decode(dict(row)) for row in rows]

    def get_item(self, item_id: str) -> dict[str, Any] | None:
        if self.supabase:
            rows = (
                self.supabase.table("items")
                .select("*")
                .eq("id", item_id)
                .limit(1)
                .execute()
                .data
                or []
            )
            return rows[0] if rows else None
        with self._connection() as connection:
            row = connection.execute(
                "SELECT * FROM items WHERE id = ?", (item_id,)
            ).fetchone()
        return self._decode(dict(row)) if row else None

    def create_item(self, data: dict[str, Any]) -> dict[str, Any]:
        now = utc_now()
        row = {
            "id": str(uuid.uuid4()),
            "kind": str(data.get("kind", "note"))[:40],
            "title": str(data.get("title", ""))[:200],
            "content": str(data.get("content", ""))[:20000],
            "value": float(data.get("value") or 0),
            "status": str(data.get("status", "active"))[:30],
            "happened_at": data.get("happened_at") or now,
            "metadata": data.get("metadata") or {},
            "created_at": now,
            "updated_at": now,
        }
        if self.supabase:
            return self.supabase.table("items").insert(row).execute().data[0]
        encoded = dict(row, metadata=json.dumps(row["metadata"], ensure_ascii=False))
        with self._lock, self._connection() as connection:
            connection.execute(
                """
                INSERT INTO items
                (id, kind, title, content, value, status, happened_at,
                 metadata, created_at, updated_at)
                VALUES (:id, :kind, :title, :content, :value, :status,
                        :happened_at, :metadata, :created_at, :updated_at)
                """,
                encoded,
            )
        return row

    def update_item(self, item_id: str, data: dict[str, Any]) -> dict[str, Any]:
        values = clean_fields(data, self.item_fields - {"created_at"})
        values["updated_at"] = utc_now()
        if self.supabase:
            rows = (
                self.supabase.table("items")
                .update(values)
                .eq("id", item_id)
                .execute()
                .data
                or []
            )
            if not rows:
                raise KeyError("item not found")
            return rows[0]
        if "metadata" in values:
            values["metadata"] = json.dumps(values["metadata"], ensure_ascii=False)
        assignments = ", ".join(f"{key} = ?" for key in values)
        with self._lock, self._connection() as connection:
            cursor = connection.execute(
                f"UPDATE items SET {assignments} WHERE id = ?",
                (*values.values(), item_id),
            )
            if not cursor.rowcount:
                raise KeyError("item not found")
        result = self.get_item(item_id)
        assert result is not None
        return result

    def archive_item(self, item_id: str) -> dict[str, Any]:
        return self.update_item(item_id, {"status": "archived"})

    def get_setting(self, key: str, default: Any = None) -> Any:
        if self.supabase:
            rows = (
                self.supabase.table("app_settings")
                .select("value")
                .eq("key", key)
                .limit(1)
                .execute()
                .data
                or []
            )
            return rows[0]["value"] if rows else default
        with self._connection() as connection:
            row = connection.execute(
                "SELECT value FROM app_settings WHERE key = ?", (key,)
            ).fetchone()
        if not row:
            return default
        try:
            return json.loads(row["value"])
        except json.JSONDecodeError:
            return default

    def set_setting(self, key: str, value: Any) -> Any:
        row = {"key": key, "value": value, "updated_at": utc_now()}
        if self.supabase:
            self.supabase.table("app_settings").upsert(row).execute()
            return value
        with self._lock, self._connection() as connection:
            connection.execute(
                """
                INSERT INTO app_settings (key, value, updated_at)
                VALUES (?, ?, ?)
                ON CONFLICT(key) DO UPDATE SET
                  value = excluded.value,
                  updated_at = excluded.updated_at
                """,
                (key, json.dumps(value, ensure_ascii=False), row["updated_at"]),
            )
        return value
