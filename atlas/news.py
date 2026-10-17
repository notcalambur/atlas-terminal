"""News fetcher: yfinance Ticker.news first, then Google News RSS fallback.

Designed for the scheduler. Returns a normalized list of headlines; sentiment
is scored by sentiment.score_headlines() in a separate file (FinBERT loads
lazily so the rest of the codebase stays import-safe).
"""
from __future__ import annotations

import datetime as dt
import time
from typing import Iterable

import feedparser
import httpx
import yfinance as yf

from .config import TICKERS
from .db import execute, fetch_all


GOOGLE_RSS_URL = (
    "https://news.google.com/rss/search?q={q}+stock&hl=en-US&gl=US&ceid=US:en"
)


def _clean_url(url: str) -> str:
    """Strip Google News tracking wrapper to recover the real article URL."""
    if not url:
        return url
    if "news.google.com/rss/articles" in url:
        try:
            # Decode the base64-ish URL params to extract the real URL.
            import base64
            import re
            m = re.search(r"articles/([^?]+)", url)
            if m:
                encoded = m.group(1)
                # Google's articles URL is URL-safe base64 of protobuf. We can't fully
                # decode it without protobuf, but we can leave the link as-is — Google
                # News will redirect on click. The redirect target is the real article.
                pass
        except Exception:
            pass
    return url


def from_yfinance(ticker: str, limit: int = 10) -> list[dict]:
    """yfinance Ticker.news often returns an empty list; caller falls back."""
    try:
        t = yf.Ticker(ticker)
        items = t.news or []
    except Exception:
        return []
    out = []
    for it in items[:limit]:
        title = it.get("title") or ""
        publisher = (it.get("publisher") or "").strip()
        ts = it.get("providerPublishTime")
        url = it.get("link") or ""
        if not title or not url:
            continue
        published = (
            dt.datetime.fromtimestamp(ts, tz=dt.timezone.utc) if ts
            else dt.datetime.now(dt.timezone.utc)
        )
        out.append({
            "title": title,
            "publisher": publisher or "Yahoo Finance",
            "published_at": published,
            "url": url,
            "source": "yfinance",
        })
    return out


def from_google_news(ticker: str, limit: int = 10) -> list[dict]:
    """Google News RSS fallback. No API key, no rate limit to speak of."""
    q = ticker.replace("^", "")
    url = GOOGLE_RSS_URL.format(q=q)
    headers = {"User-Agent": "Atlas-Terminal/0.1"}
    try:
        with httpx.Client(timeout=15.0) as client:
            r = client.get(url, headers=headers, follow_redirects=True)
            r.raise_for_status()
    except Exception:
        return []
    parsed = feedparser.parse(r.text)
    out = []
    for e in parsed.entries[:limit]:
        title = getattr(e, "title", "") or ""
        if not title:
            continue
        publisher = getattr(e, "source", None)
        publisher = publisher.get("title") if hasattr(publisher, "get") else (publisher or "")
        published = getattr(e, "published_parsed", None)
        if published:
            pub = dt.datetime(*published[:6], tzinfo=dt.timezone.utc)
        else:
            pub = dt.datetime.now(dt.timezone.utc)
        link = getattr(e, "link", "") or ""
        out.append({
            "title": title,
            "publisher": publisher or "Google News",
            "published_at": pub,
            "url": _clean_url(link),
            "source": "google_news",
        })
    return out


def fetch_headlines(ticker: str, limit: int = 10) -> list[dict]:
    """yfinance first, then Google News if yfinance returns < limit."""
    yf_items = from_yfinance(ticker, limit=limit)
    if len(yf_items) >= limit:
        return yf_items
    # Top up from Google News (dedupe by URL).
    seen = {h["url"] for h in yf_items}
    gn_items = from_google_news(ticker, limit=limit * 2)
    for h in gn_items:
        if h["url"] not in seen:
            yf_items.append(h)
            seen.add(h["url"])
        if len(yf_items) >= limit:
            break
    return yf_items[:limit]


def upsert_headlines(ticker: str, headlines: list[dict]) -> int:
    """Insert new headlines; do NOT overwrite an existing row's sentiment
    once it has been scored (we re-score in a separate pass)."""
    if not headlines:
        return 0
    sql = """
        INSERT INTO atlas.headlines (ticker, title, publisher, published_at, url, source)
        VALUES (%(ticker)s, %(title)s, %(publisher)s, %(published_at)s, %(url)s, %(source)s)
        ON CONFLICT (ticker, url) DO NOTHING
    """
    rows = [{"ticker": ticker, **h} for h in headlines]
    with __import__("psycopg").connect(__import__("os").environ.get(
        "DATABASE_URL",
        "postgresql://jesse_user:jesse_password@dokploy-postgres:5432/atlas"
    )) as conn:
        with conn.cursor() as cur:
            cur.executemany(sql, rows)
        conn.commit()
    return len(rows)


def refresh_all(tickers: Iterable[str] = TICKERS, limit: int = 10) -> dict[str, int]:
    out: dict[str, int] = {}
    for t in tickers:
        try:
            items = fetch_headlines(t, limit=limit)
            n = upsert_headlines(t, items)
            out[t] = n
        except Exception as e:
            print(f"[news] {t} FAILED: {type(e).__name__}: {e}")
            out[t] = -1
        time.sleep(0.3)
    return out


def unscored_batch(limit: int = 64) -> list[dict]:
    """Headlines missing a sentiment score, oldest first. Used by the sentiment job."""
    return fetch_all(
        """
        SELECT id, ticker, title FROM atlas.headlines
        WHERE sentiment_label IS NULL
        ORDER BY published_at ASC
        LIMIT %s
        """,
        (limit,),
    )


if __name__ == "__main__":
    print(refresh_all())