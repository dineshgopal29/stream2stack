"""
PostgreSQL client for local development.

Provides a Supabase-compatible query builder interface backed by psycopg2,
so that service code works unchanged whether using Supabase or local Postgres.

Activate by setting DATABASE_URL in your environment.
"""

from __future__ import annotations

import json
import logging
import os
from functools import lru_cache
from types import SimpleNamespace
from typing import Any

import psycopg2
import psycopg2.extras
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Response wrapper
# ---------------------------------------------------------------------------

class _Response:
    """Mimics the supabase-py APIResponse shape (.data, .count)."""

    def __init__(self, data: list[dict] | dict | None, count: int | None = None):
        self.data = data
        if count is not None:
            self.count = count
        elif data is None:
            self.count = 0
        elif isinstance(data, list):
            self.count = len(data)
        else:
            self.count = 1


# ---------------------------------------------------------------------------
# Query builder
# ---------------------------------------------------------------------------

class _QueryBuilder:
    """Chainable query builder that translates to psycopg2 SQL."""

    def __init__(self, conn_factory, table: str):
        self._conn_factory = conn_factory
        self._table = table
        self._operation: str = "select"
        self._columns: str = "*"
        self._data: dict | list | None = None
        self._on_conflict: str | None = None
        self._filters: list[tuple] = []        # (col, op, val)
        self._order_col: str | None = None
        self._order_desc: bool = False
        self._limit_val: int | None = None
        self._single: bool = False
        self._negate_next: bool = False

    # --- operation setters ---

    def select(self, columns: str = "*") -> "_QueryBuilder":
        self._operation = "select"
        self._columns = columns
        return self

    def insert(self, data: dict | list) -> "_QueryBuilder":
        self._operation = "insert"
        self._data = data
        return self

    def update(self, data: dict) -> "_QueryBuilder":
        self._operation = "update"
        self._data = data
        return self

    def upsert(self, data: dict | list, on_conflict: str = "id") -> "_QueryBuilder":
        self._operation = "upsert"
        self._data = data
        self._on_conflict = on_conflict
        return self

    def delete(self) -> "_QueryBuilder":
        self._operation = "delete"
        return self

    # --- filter methods ---

    def eq(self, column: str, value: Any) -> "_QueryBuilder":
        self._filters.append((column, "=", value))
        return self

    def in_(self, column: str, values: list) -> "_QueryBuilder":
        self._filters.append((column, "IN", values))
        return self

    def is_(self, column: str, value: str) -> "_QueryBuilder":
        """Handle .is_('col', 'null') / .not_.is_('col', 'null')."""
        negate = self._negate_next
        self._negate_next = False  # always reset, regardless of value
        if value == "null":
            op = "IS NOT NULL" if negate else "IS NULL"
            self._filters.append((column, op, None))
        return self

    @property
    def not_(self) -> "_QueryBuilder":
        self._negate_next = True
        return self

    # --- modifiers ---

    def order(self, column: str, desc: bool = False) -> "_QueryBuilder":
        self._order_col = column
        self._order_desc = desc
        return self

    def limit(self, count: int) -> "_QueryBuilder":
        self._limit_val = count
        return self

    def single(self) -> "_QueryBuilder":
        self._single = True
        return self

    # --- execute ---

    def execute(self) -> _Response:
        conn = self._conn_factory()
        try:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                result = None
                if self._operation == "select":
                    result = self._exec_select(cur)
                elif self._operation == "insert":
                    result = self._exec_insert(cur)
                elif self._operation == "update":
                    result = self._exec_update(cur)
                elif self._operation == "upsert":
                    result = self._exec_upsert(cur)
                elif self._operation == "delete":
                    result = self._exec_delete(cur)
                else:
                    raise ValueError(f"Unknown operation: {self._operation}")
                conn.commit()
                return result
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    # --- private SQL builders ---

    def _build_where(self, params: list) -> str:
        if not self._filters:
            return ""
        clauses = []
        for col, op, val in self._filters:
            if op in ("IS NULL", "IS NOT NULL"):
                clauses.append(f'"{col}" {op}')
            elif op == "IN":
                clauses.append(f'"{col}" = ANY(%s)')
                params.append(val)
            else:
                clauses.append(f'"{col}" {op} %s')
                params.append(val)
        return "WHERE " + " AND ".join(clauses)

    def _exec_select(self, cur) -> _Response:
        params: list = []
        # Parse column list — keep * as-is, otherwise quote each name.
        if self._columns.strip() == "*":
            cols_sql = "*"
        else:
            cols_sql = ", ".join(
                f'"{c.strip()}"' for c in self._columns.split(",")
            )
        sql = f'SELECT {cols_sql} FROM "{self._table}"'
        where = self._build_where(params)
        if where:
            sql += " " + where
        if self._order_col:
            direction = "DESC" if self._order_desc else "ASC"
            sql += f' ORDER BY "{self._order_col}" {direction}'
        if self._limit_val is not None:
            sql += f" LIMIT {self._limit_val}"

        logger.debug("SELECT SQL: %s | params: %s", sql, params)
        cur.execute(sql, params)
        rows = [_serialize_row(dict(r)) for r in cur.fetchall()]

        if self._single:
            data = rows[0] if rows else None
            return _Response(data, count=len(rows))
        return _Response(rows)

    def _exec_insert(self, cur) -> _Response:
        rows = self._data if isinstance(self._data, list) else [self._data]
        if not rows:
            return _Response([])

        columns = list(rows[0].keys())
        col_sql = ", ".join(f'"{c}"' for c in columns)
        val_placeholders = ", ".join(["%s"] * len(columns))

        inserted = []
        for row in rows:
            vals = [_json_serialize(row[c]) for c in columns]
            sql = (
                f'INSERT INTO "{self._table}" ({col_sql}) '
                f'VALUES ({val_placeholders}) RETURNING *'
            )
            logger.debug("INSERT SQL: %s", sql)
            cur.execute(sql, vals)
            inserted.append(_serialize_row(dict(cur.fetchone())))

        return _Response(inserted)

    def _exec_update(self, cur) -> _Response:
        if not self._data:
            return _Response([])
        params: list = []
        set_clauses = []
        for col, val in self._data.items():
            set_clauses.append(f'"{col}" = %s')
            params.append(_json_serialize(val))

        sql = f'UPDATE "{self._table}" SET {", ".join(set_clauses)}'
        where = self._build_where(params)
        if where:
            sql += " " + where
        sql += " RETURNING *"

        logger.debug("UPDATE SQL: %s", sql)
        cur.execute(sql, params)
        rows = [_serialize_row(dict(r)) for r in cur.fetchall()]
        return _Response(rows)

    def _exec_upsert(self, cur) -> _Response:
        rows = self._data if isinstance(self._data, list) else [self._data]
        if not rows:
            return _Response([])

        columns = list(rows[0].keys())
        col_sql = ", ".join(f'"{c}"' for c in columns)
        val_placeholders = ", ".join(["%s"] * len(columns))
        conflict_cols = [c.strip() for c in (self._on_conflict or "id").split(",")]
        conflict_cols_sql = ", ".join(f'"{c}"' for c in conflict_cols)
        update_set = ", ".join(
            f'"{c}" = EXCLUDED."{c}"' for c in columns if c not in conflict_cols
        )

        # If all columns are conflict columns there's nothing to update — use DO NOTHING.
        on_conflict_action = (
            f"DO UPDATE SET {update_set}" if update_set else "DO NOTHING"
        )

        upserted = []
        for row in rows:
            vals = [_json_serialize(row[c]) for c in columns]
            sql = (
                f'INSERT INTO "{self._table}" ({col_sql}) '
                f'VALUES ({val_placeholders}) '
                f'ON CONFLICT ({conflict_cols_sql}) {on_conflict_action} '
                f'RETURNING *'
            )
            logger.debug("UPSERT SQL: %s", sql)
            cur.execute(sql, vals)
            result = cur.fetchone()
            if result:
                upserted.append(_serialize_row(dict(result)))

        return _Response(upserted)

    def _exec_delete(self, cur) -> _Response:
        params: list = []
        sql = f'DELETE FROM "{self._table}"'
        where = self._build_where(params)
        if where:
            sql += " " + where
        sql += " RETURNING *"
        logger.debug("DELETE SQL: %s", sql)
        cur.execute(sql, params)
        rows = [_serialize_row(dict(r)) for r in cur.fetchall()]
        return _Response(rows)


