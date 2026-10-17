"""Centralised config. Reads from .env once at import."""
from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

# Load .env from project root if present (scheduler / local dev).
_ROOT = Path(__file__).resolve().parent.parent
load_dotenv(_ROOT / ".env", override=False)

DATABASE_URL: str = os.environ.get(
    "DATABASE_URL",
    "postgresql://jesse_user:jesse_password@dokploy-postgres:5432/atlas",
)
SEC_USER_AGENT: str = os.environ.get(
    "SEC_USER_AGENT",
    "Atlas Terminal research@example.com",
)
LOG_LEVEL: str = os.environ.get("LOG_LEVEL", "INFO")
PORT: int = int(os.environ.get("PORT", "8000"))

# Fixed ticker universe — used by the frontend picker and the scheduler.
TICKERS: tuple[str, ...] = (
    "AAPL", "MSFT", "NVDA", "AMZN", "GOOGL",
    "META", "TSLA", "JPM", "V", "SPY", "QQQ",
)
INDICES: tuple[str, ...] = ("SPY", "QQQ", "DIA", "IWM", "^VIX")

# FRED series we always want.
FRED_SERIES: tuple[str, ...] = (
    "DFF", "DGS3MO", "DGS2", "DGS10", "CPIAUCSL", "UNRATE",
)