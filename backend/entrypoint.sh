#!/bin/sh
set -e

# Wait for PostgreSQL to be ready
echo "Waiting for PostgreSQL..."
until pg_isready -h db -p 5432 -U "${POSTGRES_USER:-postgres}"; do
  echo "PostgreSQL is unavailable — sleeping"
  sleep 2
done
echo "PostgreSQL is up."

# Run database migrations
echo "Running alembic upgrade head..."
alembic upgrade head

# Seed demo data
echo "Seeding demo data..."
python -m app.db.seed

# If extra arguments were supplied (e.g. the celery command from docker-compose),
# exec them directly. Otherwise default to the web server.
if [ $# -gt 0 ]; then
  echo "Starting: $*"
  exec "$@"
fi

echo "Starting uvicorn..."
exec uvicorn app.main:app --host 0.0.0.0 --port 8000
