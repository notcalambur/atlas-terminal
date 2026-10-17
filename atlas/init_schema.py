"""Init script. Creates the schema. Idempotent — safe to re-run.

Usage: python -m atlas.init_schema
"""
from __future__ import annotations

import sys
from pathlib import Path

# Allow running as `python -m atlas.init_schema`.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import psycopg

from atlas.config import DATABASE_URL


def main() -> int:
    sql = (Path(__file__).resolve().parent / "schema.sql").read_text()
    with psycopg.connect(DATABASE_URL, autocommit=True) as conn:
        with conn.cursor() as cur:
            cur.execute(sql)
    print(f"[atlas] schema applied to {DATABASE_URL}")
    return 0


if __name__ == "__main__":
    sys.exit(main())