"""SEC EDGAR fetcher: CIK mapping + XBRL companyfacts + submissions.

Reads ticker->CIK from https://www.sec.gov/files/company_tickers.json (cached
in-process; the file is ~150KB and changes rarely). Pulls Revenue /
NetIncomeLoss / DilutedEPS / GrossProfit from
https://data.sec.gov/api/xbrl/companyfacts/CIK{padded}.json. Falls back
to the alternate revenue concept name when a filer only tags one.

Per-ticker output: 8 most-recent reported (period_end, form) rows for
fundamentals, and 8 most-recent 10-K/10-Q/8-K filings.

Writes into atlas.fundamentals / atlas.filings (upsert).
"""
from __future__ import annotations

import datetime as dt
import time
from typing import Iterable

import httpx

from .config import SEC_USER_AGENT
from .db import execute

# Source order matters: prefer the modern ASC 606 concept first, fall back
# to the legacy "Revenues" used by older filers (e.g. AAPL pre-2018).
_REVENUE_KEYS: tuple[str, ...] = (
    "RevenueFromContractWithCustomerExcludingAssessedRevenue",
    "Revenues",
    "RevenueFromContractWithCustomerIncludingAssessedRevenue",
)
_EPS_KEYS: tuple[str, ...] = ("EarningsPerShareDiluted", "EarningsPerShareBasic")
# Filers diverge on the exact revenue suffix; if the curated list has no
# points we scan us-gaap for a revenue-flavoured name. Prefer ASC 606
# (RevenueFromContractWith*) — generic SalesRevenueNet is segment-level.
_REVENUE_FALLBACK_PREFIXES = (
    "RevenueFromContractWithCustomer",
    "Revenues",
    "SalesRevenueNet",
)

_HEADERS = {"User-Agent": SEC_USER_AGENT, "Accept-Encoding": "gzip, deflate"}
_BASE = "https://data.sec.gov"
_RPS_PAUSE = 0.15  # stay under 10 req/s
_TICKER_MAP_URL = "https://www.sec.gov/files/company_tickers.json"

# Lazy, in-process CIK cache: {upper(ticker) -> str(10-digit CIK)}.
_CIK_CACHE: dict[str, str] = {}


def _padded_cik(cik: int | str) -> str:
    return str(cik).zfill(10)


def _get_ticker_map() -> dict[str, str]:
    """{UPPER_TICKER -> 10-digit zero-padded CIK}. Cached for process lifetime."""
    if _CIK_CACHE:
        return _CIK_CACHE
    with _client() as client:
        raw = client.get(_TICKER_MAP_URL).json()
    # Source shape: {"0": {"cik_str": 320193, "ticker": "AAPL", "title": "..."}, ...}
    for row in raw.values():
        tk = str(row["ticker"]).upper()
        _CIK_CACHE[tk] = _padded_cik(row["cik_str"])
    return _CIK_CACHE


def resolve_cik(ticker: str) -> str | None:
    return _get_ticker_map().get(ticker.upper())


# ---------- low-level SEC fetch ----------

def _client() -> httpx.Client:
    return httpx.Client(headers=_HEADERS, timeout=30, http2=False)


def _fetch_json(client: httpx.Client, url: str) -> dict | None:
    """GET url; return JSON or None (404 / parse error). Sleeps to respect rate."""
    try:
        r = client.get(url)
    except httpx.HTTPError:
        time.sleep(_RPS_PAUSE)
        return None
    time.sleep(_RPS_PAUSE)
    if r.status_code != 200:
        return None
    return r.json()


# ---------- series assembly ----------

def _concept_series(us_gaap: dict, *names: str) -> list[dict]:
    """Return [{end, form, val}, ...] for the first present concept across *names*.

    Filters to 10-K / 10-Q (drops amendments / 8-K restatements), de-dups on
    (end, form) keeping the most-recently-filed value.
    """
    for name in names:
        node = us_gaap.get(name)
        if not node:
            continue
        return _rows_from(node)
    return []


