#!/usr/bin/env bash
# Dev-цикл: up / restart / logs / down. Авторизация — один раз через UI
# (та же форма Domyland, что в проде): токен не хранится в файлах репозитория.
set -euo pipefail
cd "$(dirname "$0")/.."

case "${1:-}" in
  up)
    docker compose -f docker-compose.dev.yml up -d
    echo "HA dev: http://localhost:8124 (первый старт — онбординг, создайте admin-пользователя)"
    ;;
  restart)
    docker compose -f docker-compose.dev.yml restart
    ;;
  logs)
    docker compose -f docker-compose.dev.yml logs -f --tail=100
    ;;
  down)
    docker compose -f docker-compose.dev.yml down
    ;;
  *)
    echo "usage: $0 {up|restart|logs|down}" >&2
    exit 1
    ;;
esac
