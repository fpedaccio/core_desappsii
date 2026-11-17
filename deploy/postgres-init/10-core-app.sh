#!/bin/sh
# Runs only when the official PostgreSQL image initializes an empty volume.
set -eu
: "${APP_DB_PASSWORD:?APP_DB_PASSWORD must be configured}"
psql --set=ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" \
    --set=app_password="$APP_DB_PASSWORD" --set=db_name="$POSTGRES_DB" <<'SQL'
CREATE ROLE core_app LOGIN PASSWORD :'app_password'
    NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION;
GRANT CONNECT ON DATABASE :"db_name" TO core_app;
GRANT USAGE, CREATE ON SCHEMA public TO core_app;
SQL
