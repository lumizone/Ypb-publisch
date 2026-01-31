#!/bin/bash
# Script to restart the application

cd /Users/lukasz/YPBv2

# Stop the current application
pkill -9 -f "python.*app.py" && echo "✓ Application stopped" || echo "Application was not running"

# Wait a moment for the process to fully terminate
sleep 2

# Start the application again in background using venv python
nohup .venv/bin/python app.py > /tmp/flask_app.log 2>&1 &

echo "✓ Application restarted in background (PID: $!)"
echo "✓ Logs: /tmp/flask_app.log"
