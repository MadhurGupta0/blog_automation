#!/bin/sh
set -e

echo "Starting blog automation cron (every 2 days)..."

# Run once immediately on container start
echo "[$(date)] Running initial blog automation..."
python /app/blogautomation.py

# Then loop every 2 days (172800 seconds)
while true; do
    sleep 172800
    echo "[$(date)] Running scheduled blog automation..."
    python /app/blogautomation.py
done
