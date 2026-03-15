#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────────
# run_all.sh — Start all 4 drone swarm services in background
# Usage: bash scripts/run_all.sh
# Ctrl+C kills everything cleanly.
# ─────────────────────────────────────────────────────────────────────

set -e

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT_DIR"

PIDS=()

cleanup() {
  echo ""
  echo "Shutting down all services..."
  for pid in "${PIDS[@]}"; do
    kill "$pid" 2>/dev/null && echo "  Killed PID $pid" || true
  done
  wait 2>/dev/null
  echo "All services stopped."
  exit 0
}

trap cleanup SIGINT SIGTERM

echo "═══════════════════════════════════════════════════"
echo "  Drone Swarm Rescue — Starting All Services"
echo "═══════════════════════════════════════════════════"
echo ""

# 1. MCP Server
echo "[1/4] Starting MCP Server on :8000..."
python -m mcp_server.server &
PIDS+=($!)
echo "       PID: ${PIDS[-1]}"
sleep 2

# 2. API Bridge
echo "[2/4] Starting API Bridge on :8001..."
uvicorn api.bridge:app --port 8001 --reload &
PIDS+=($!)
echo "       PID: ${PIDS[-1]}"
sleep 1

# 3. Agent Runner
echo "[3/4] Starting Agent Runner..."
python -m agent.runner &
PIDS+=($!)
echo "       PID: ${PIDS[-1]}"
sleep 1

# 4. Frontend
echo "[4/4] Starting Next.js Dashboard on :3000..."
cd dashboard && npm run dev &
PIDS+=($!)
echo "       PID: ${PIDS[-1]}"
cd "$ROOT_DIR"

echo ""
echo "═══════════════════════════════════════════════════"
echo "  All services running!"
echo ""
echo "  MCP Server:   http://localhost:8000/mcp"
echo "  API Bridge:   http://localhost:8001"
echo "  Dashboard:    http://localhost:3000"
echo ""
echo "  Press Ctrl+C to stop all services."
echo "═══════════════════════════════════════════════════"

# Wait for any child to exit
wait
