#!/bin/sh
set -e

echo "[entrypoint] Installing git..."
apt-get update -qq && apt-get install -y --no-install-recommends git > /dev/null

echo "[entrypoint] Pulling latest code..."
git pull || echo "[entrypoint] WARNING: git pull failed, continuing with existing code"

echo "[entrypoint] Installing Python dependencies..."
pip install --no-cache-dir -r requirements.txt

echo "[entrypoint] Starting NewsFeed app..."
exec python -m src.main
