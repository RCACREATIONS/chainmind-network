#!/usr/bin/env bash
set -e
echo ""
echo " ================================================"
echo "  IntelliChain Node -- Auto Installer"
echo " ================================================"
echo ""

# ── Python ───────────────────────────────────────────────────────────────────
echo " [1/5] Checking Python..."
PYTHON_EXE=$(command -v python3 2>/dev/null || command -v python 2>/dev/null || echo "")
if [ -z "$PYTHON_EXE" ]; then
    echo "       Python 3 not found. Install with:"
    echo "       Mac:   brew install python3"
    echo "       Linux: sudo apt install python3 python3-venv"
    exit 1
fi
PYVER=$("$PYTHON_EXE" --version 2>&1 | awk '{print $2}')
echo "       Found: Python $PYVER"

# ── Venv ─────────────────────────────────────────────────────────────────────
echo ""
echo " [2/5] Setting up virtual environment..."
if [ -d ".venv" ]; then
    echo "       Already exists."
else
    "$PYTHON_EXE" -m venv .venv
    echo "       Created."
fi
source .venv/bin/activate

# ── Dependencies (with retry) ─────────────────────────────────────────────────
echo ""
echo " [3/5] Installing Python dependencies..."
PIP_OK=0
for attempt in 1 2 3; do
    [ $attempt -gt 1 ] && echo "       Retry attempt $attempt of 3..." && sleep 5
    if pip install --no-cache-dir --prefer-binary --quiet -r requirements.txt; then
        PIP_OK=1
        break
    fi
done
if [ $PIP_OK -eq 0 ]; then
    echo "  ERROR: Dependency install failed after 3 attempts."
    exit 1
fi
echo "       Done."

# ── Ollama (with retry) ───────────────────────────────────────────────────────
echo ""
echo " [4/5] Installing Ollama AI engine..."

if command -v ollama &>/dev/null; then
    echo "       Already installed."
else
    OS="$(uname -s)"
    OLLAMA_OK=0

    if [ "$OS" = "Darwin" ] && command -v brew &>/dev/null; then
        echo "       Installing via Homebrew..."
        for attempt in 1 2 3; do
            [ $attempt -gt 1 ] && echo "       Retry $attempt of 3..." && sleep 10
            if brew install ollama --quiet; then
                OLLAMA_OK=1
                break
            fi
        done
    else
        echo "       Downloading Ollama (~60MB, official script)..."
        for attempt in 1 2 3; do
            [ $attempt -gt 1 ] && echo "       Retry $attempt of 3..." && sleep 10
            if curl -fsSL --retry 5 --retry-delay 10 --retry-connrefused --max-time 300 https://ollama.ai/install.sh | sh; then
                OLLAMA_OK=1
                break
            fi
        done
    fi

    if [ $OLLAMA_OK -eq 1 ]; then
        echo "       Ollama installed."
    else
        echo ""
        echo "  [WARNING] Ollama auto-install failed. Install manually:"
        echo "    Mac:   brew install ollama"
        echo "    Linux: curl -fsSL https://ollama.ai/install.sh | sh"
        echo ""
        echo "  All other components installed successfully."
        echo "  Re-run this script after installing Ollama."
        echo ""
    fi
fi

# ── System check & model recommendations ─────────────────────────────────────
echo ""
echo " [5/5] Detecting your hardware..."
python -c "
from node.system_check import get_system_info, system_summary, get_tier_for_system
info = get_system_info()
print('       ' + system_summary(info))
print('       Recommended tier: ' + get_tier_for_system(info).upper())
" 2>/dev/null || echo "       System check skipped."

mkdir -p data
chmod +x start.sh

echo ""
echo " ================================================"
echo "  Installation complete!"
echo " ================================================"
echo ""
echo "  Your hardware profile is shown above."
echo "  Only models that fit your RAM will be available."
echo ""
echo "  Next steps:"
echo "    ./start.sh model pull tinyllama   Pull the smallest model (~600MB)"
echo "    ./start.sh node                   Start the AI node"
echo "    ./start.sh dashboard              Open the web dashboard"
echo "    ./start.sh all                    Start everything at once"
echo ""