def _rows_from(node: dict) -> list[dict]:
    units = next(iter(node["units"].values()))  # one unit per concept
    rows = [
        {"end": p["end"], "form": p["form"], "filed": p["filed"], "val": p["val"]}
        for p in units
        if p.get("form") in ("10-K", "10-Q")
    ]
    # dedupe on (end, form): later-filed wins (covers restatements).
    latest: dict[tuple[str, str], dict] = {}
    for r in rows:
        key = (r["end"], r["form"])
        cur = latest.get(key)
        if cur is None or r["filed"] > cur["filed"]:
            latest[key] = r
    return sorted(latest.values(), key=lambda r: r["end"], reverse=True)


def _pick_revenue(us_gaap: dict) -> list[dict]:
    # Pick the revenue-flavoured concept whose most-recent 10-K/10-Q period is
    # the latest — that's the one the filer is actually reporting now (many
    # keep their old concept around for years of history).
    best = None  # (last_end, node)
    for k, v in us_gaap.items():
        if not any(k == p or k.startswith(p)
                   for p in (*_REVENUE_KEYS, *_REVENUE_FALLBACK_PREFIXES)):
            continue
        units = next(iter(v["units"].values()))
        recent_ends = [p["end"] for p in units if p.get("form") in ("10-K", "10-Q")]
        if not recent_ends:
            continue
        last = max(recent_ends)
        if best is None or last > best[0]:
            best = (last, v)
    return _rows_from(best[1]) if best else []


def _build_quarters(us_gaap: dict) -> list[dict]:
    rev = _pick_revenue(us_gaap)
    ni = _concept_series(us_gaap, "NetIncomeLoss")
    eps = _concept_series(us_gaap, *_EPS_KEYS)
    gp = _concept_series(us_gaap, "GrossProfit")
    by_key: dict[tuple[str, str], dict] = {}
    for series, key in (
        (rev, "revenue"), (ni, "net_income"),
        (eps, "diluted_eps"), (gp, "gross_profit"),
    ):
        for p in series:
            slot = by_key.setdefault((p["end"], p["form"]), {
                "period_end": p["end"], "form": p["form"],
            })
            slot[key] = float(p["val"])
    q = sorted(by_key.values(), key=lambda r: r["period_end"], reverse=True)[:8]
    for row in q:
        rev_v = row.get("revenue")
        gp_v = row.pop("gross_profit", None)  # schema stores the ratio, not raw
        ni_v = row.get("net_income")
        row["gross_margin"] = (gp_v / rev_v) if (rev_v and gp_v is not None) else None
        row["net_margin"] = (ni_v / rev_v) if (rev_v and ni_v is not None) else None
    return q


# ---------- public API ----------

def fetch_fundamentals(ticker: str) -> dict:
    """Return {ticker, cik, quarters[8], fetched_at} or {ticker, error, fetched_at}."""
    ticker = ticker.upper()
    fetched_at = dt.datetime.now(dt.timezone.utc).isoformat()
    cik = resolve_cik(ticker)
    if not cik:
        return {"ticker": ticker, "error": "no SEC data", "fetched_at": fetched_at}
    with _client() as client:
        facts = _fetch_json(client, f"{_BASE}/api/xbrl/companyfacts/CIK{cik}.json")
    if not facts or "facts" not in facts:
        return {"ticker": ticker, "error": "no SEC data", "fetched_at": fetched_at}
    us_gaap = facts["facts"].get("us-gaap", {})
    quarters = _build_quarters(us_gaap)
    return {"ticker": ticker, "cik": cik, "quarters": quarters, "fetched_at": fetched_at}


