# IntelliChain AI Node

Lightweight Python AI node for the Chainmind decentralized intelligence protocol.  
**Runs fully offline. No cloud. No API keys.**

---

## What's inside

| File / Folder | Purpose |
|---|---|
| `node/server.py` | FastAPI node — REST + WebSocket endpoints |
| `node/ollama_client.py` | Async wrapper around Ollama's local HTTP API |
| `node/tasks.py` | Async task queue and inference processor |
| `node/dashboard.py` | Streamlit dashboard (stats, models, chat, log) |
| `node/cli.py` | Typer CLI — pull models, ask questions, check status |
| `node/db.py` | SQLite layer — tasks, stats, IQ earnings |
| `config.yaml` | All config in one place (ports, model catalog) |
| `requirements.txt` | Python dependencies |

---

## Requirements

- Python 3.10+
- ~600 MB free disk (for TinyLlama, the smallest model)
- Internet access only for initial model download

---

## Install

**Linux / macOS**
```bash
chmod +x install.sh start.sh
./install.sh
```

**Windows**
```
install.bat
```

The installer will:
1. Create a Python virtual environment
2. Install all dependencies
3. Install the Ollama CLI (if not already installed)
4. Create the `data/` directory

---

## Quick Start

```bash
# 1. Pull the smallest model (~600 MB)
./start.sh model pull tinyllama

# 2. Start the node (leave this terminal running)
./start.sh node

# 3. Open the dashboard (in a second terminal)
./start.sh dashboard

# OR start everything at once
./start.sh all
```

---

## Available Models

```bash
./start.sh model catalog      # browse all models by size
./start.sh model list         # show installed models
```

| Size | Model | Disk |
|---|---|---|
| Tiny | tinyllama | ~600 MB |
| Tiny | qwen2:0.5b | ~350 MB |
| Tiny | phi3:mini | ~2.3 GB |
| Small | llama3.2:3b | ~2.0 GB |
| Medium | mistral | ~4.1 GB |
| Medium | llama3.1:8b | ~4.7 GB |
| Large | llama3.1:70b | ~40 GB |

---

## Usage

```bash
# One-shot query from terminal
./start.sh ask "Explain quantum entanglement in one sentence"
./start.sh ask "Write a Python function to reverse a string" --model mistral

# Node health check
./start.sh status
```

### REST API (when node is running on port 8000)

```bash
# Health check
curl http://localhost:8000/health

# Queue an inference task
curl -X POST http://localhost:8000/infer \
  -H "Content-Type: application/json" \
  -d '{"prompt": "Hello world", "model": "tinyllama"}'

# Check task result
curl http://localhost:8000/tasks/<task_id>

# List local models
curl http://localhost:8000/models

# Pull a model
curl -X POST http://localhost:8000/models/pull \
  -H "Content-Type: application/json" \
  -d '{"model": "tinyllama"}'

# Node stats (tasks completed, tokens, IQ earned)
curl http://localhost:8000/stats
```

### WebSocket — streaming inference

```python
import asyncio, websockets, json

async def chat():
    async with websockets.connect("ws://localhost:8000/ws/infer") as ws:
        await ws.send(json.dumps({"prompt": "Tell me a joke", "model": "tinyllama"}))
        async for msg in ws:
            data = json.loads(msg)
            if data.get("chunk"):
                print(data["chunk"], end="", flush=True)
            if data.get("done"):
                break

asyncio.run(chat())
```

---

## Dashboard

Open `http://localhost:8501` after running `./start.sh dashboard`

- **Overview** — uptime, total tasks, tokens, IQ earned
- **Models** — install / delete models by size tier
- **Chat** — interactive chat with any installed model
- **Tasks** — full task log with timing and token counts

---

## Configuration

Edit `config.yaml` to change ports, node name, or model catalog.

```yaml
node:
  name: "my-node"
  port: 8000

ollama:
  port: 11434

dashboard:
  port: 8501
```

---

## IQ Token Simulation

Every completed task earns simulated IQ tokens:

```
IQ = (tokens_in + tokens_out) × 0.001
```

Tracked locally in `data/node.db`. Real on-chain integration is Phase 1.

---

## Architecture (Phase 0)

```
User / Client
     │
     ▼
FastAPI Node  (port 8000)
  ├── REST API  — /infer, /tasks, /models, /stats
  ├── WebSocket — /ws/infer (streaming), /ws/pull (model download)
  └── Task Queue (asyncio)
          │
          ▼
   Ollama Server  (port 11434)
          │
          ▼
   Local LLM Model (tinyllama, mistral, llama3, …)
          │
          ▼
   SQLite  data/node.db
```

---

*IntelliChain — Decentralized Intelligence Protocol. Phase 0 Node.*
