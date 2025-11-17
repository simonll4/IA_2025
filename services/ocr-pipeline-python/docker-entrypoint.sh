#!/bin/bash
set -e

# Ensure data directories exist with correct permissions
mkdir -p /app/data/uploads /app/data/processed /app/data/cache

# Ensure the database directory is writable
# If the database file doesn't exist, SQLAlchemy will create it
# If it exists but is read-only, try to fix permissions
DB_FILE="/app/data/app.db"
if [ -f "$DB_FILE" ]; then
    # Check if we can write to it
    if [ ! -w "$DB_FILE" ]; then
        echo "⚠️  Database file exists but is read-only. Attempting to fix permissions..."
        chmod 666 "$DB_FILE" 2>/dev/null || echo "⚠️  Could not change permissions on $DB_FILE"
    fi
fi

# Ensure the data directory is writable
if [ ! -w "/app/data" ]; then
    echo "⚠️  Data directory is not writable. Attempting to fix permissions..."
    chmod 755 /app/data 2>/dev/null || echo "⚠️  Could not change permissions on /app/data"
fi

echo "✓ Data directory permissions verified"

# Execute the main command
exec "$@"
