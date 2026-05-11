#!/usr/bin/env bash
set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
COMPOSE_FILE="$PROJECT_ROOT/docker-compose.yml"
SERVICES=("$@")

if [[ ${#SERVICES[@]} -eq 0 ]]; then
  SERVICES=(controller separator diarizer speaker tts-cosyvoice)
fi

declare -A IMAGES=(
  [controller]="movie-dubbing/controller:local"
  [separator]="movie-dubbing/separator:local"
  [diarizer]="movie-dubbing/diarizer:local"
  [speaker]="movie-dubbing/speaker:local"
  [tts-cosyvoice]="movie-dubbing/tts-cosyvoice:local"
)

"$PROJECT_ROOT/scripts/docker/check-host.sh"

cd "$PROJECT_ROOT"

missing_services=()
for service in "${SERVICES[@]}"; do
  image="${IMAGES[$service]:-}"
  if [[ -z "$image" ]]; then
    echo "[error] unknown service: $service"
    exit 1
  fi

  if ! docker image inspect "$image" >/dev/null 2>&1; then
    missing_services+=("$service")
  fi
done

if [[ ${#missing_services[@]} -gt 0 ]]; then
  echo "[info] building missing images: ${missing_services[*]}"
  "$PROJECT_ROOT/scripts/docker/build.sh" "${missing_services[@]}"
fi

docker compose -f "$COMPOSE_FILE" up -d --no-build "${SERVICES[@]}"
docker compose -f "$COMPOSE_FILE" ps
