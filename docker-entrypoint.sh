#!/bin/bash
set -e

# Wait for PostgreSQL if using it
if [ "$DB_TYPE" = "postgres" ]; then
    echo "Waiting for PostgreSQL..."
    while ! curl -s "http://$DB_HOST:$DB_PORT" > /dev/null; do
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