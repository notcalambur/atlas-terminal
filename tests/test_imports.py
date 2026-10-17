"""Smoke tests that load each submodule. Verifies imports resolve."""
from __future__ import annotations


def test_imports():
    import atlas
    import atlas.config
    import atlas.db
    import atlas.fetcher
    import atlas.fred
    import atlas.news
    import atlas.risk
    import atlas.sentiment
    assert atlas.__version__