def _json_serialize(val: Any) -> Any:
    """Convert Python types to psycopg2-compatible values."""
    if isinstance(val, list) and val and isinstance(val[0], float):
        # pgvector expects a string like '[0.1, 0.2, ...]'
        return "[" + ",".join(str(v) for v in val) + "]"
    return val


def _serialize_row(row: dict) -> dict:
    """Normalize a DB row for consumption by Pydantic models.

    psycopg2 auto-converts timestamptz → datetime objects.  Pydantic models
    that type those fields as ``str`` would raise a ValidationError.  Convert
    all datetime-like values to ISO-8601 strings so the response layer stays
    clean regardless of the DB driver's type coercion.
    """
    from datetime import date, datetime  # local import to avoid circular refs

    out = {}
    for k, v in row.items():
        if isinstance(v, datetime):
            out[k] = v.isoformat()
        elif isinstance(v, date):
            out[k] = v.isoformat()
        else:
            out[k] = v
    return out


# ---------------------------------------------------------------------------
# RPC stub
# ---------------------------------------------------------------------------

class _RpcBuilder:
    def __init__(self, conn_factory, fn_name: str, params: dict):
        self._conn_factory = conn_factory
        self._fn_name = fn_name
        self._params = params

    def execute(self) -> _Response:
        conn = self._conn_factory()
        try:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                # Build named-argument call: SELECT * FROM fn(arg1 => %s, ...)
                args_sql = ", ".join(f"{k} => %s" for k in self._params)
                vals = list(self._params.values())
                sql = f"SELECT * FROM {self._fn_name}({args_sql})"
                logger.debug("RPC SQL: %s", sql)
                cur.execute(sql, vals)
                rows = [_serialize_row(dict(r)) for r in cur.fetchall()]
                conn.commit()
                return _Response(rows)
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()


