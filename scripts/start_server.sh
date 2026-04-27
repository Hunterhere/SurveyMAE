#!/usr/bin/env bash
set -euo pipefail

HOST="0.0.0.0"
PORT="8000"
LOG_LEVEL="info"
RELOAD="1"

usage() {
  cat <<'USAGE'
Usage:
  scripts/start_server.sh [options]

Options:
  --host VALUE
  --port VALUE
  --log-level VALUE   critical | error | warning | info | debug | trace
  --no-reload
  -h, --help
USAGE
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --host) HOST="$2"; shift 2 ;;
    --port) PORT="$2"; shift 2 ;;
    --log-level) LOG_LEVEL="$2"; shift 2 ;;
    --no-reload) RELOAD="0"; shift ;;
    -h|--help) usage; exit 0 ;;
    *)
      echo "Unknown option: $1" >&2
      usage >&2
      exit 1
      ;;
  esac
done

cd "$(dirname "$0")/.."

cmd=(
  uv run python -m uvicorn
  src.web.app:app
  --host "$HOST"
  --port "$PORT"
  --log-level "$LOG_LEVEL"
)

if [[ "$RELOAD" == "1" ]]; then
  cmd+=(--reload)
fi

echo "========================================"
echo "SurveyMAE Web Server"
echo "========================================"
echo
echo "Starting server at: http://localhost:${PORT}"
echo "Press Ctrl+C to stop"
echo

exec "${cmd[@]}"
