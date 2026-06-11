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

# Start the application
echo "Starting uvicorn..."
exec uvicorn app.main:app --host 0.0.0.0 --port 8000
