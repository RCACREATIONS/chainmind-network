#!/usr/bin/env bash
set -e

VENV_ACTIVATE=".venv/bin/activate"

if [ ! -f "$VENV_ACTIVATE" ]; then
    echo "Virtual environment not found. Run ./install.sh first."
    exit 1
fi
source "$VENV_ACTIVATE"

OLLAMA_EXE=""
if command -v ollama &>/dev/null; then
    OLLAMA_EXE="ollama"
fi

CMD="${1:-help}"

_start_ollama() {
    if [ -n "$OLLAMA_EXE" ]; then
        if ! pgrep -x ollama > /dev/null 2>&1; then
            echo "Starting Ollama in background..."
            "$OLLAMA_EXE" serve &>/dev/null &
            sleep 2
        fi
    else
        echo "[WARNING] Ollama not found. Install from https://ollama.ai/download"
    fi
}

case "$CMD" in
    node)
        python -m node.setup_wizard
        _start_ollama
        echo "Starting ChainMind node..."
        python -m node.cli node start
        ;;
    dashboard)
        python -m node.cli dashboard
        ;;
    all)
        python -m node.setup_wizard
        _start_ollama
        echo "Starting node in background..."
        python -m node.cli node start &
        sleep 3
        echo "Opening dashboard..."
        python -m node.cli dashboard
        ;;
    status)
        python -m node.cli node status
        ;;
    model)
        shift
        python -m node.cli model "$@"
        ;;
    network)
        shift
        python -m node.cli network "$@"
        ;;
    ask)
        shift
        python -m node.cli ask "$@"
        ;;
    leaderboard)
        python -m node.cli leaderboard
        ;;
    *)
        echo ""
        echo "  ChainMind Network"
        echo ""
        echo "  Usage: ./start.sh <command> [options]"
        echo ""
        echo "  Node:"
        echo "    node              Start the AI node server"
        echo "    dashboard         Open the web dashboard"
        echo "    all               Start node + dashboard together"
        echo "    status            Show node status and stats"
        echo ""
        echo "  Models:"
        echo "    model list        List installed models"
        echo "    model catalog     Browse models by size"
        echo "    model pull NAME   Download a model (e.g. tinyllama)"
        echo "    model delete NAME Remove a model"
        echo ""
        echo "  Quick start:"
        echo "    ./start.sh model pull tinyllama"
        echo "    ./start.sh all"
        echo ""
        ;;
esac
