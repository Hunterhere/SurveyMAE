#!/usr/bin/env bash
set -euo pipefail

ACTION="${1:-start}"

IMAGE="grobid/grobid:0.8.2-full"
CONTAINER_NAME="grobid"
PORT="8070"
LOG_MAX_SIZE="10m"
LOG_MAX_FILE="5"
LOGS_TAIL="200"

container_id() {
  docker ps -a --filter "name=^/${CONTAINER_NAME}$" --format "{{.ID}}"
}

is_running() {
  local state
  state="$(docker inspect -f '{{.State.Running}}' "$CONTAINER_NAME" 2>/dev/null || true)"
  [[ "$state" == "true" ]]
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
  docker ps -a --filter "name=^/${CONTAINER_NAME}$" \
    --format "table {{.Names}}\t{{.Status}}\t{{.Ports}}\t{{.Image}}"
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
  local url="http://localhost:${PORT}/api/isalive"
  if curl -fsS "$url" >/dev/null 2>&1; then
    echo "GROBID is alive at $url"
  else
    echo "GROBID health check failed at $url"
  fi
}

case "$ACTION" in
  start)
    start_container
    sleep 2
    health_check
    ;;
  stop)
    stop_container
    ;;
  restart)
    restart_container
    sleep 2
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
    echo "Usage: $0 {start|stop|restart|status|logs|rm}"
    exit 1
    ;;
esac
