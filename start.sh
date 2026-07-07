#!/bin/bash
# ChainMind startup — node server (with watchdog) + Streamlit dashboard

set -e

mkdir -p data/logs

# ── Preflight: free ports if already occupied ─────────────────────────────────
for PORT in 8000 5000; do
  OLDPID=$(lsof -ti:"$PORT" 2>/dev/null || true)
  if [ -n "$OLDPID" ]; then
    echo "Port $PORT in use by PID $OLDPID — releasing..."
    kill -9 "$OLDPID" 2>/dev/null || true
    sleep 1
  fi
done

# ── Cleanup on exit: kill all child jobs ─────────────────────────────────────
cleanup() {
  echo "Shutting down ChainMind..."
  jobs -p | xargs kill 2>/dev/null || true
  wait 2>/dev/null || true
}
trap cleanup EXIT SIGINT SIGTERM

# ── Node server watchdog: restart on crash ────────────────────────────────────
node_watchdog() {
  while true; do
    echo "[node] Starting on port 8000..."
    python -m uvicorn node.server:app --host 0.0.0.0 --port 8000 --log-level info
    EC=$?
    echo "[node] Exited (code $EC). Restarting in 5 s..."
    sleep 5
  done
}

node_watchdog &

echo "Waiting for node server to start..."
sleep 3

# ── Dashboard: run in foreground (workflow alive while dashboard is up) ───────
echo "Starting ChainMind dashboard on port 5000..."
exec python -m streamlit run node/dashboard.py \
  --server.port 5000 \
  --server.address 0.0.0.0 \
  --server.headless true \
  --server.enableCORS false \
  --server.enableXsrfProtection false
