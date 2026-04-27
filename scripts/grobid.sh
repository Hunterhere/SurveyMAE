#!/usr/bin/env bash
set -euo pipefail

ACTION="start"
IMAGE="grobid/grobid:0.9.0-crf"
CONTAINER_NAME="grobid"
PORT="8070"
MEMORY="8g"
LOG_MAX_SIZE="10m"
LOG_MAX_FILE="5"
LOGS_TAIL="200"
HEALTH_RETRIES="60"
HEALTH_INTERVAL_SEC="2"
HEALTH_TIMEOUT_SEC="5"

usage() {
  cat <<'USAGE'
Usage:
  scripts/grobid.sh [action] [options]

Actions:
  start | stop | restart | status | logs | rm

Options:
  --action VALUE
  --image VALUE
  --container-name VALUE
  --port VALUE
  --memory VALUE
  --log-max-size VALUE
  --log-max-file VALUE
  --logs-tail VALUE
  --health-retries VALUE
  --health-interval-sec VALUE
  --health-timeout-sec VALUE
  -h, --help
USAGE
}

if [[ $# -gt 0 && "$1" != --* && "$1" != "-h" ]]; then
  ACTION="$1"
  shift
fi

while [[ $# -gt 0 ]]; do
  case "$1" in
    --action) ACTION="$2"; shift 2 ;;
    --image) IMAGE="$2"; shift 2 ;;
    --container-name) CONTAINER_NAME="$2"; shift 2 ;;
    --port) PORT="$2"; shift 2 ;;
    --memory) MEMORY="$2"; shift 2 ;;
    --log-max-size) LOG_MAX_SIZE="$2"; shift 2 ;;
    --log-max-file) LOG_MAX_FILE="$2"; shift 2 ;;
    --logs-tail) LOGS_TAIL="$2"; shift 2 ;;
    --health-retries) HEALTH_RETRIES="$2"; shift 2 ;;
    --health-interval-sec) HEALTH_INTERVAL_SEC="$2"; shift 2 ;;
    --health-timeout-sec) HEALTH_TIMEOUT_SEC="$2"; shift 2 ;;
    -h|--help) usage; exit 0 ;;
    *)
      echo "Unknown option: $1" >&2
      usage >&2
      exit 1
      ;;
  esac
done

container_id() {
  docker ps -a --filter "name=^/${CONTAINER_NAME}$" --format "{{.ID}}"
}

is_running() {
  local state
  state="$(docker inspect -f '{{.State.Running}}' "$CONTAINER_NAME" 2>/dev/null || true)"
  [[ "$state" == "true" ]]
}

mapped_host_port() {
  if [[ -z "$(container_id)" ]]; then
    return 0
  fi

  local port_line
  port_line="$(docker port "$CONTAINER_NAME" 8070/tcp 2>/dev/null | head -n 1 || true)"
  if [[ "$port_line" =~ :([0-9]+)$ ]]; then
    echo "${BASH_REMATCH[1]}"
  fi
}

ensure_image() {
  if ! docker image inspect "$IMAGE" >/dev/null 2>&1; then
    echo "Image not found. Pulling $IMAGE ..."
    docker pull "$IMAGE"
  fi
}

start_container() {
  ensure_image

  if [[ -n "$(container_id)" ]]; then
    docker update --memory "$MEMORY" --memory-swap "$MEMORY" "$CONTAINER_NAME" >/dev/null
    if is_running; then
      echo "Container '$CONTAINER_NAME' is already running."
      return
    fi
    echo "Starting existing container '$CONTAINER_NAME' ..."
    docker start "$CONTAINER_NAME" >/dev/null
    return
  fi

  echo "Creating and starting container '$CONTAINER_NAME' ..."
  docker run -d --name "$CONTAINER_NAME" --restart unless-stopped --init --ulimit core=0 \
    -p "${PORT}:8070" \
    --memory "$MEMORY" --memory-swap "$MEMORY" \
    --log-opt "max-size=${LOG_MAX_SIZE}" --log-opt "max-file=${LOG_MAX_FILE}" \
    "$IMAGE" >/dev/null
}

stop_container() {
  if [[ -z "$(container_id)" ]]; then
    echo "Container '$CONTAINER_NAME' does not exist."
    return
  fi
  docker stop "$CONTAINER_NAME" >/dev/null
}

restart_container() {
  if [[ -z "$(container_id)" ]]; then
    start_container
    return
  fi
  docker restart "$CONTAINER_NAME" >/dev/null
}

status_container() {
  local rows
  rows="$(docker ps -a --filter "name=^/${CONTAINER_NAME}$" --format "{{.Names}}\t{{.Status}}\t{{.Ports}}\t{{.Image}}")"
  if [[ -z "$rows" ]]; then
    echo "Container '$CONTAINER_NAME' not found."
    return
  fi
  printf "NAMES\tSTATUS\tPORTS\tIMAGE\n"
  printf "%b\n" "$rows"
}

logs_container() {
  if [[ -z "$(container_id)" ]]; then
    echo "Container '$CONTAINER_NAME' does not exist."
    return
  fi
  docker logs --tail "$LOGS_TAIL" -f "$CONTAINER_NAME"
}

remove_container() {
  if [[ -z "$(container_id)" ]]; then
    echo "Container '$CONTAINER_NAME' does not exist."
    return
  fi
  docker rm -f "$CONTAINER_NAME" >/dev/null
}

health_check() {
  local start_ts elapsed mapped_port health_port url
  start_ts="$(date +%s)"
  mapped_port="$(mapped_host_port)"
  health_port="${mapped_port:-$PORT}"

  if [[ -n "$mapped_port" && "$mapped_port" != "$PORT" ]]; then
    echo "Container maps 8070/tcp to host port $mapped_port (requested --port=$PORT). Health check will use $mapped_port."
  fi
  if [[ -z "$mapped_port" ]]; then
    echo "No host port mapping found for container 8070/tcp. Health check will try --port=$PORT."
    echo "If this container was created without '-p ${PORT}:8070', recreate it:"
    echo "  scripts/grobid.sh rm"
    echo "  scripts/grobid.sh start --port $PORT"
  fi

  url="http://localhost:${health_port}/api/isalive"
  for ((i = 1; i <= HEALTH_RETRIES; i++)); do
    if curl -fsS --max-time "$HEALTH_TIMEOUT_SEC" "$url" >/dev/null 2>&1; then
      elapsed="$(( $(date +%s) - start_ts ))"
      echo "GROBID is alive at $url (ready in ${elapsed}s)"
      return 0
    fi
    if [[ "$i" -lt "$HEALTH_RETRIES" ]]; then
      sleep "$HEALTH_INTERVAL_SEC"
    fi
  done

  echo "GROBID health check failed at $url after $HEALTH_RETRIES attempts."
  echo "Container status:"
  status_container
  echo "Recent container logs:"
  docker logs --tail "$LOGS_TAIL" "$CONTAINER_NAME" || true
  return 1
}

case "$ACTION" in
  start)
    start_container
    health_check
    ;;
  stop)
    stop_container
    ;;
  restart)
    restart_container
    health_check
    ;;
  status)
    status_container
    ;;
  logs)
    logs_container
    ;;
  rm)
    remove_container
    ;;
  *)
    echo "Usage: $0 {start|stop|restart|status|logs|rm}" >&2
    exit 1
    ;;
esac
