#!/bin/bash
# Postgres init script — creates both main and test databases
set -e

psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" <<-EOSQL
    CREATE DATABASE ai_badge_test;
    GRANT ALL PRIVILEGES ON DATABASE ai_badge_test TO ai_badge;
EOSQL

echo "Created test database: ai_badge_test"
