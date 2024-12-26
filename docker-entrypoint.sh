#!/bin/bash
set -e

if [ "$DB_TYPE" = "postgres" ]; then
    echo "Waiting for PostgreSQL..."
    until pg_isready -h "$DB_HOST" -p "$DB_PORT" -U "postgres"; do
        echo "PostgreSQL is unavailable - sleeping"
        sleep 1
    done
    echo "PostgreSQL is up"

    # Create database and user if they don't exist
    echo "Setting up database and user..."
    PGPASSWORD=$POSTGRES_PASSWORD psql -h "$DB_HOST" -p "$DB_PORT" -U "postgres" <<-EOSQL
        -- Create user if not exists
        DO \$\$
        BEGIN
            IF NOT EXISTS (SELECT FROM pg_user WHERE usename = '$DB_USER') THEN
                CREATE USER $DB_USER WITH PASSWORD '$DB_PASSWORD';
            END IF;
        END
        \$\$;

        -- Create database if not exists
        SELECT 'CREATE DATABASE $DB_NAME'
        WHERE NOT EXISTS (SELECT FROM pg_database WHERE datname = '$DB_NAME')\gexec

        -- Grant privileges
        GRANT ALL PRIVILEGES ON DATABASE $DB_NAME TO $DB_USER;
        
        -- Connect to the database and grant schema privileges
        \c $DB_NAME
        GRANT ALL ON SCHEMA public TO $DB_USER;
EOSQL
    echo "Database setup completed"
fi

# Run database migrations
echo "Running database migrations..."
alembic upgrade head

# Start the application
echo "Starting application..."
exec uvicorn main:app --host 0.0.0.0 --port 8000 