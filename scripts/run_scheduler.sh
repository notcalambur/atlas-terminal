#!/usr/bin/env bash
# Atlas Terminal scheduler.
# Run via cron in the VPS (NOT inside Vercel serverless). Crontab example:
#   */15  9-16  * * 1-5  /opt/atlas/run_scheduler.sh prices      # US market hours, weekdays
#   */30  *     * * *    /opt/atlas/run_scheduler.sh news         # news every 30m
#   0  22  *   *  *      /opt/atlas/run_scheduler.sh fundamentals # daily
#   30  22 *   *  *      /opt/atlas/run_scheduler.sh fred         # daily
#   */30 *     * * *     /opt/atlas/run_scheduler.sh sentiment    # every 30m (after news)
set -euo pipefail

cd "$(dirname "$0")/.."
export $(grep -v '^#' .env | xargs) || true

case "${1:-all}" in
    prices)
        python3 -m atlas.fetcher ;;
    news)
        python3 -m atlas.news && python3 -m atlas.sentiment ;;
    fundamentals)
        python3 -m atlas.edgar ;;
    fred)
        python3 -m atlas.fred ;;
    sentiment)
        python3 -m atlas.sentiment ;;
    all)
        python3 -m atlas.fetcher
        python3 -m atlas.news
        python3 -m atlas.sentiment
        python3 -m atlas.fred
        python3 -m atlas.edgar
        ;;
    *)
        echo "Usage: $0 {prices|news|fundamentals|fred|sentiment|all}" >&2
        exit 1 ;;
esac