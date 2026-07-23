#!/bin/sh
set -eu

if ! docker info >/dev/null 2>&1; then
    echo "Docker Desktop is not running. Start it, then run tests/run.sh again." >&2
    exit 1
fi

exec docker compose -f docker-compose.test.yml run --rm integration-tests "$@"
