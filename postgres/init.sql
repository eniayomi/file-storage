-- Create the application user and database
CREATE USER ${APP_USER} WITH PASSWORD '${APP_PASSWORD}';
CREATE DATABASE ${APP_DB};
GRANT ALL PRIVILEGES ON DATABASE ${APP_DB} TO ${APP_USER};

-- Connect to the application database
\c ${APP_DB}

-- Grant schema privileges
GRANT ALL ON SCHEMA public TO ${APP_USER}; 