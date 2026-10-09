#!/usr/bin/env bash
# Run without Docker (Python 3.10+). Usage: ./scripts/run-local.sh
set -euo pipefail
cd "$(dirname "$0")/.."
[ -f .env ] || { echo ".env 파일이 없습니다. cp .env.example .env 후 값을 채우세요." >&2; exit 1; }
if [ ! -d .venv ]; then
  python3 -m venv .venv
  .venv/bin/pip install --upgrade pip >/dev/null
  .venv/bin/pip install -r requirements.txt
fi
set -a; . ./.env; set +a
mkdir -p data
echo "RAGAS 실험실: http://${BIND_HOST:-127.0.0.1}:${PORT:-8030}"
exec .venv/bin/uvicorn app.main:build --factory --host "${BIND_HOST:-127.0.0.1}" --port "${PORT:-8030}" --loop asyncio
