#!/bin/bash
set -e

# Wait for PostgreSQL if using it
if [ "$DB_TYPE" = "postgres" ]; then
    echo "Waiting for PostgreSQL..."
    until pg_isready -h "$DB_HOST" -p "$DB_PORT" -U "$DB_USER"; do
        echo "PostgreSQL is unavailable - sleeping"
        sleep 1
    done
    echo "PostgreSQL is up"
fi

# Run database migrations
echo "Running database migrations..."
alembic upgrade head

# Start the application
echo "Starting application..."
exec uvicorn main:app --host 0.0.0.0 --port 8000 