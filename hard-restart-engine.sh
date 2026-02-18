docker compose down --remove-orphans

docker image rm scoringengine/base scoringengine/web scoringengine/bootstrap scoringengine/engine scoringengine/worker 2>/dev/null || true

docker compose build --no-cache base
docker compose build --no-cache bootstrap web engine worker

SCORINGENGINE_OVERWRITE_DB=true docker compose up -d