def fetch_filings(ticker: str) -> list[dict]:
    ticker = ticker.upper()
    cik = resolve_cik(ticker)
    if not cik:
        return []
    with _client() as client:
        sub = _fetch_json(client, f"{_BASE}/submissions/CIK{cik}.json")
    if not sub:
        return []
    recent = sub.get("filings", {}).get("recent") or {}
    forms = recent.get("form") or []
    out: list[dict] = []
    cik_int = str(int(cik))  # archive path drops the leading zeros
    for i, form in enumerate(forms):
        if form not in ("10-K", "10-Q", "8-K"):
            continue
        accn = recent["accessionNumber"][i]
        out.append({
            "form": form,
            "filed_at": recent["filingDate"][i],
            "period_of_report": recent.get("reportDate", [None] * len(forms))[i],
            "accession_no": accn,
            "primary_doc": recent.get("primaryDocument", [None] * len(forms))[i],
            "url": f"https://www.sec.gov/Archives/edgar/data/{cik_int}/{accn.replace('-', '')}/{recent['primaryDocument'][i]}",
        })
    out.sort(key=lambda r: r["filed_at"], reverse=True)
    return out[:8]


# ---------- DB upserts ----------

_FUND_UPSERT = """
INSERT INTO atlas.fundamentals
    (ticker, period_end, form, revenue, net_income, diluted_eps, gross_margin, net_margin)
VALUES (%(ticker)s, %(period_end)s, %(form)s, %(revenue)s, %(net_income)s,
        %(diluted_eps)s, %(gross_margin)s, %(net_margin)s)
ON CONFLICT (ticker, period_end, form) DO UPDATE SET
    revenue       = EXCLUDED.revenue,
    net_income    = EXCLUDED.net_income,
    diluted_eps   = EXCLUDED.diluted_eps,
    gross_margin  = EXCLUDED.gross_margin,
    net_margin    = EXCLUDED.net_margin,
    fetched_at    = now()
"""

_FILING_UPSERT = """
INSERT INTO atlas.filings
    (ticker, form, filed_at, period_of_report, accession_no, primary_doc, url)
VALUES (%(ticker)s, %(form)s, %(filed_at)s, %(period_of_report)s,
        %(accession_no)s, %(primary_doc)s, %(url)s)
ON CONFLICT (ticker, accession_no) DO UPDATE SET
    form             = EXCLUDED.form,
    filed_at         = EXCLUDED.filed_at,
    period_of_report = EXCLUDED.period_of_report,
    primary_doc      = EXCLUDED.primary_doc,
    url              = EXCLUDED.url,
    fetched_at       = now()
"""


def upsert_fundamentals(ticker: str, rows: list[dict]) -> int:
    if not rows:
        return 0
    cols = ("ticker", "period_end", "form", "revenue", "net_income",
            "diluted_eps", "gross_margin", "net_margin")
    payload = [{k: (r.get(k) if k != "ticker" else ticker) for k in cols} for r in rows]
    for p in payload:
        execute(_FUND_UPSERT, p)
    return len(payload)


def upsert_filings(ticker: str, filings: list[dict]) -> int:
    if not filings:
        return 0
    for f in filings:
        f = dict(f, ticker=ticker.upper())
        execute(_FILING_UPSERT, f)
    return len(filings)


# ---------- scheduler entrypoint ----------

def run_full_refresh(tickers: Iterable[str]) -> dict:
    fund_rows = filings_rows = 0
    errors: list[str] = []
    for t in tickers:
        t = t.upper()
        try:
            r = fetch_fundamentals(t)
            if "error" in r:
                errors.append(f"{t}:{r['error']}")
            elif r["quarters"]:
                fund_rows += upsert_fundamentals(t, r["quarters"])
        except Exception as e:  # pragma: no cover
            errors.append(f"{t}:fund:{e!s}")
        try:
            f = fetch_filings(t)
            filings_rows += upsert_filings(t, f)
        except Exception as e:  # pragma: no cover
            errors.append(f"{t}:filings:{e!s}")
    return {"fundamentals_rows": fund_rows, "filings_rows": filings_rows, "errors": errors}


if __name__ == "__main__":  # pragma: no cover
    import sys
    tickers = sys.argv[1:] or ["AAPL"]
    print(run_full_refresh(tickers))
