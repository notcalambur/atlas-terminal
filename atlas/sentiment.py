"""FinBERT sentiment. Loaded lazily on first call.

We intentionally do NOT preload the model at import time — keeps `import atlas`
cheap and means the FastAPI serverless never touches the model (sentiment is
pre-computed by the scheduler). Run from the scheduler only.

ProsusAI/finbert is the canonical model. CPU inference is fine for ~50-200
headlines per minute on a modern CPU; for our scale (≤ 11 tickers × 10
headlines / 30 min) this is more than enough.
"""
from __future__ import annotations

from functools import lru_cache

from .db import execute


_MODEL_NAME = "ProsusAI/finbert"
_LABEL_MAP = {0: "positive", 1: "negative", 2: "neutral"}


@lru_cache(maxsize=1)
def _pipeline():
    """Lazy: only load on first call. CPU is fine."""
    from transformers import pipeline
    return pipeline("sentiment-analysis", model=_MODEL_NAME, device=-1)


def score_headline(title: str) -> dict:
    """Score one headline. Returns {'label': 'positive'|'neutral'|'negative', 'score': 0..1}."""
    pipe = _pipeline()
    out = pipe(title[:512])[0]   # FinBERT truncates at 512 tokens anyway.
    # transformers returns label like 'positive'/'negative'/'neutral' already.
    label = out["label"].lower()
    score = float(out["score"])
    return {"label": label, "score": score}


def score_batch(headlines: list[dict]) -> list[dict]:
    """Score a batch of {id, ticker, title}. Returns same rows with label/score."""
    if not headlines:
        return []
    pipe = _pipeline()
    titles = [h["title"][:512] for h in headlines]
    results = pipe(titles, batch_size=16)
    out = []
    for h, r in zip(headlines, results):
        out.append({
            "id": h["id"],
            "label": r["label"].lower(),
            "score": float(r["score"]),
        })
    return out


def apply_scores(scored: list[dict]) -> int:
    """Persist label+score back to atlas.headlines. Returns rows updated."""
    if not scored:
        return 0
    sql = """
        UPDATE atlas.headlines
        SET sentiment_label = %s, sentiment_score = %s
        WHERE id = %s
    """
    rows = [(s["label"], s["score"], s["id"]) for s in scored]
    with __import__("psycopg").connect(__import__("os").environ.get(
        "DATABASE_URL",
        "postgresql://jesse_user:jesse_password@dokploy-postgres:5432/atlas"
    )) as conn:
        with conn.cursor() as cur:
            cur.executemany(sql, rows)
        conn.commit()
    return len(rows)


def score_pending(limit: int = 64) -> int:
    """Score everything unscored. Used by the scheduler."""
    from .news import unscored_batch
    batch = unscored_batch(limit=limit)
    if not batch:
        return 0
    scored = score_batch(batch)
    return apply_scores(scored)


if __name__ == "__main__":
    print(f"scored {score_pending()} headlines")