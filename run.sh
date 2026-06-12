#!/usr/bin/env bash
set -e

# Start the FastAPI node server in the background on port 8000
echo "Starting ChainMind node server on port 8000..."
python -m uvicorn node.server:app --host 0.0.0.0 --port 8000 --log-level warning &
NODE_PID=$!

# Give the node server a moment to start
sleep 3

echo "Starting ChainMind dashboard on port 5000..."
python -m streamlit run node/dashboard.py \
    --server.port 5000 \
    --server.address 0.0.0.0 \
    --server.headless true \
    --server.enableCORS false \
    --server.enableXsrfProtection false

# If dashboard exits, kill the node server
kill $NODE_PID 2>/dev/null || true
