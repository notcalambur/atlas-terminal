"""Atlas Terminal — Vercel serverless FastAPI entrypoint.

Top-level file so Vercel's Python runtime can find it as the entrypoint
referenced by pyproject.toml's `[tool.vercel] entrypoint = "api:handler"`.
The full app lives in atlas/api.py; this file just exposes the symbol.
"""
from atlas.api import app, handler  # noqa: F401