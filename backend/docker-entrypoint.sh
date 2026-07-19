#!/bin/sh
# Runs pending Alembic migrations, then starts the API server. Baked into the image (rather
# than passed as a platform-specific "start command" string) so it behaves identically whether
# launched by `docker run`, docker-compose, or a host like Render whose dockerCommand field does
# NOT reliably shell-parse `&&`/env-var chains passed inline in render.yaml.
set -e

# alembic/env.py reads ALEMBIC_DATABASE_URL specifically (see alembic/env.py); fall back to
# DATABASE_URL so callers only have to set one variable.
export ALEMBIC_DATABASE_URL="${ALEMBIC_DATABASE_URL:-$DATABASE_URL}"

alembic upgrade head
exec uvicorn app.main:app --host 0.0.0.0 --port "${PORT:-8000}"
