#!/bin/bash
# Start both Telegram bot and monitoring server

# Get the script's directory
SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
cd "$SCRIPT_DIR"

# Activate virtual environment
source venv/bin/activate

# Start monitoring server in background
python telegram_bot/monitoring_server.py > logs/monitoring.log 2>&1 &
MONITOR_PID=$!
echo "Started monitoring server (PID: $MONITOR_PID)"

# Start main bot (this will run in foreground)
python telegram_bot/main.py
