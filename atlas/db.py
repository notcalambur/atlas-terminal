"""DB connection helpers. Re-used by fetcher scripts and (a read-only subset) by API.

API side uses short-lived connections via psycopg.connect(). The scheduler
side uses the same. We deliberately avoid long-lived pooling in the
serverless API (Vercel freezes the connection between invocations).
"""
from __future__ import annotations

import contextlib
import os
from typing import Iterator

import psycopg
from psycopg.rows import dict_row

from .config import DATABASE_URL


@contextlib.contextmanager
def get_connection(autocommit: bool = False) -> Iterator[psycopg.Connection]:
    """Yield a short-lived connection. Caller wraps in `with`. Raises on error."""
    with psycopg.connect(DATABASE_URL, autocommit=autocommit) as conn:
        yield conn


@contextlib.contextmanager
def connection(autocommit: bool = False) -> Iterator[psycopg.Connection]:
    """Alias for get_connection — kept for backwards compat with the API."""
    with get_connection(autocommit=autocommit) as conn:
        yield conn


def fetch_all(sql: str, params: tuple | dict | None = None) -> list[dict]:
    """Read-only helper used by API handlers. Returns list of dicts."""
    with get_connection() as conn, conn.cursor(row_factory=dict_row) as cur:
        cur.execute(sql, params or ())
        return list(cur.fetchall())


def fetch_one(sql: str, params: tuple | dict | None = None) -> dict | None:
    with get_connection() as conn, conn.cursor(row_factory=dict_row) as cur:
        cur.execute(sql, params or ())
        return cur.fetchone()


def execute(sql: str, params: tuple | dict | None = None) -> None:
    """Write helper for the scheduler scripts."""
    with get_connection(autocommit=False) as conn:
        with conn.cursor() as cur:
            cur.execute(sql, params or ())
        conn.commit()