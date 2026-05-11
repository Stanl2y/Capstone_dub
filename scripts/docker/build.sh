#!/usr/bin/env bash
set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
COMPOSE_FILE="$PROJECT_ROOT/docker-compose.yml"
SERVICES=("$@")

if [[ ${#SERVICES[@]} -eq 0 ]]; then
  SERVICES=(controller separator diarizer speaker tts-cosyvoice)
fi

"$PROJECT_ROOT/scripts/docker/check-host.sh"

cd "$PROJECT_ROOT"
for service in "${SERVICES[@]}"; do
  echo "[build] $service"
  docker compose -f "$COMPOSE_FILE" --progress plain build "$service"
done