# ---------------------------------------------------------------------------
# Storage stub
# ---------------------------------------------------------------------------

class _StorageBucketStub:
    def __init__(self, bucket: str):
        self._bucket = bucket
        self._local_dir = os.path.join(os.path.dirname(__file__), "..", "..", "local_storage", bucket)
        os.makedirs(self._local_dir, exist_ok=True)

    def upload(self, path: str, file: bytes, file_options: dict | None = None) -> None:
        dest = os.path.join(self._local_dir, path)
        os.makedirs(os.path.dirname(dest), exist_ok=True)
        with open(dest, "wb") as f:
            f.write(file)
        logger.info("Local storage: saved %s", dest)

    def get_public_url(self, path: str) -> str:
        dest = os.path.abspath(os.path.join(self._local_dir, path))
        return f"file://{dest}"


class _StorageStub:
    def from_(self, bucket: str) -> _StorageBucketStub:
        return _StorageBucketStub(bucket)


# ---------------------------------------------------------------------------
# Main client
# ---------------------------------------------------------------------------

class PostgresClient:
    """Drop-in replacement for the Supabase client for local development."""

    def __init__(self, database_url: str):
        self._database_url = database_url
        self.storage = _StorageStub()

    def _connect(self):
        return psycopg2.connect(self._database_url)

    def table(self, name: str) -> _QueryBuilder:
        return _QueryBuilder(self._connect, name)

    def rpc(self, fn_name: str, params: dict | None = None) -> _RpcBuilder:
        return _RpcBuilder(self._connect, fn_name, params or {})


@lru_cache(maxsize=1)
def get_postgres_client() -> PostgresClient:
    """Return a cached PostgresClient instance."""
    database_url = os.getenv("DATABASE_URL")
    if not database_url:
        raise ValueError("DATABASE_URL environment variable is not set.")
    logger.info("Initialising local PostgreSQL client.")
    return PostgresClient(database_url)
