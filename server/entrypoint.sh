#!/bin/sh
set -eu

export PURERETA_ROOT=/app
export PORT="${PORT:-80}"

python3 -c "
import sys
sys.path.insert(0, '/app/server')
from db import init_db
init_db()
"

python3 /app/server/bambu/sync_worker.py &
exec python3 /app/server/purereta_server.py
