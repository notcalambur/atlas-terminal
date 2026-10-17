FROM python:3.12-slim

# System deps for lxml/psycopg
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc libpq-dev libxml2-dev libxslt1-dev git \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Force a fresh checkout every rebuild: invalidate Docker layer cache when
# the commit hash changes (Dokploy passes $COMMIT_SHA but we don't rely on it).
ARG CACHEBUST=unknown
RUN git clone --depth 1 https://github.com/notcalambur/atlas-terminal.git /tmp/repo \
    && cp -r /tmp/repo/. /app/ \
    && rm -rf /tmp/repo

# Install API + scheduler deps. Heavy ML deps for sentiment only needed
# by the scheduler; we install everything here because the scheduler runs
# inside the same container as a separate process.
RUN pip install --no-cache-dir --upgrade pip \
    && pip install --no-cache-dir -r api_requirements.txt \
    && pip install --no-cache-dir -r requirements.txt

# Expose the FastAPI port.
EXPOSE 8000

# Default command runs the API. The scheduler runs as a Dokploy scheduled
# task against the same image (see scripts/run_scheduler.sh).
CMD ["uvicorn", "atlas.api:app", "--host", "0.0.0.0", "--port", "8000"]