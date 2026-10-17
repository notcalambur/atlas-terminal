"""FRED CSV fetcher. Public, no key. https://fred.stlouisfed.org/graph/fredgraph.csv?id=SERIES"""
from __future__ import annotations

import csv
import datetime as dt
import io
import time

import httpx

from .config import FRED_SERIES
from .db import execute


CSV_URL = "https://fred.stlouisfed.org/graph/fredgraph.csv"


def fetch_series(series_id: str, lookback_days: int = 365 * 10) -> list[tuple[dt.date, float]]:
    """Pull a single FRED series. Returns list of (date, value). Newest last."""
    # The endpoint accepts ?id= and an optional cosd/coed date range; pulling the
    # whole series is cheap enough for daily macro indicators.
    params = {"id": series_id}
    headers = {"User-Agent": "Atlas-Terminal/0.1 (research; +mailto:research@example.com)"}
    with httpx.Client(timeout=20.0) as client:
        r = client.get(CSV_URL, params=params, headers=headers, follow_redirects=True)
        r.raise_for_status()
    text = r.text
    out: list[tuple[dt.date, float]] = []
    reader = csv.DictReader(io.StringIO(text))
    for row in reader:
        try:
            d = dt.date.fromisoformat(row["DATE"])
            v = float(row[series_id])
        except (KeyError, ValueError):
            continue
        out.append((d, v))
    return out


def upsert_series(series_id: str, rows: list[tuple[dt.date, float]]) -> int:
    if not rows:
        return 0
    sql = """
        INSERT INTO atlas.fred_series (series_id, ts, value)
        VALUES (%s, %s, %s)
        ON CONFLICT (series_id, ts) DO UPDATE SET
            value      = EXCLUDED.value,
            fetched_at = now()
    """
    payload = [(series_id, d, v) for d, v in rows]
    with __import__("psycopg").connect(__import__("os").environ.get(
        "DATABASE_URL",
        "postgresql://jesse_user:jesse_password@dokploy-postgres:5432/atlas"
    )) as conn:
        with conn.cursor() as cur:
            cur.executemany(sql, payload)
        conn.commit()
    return len(payload)


def refresh_all(series_ids: list[str] | None = None) -> dict[str, int]:
    """Refresh every FRED series in the config. Returns rows-upserted per id."""
    series_ids = list(series_ids or FRED_SERIES)
    out: dict[str, int] = {}
    for sid in series_ids:
        try:
            rows = fetch_series(sid)
            out[sid] = upsert_series(sid, rows)
        except Exception as e:
            print(f"[fred] {sid} FAILED: {type(e).__name__}: {e}")
            out[sid] = -1
        # Be polite — FRED asks for rate-limit respect.
        time.sleep(0.2)
    return out


def latest(series_id: str) -> tuple[dt.date, float] | None:
    """Read the most recent row of a series from the DB. Used by the API."""
    from .db import fetch_one
    row = fetch_one(
        "SELECT ts, value FROM atlas.fred_series WHERE series_id = %s ORDER BY ts DESC LIMIT 1",
        (series_id,),
    )
    if not row:
        return None
    return row["ts"], float(row["value"])


if __name__ == "__main__":
    print(refresh_all())