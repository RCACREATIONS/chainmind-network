# ChainMind Network

> **Decentralized AI infrastructure — run a node, earn IQ.**

ChainMind is a peer-to-peer intelligence protocol where anyone can contribute compute, run local AI models, and earn rewards. Every node is fully self-contained: no cloud dependency, no API keys, no data leaving your machine.

---

## How it works

Your machine runs a local LLM through [Ollama](https://ollama.com). ChainMind wraps it with a lightweight node server that handles task queuing, streaming inference, and on-device reward tracking. When real on-chain integration ships, your accumulated IQ balance carries over automatically.

```
Client Request
      │
      ▼
 ChainMind Node  (port 8000)
  ├── REST API   — task queue, model management, stats
  ├── WebSocket  — streaming token-by-token inference
  └── Task Queue
          │
          ▼
   Ollama  (port 11434)
          │
          ▼
   Local LLM  (tinyllama · mistral · llama3 · …)
          │
          ▼
   SQLite  data/node.db
```

---

## Requirements

| Requirement | Detail |
|---|---|
| Python | 3.10 or higher |
| Disk space | 350 MB minimum (qwen2:0.5b) |
| Internet | Only needed once, for the initial model pull |
| OS | Linux, macOS, Windows |

---

## Install

**Linux / macOS**
```bash
chmod +x install.sh && ./install.sh
```

**Windows**
```
install.bat
```

The installer creates a virtual environment, installs dependencies, and sets up Ollama if it isn't already present.

---

## Quick start

```bash
# Pull a model (choose any from the catalog below)
./start.sh model pull tinyllama

# Start the node
./start.sh node

# Open the dashboard (separate terminal)
./start.sh dashboard

# Or launch everything at once
./start.sh all
```

---

## Model catalog

```bash
./start.sh model catalog   # browse all options
./start.sh model list      # show what's installed
```

| Tier | Model | Size |
|---|---|---|
| Tiny | qwen2:0.5b | ~350 MB |
| Tiny | tinyllama | ~600 MB |
| Compact | phi3:mini | ~2.3 GB |
| Small | llama3.2:3b | ~2.0 GB |
| Medium | mistral | ~4.1 GB |
| Medium | llama3.1:8b | ~4.7 GB |
| Large | llama3.1:70b | ~40 GB |

---

## Usage

```bash
# Ask a question directly from the terminal
./start.sh ask "Summarize the key ideas behind proof-of-work"
./start.sh ask "Write a Python function to reverse a linked list" --model mistral

# Check node health
./start.sh status
```

### REST API

```bash
# Health check
curl http://localhost:8000/health

# Submit an inference task
curl -X POST http://localhost:8000/infer \
  -H "Content-Type: application/json" \
  -d '{"prompt": "Explain tokenomics in one paragraph", "model": "tinyllama"}'

# Poll for result
curl http://localhost:8000/tasks/<task_id>

# List installed models
curl http://localhost:8000/models

# Pull a new model
curl -X POST http://localhost:8000/models/pull \
  -H "Content-Type: application/json" \
  -d '{"model": "mistral"}'

# Node stats
curl http://localhost:8000/stats
```

### WebSocket streaming

```python
import asyncio, websockets, json

async def stream():
    async with websockets.connect("ws://localhost:8000/ws/infer") as ws:
        await ws.send(json.dumps({"prompt": "What is a blockchain?", "model": "tinyllama"}))
        async for msg in ws:
            data = json.loads(msg)
            if data.get("chunk"):
                print(data["chunk"], end="", flush=True)
            if data.get("done"):
                break

asyncio.run(stream())
```

---

## Dashboard

Visit `http://localhost:8501` after running `./start.sh dashboard`.

| Tab | What you'll find |
|---|---|
| Overview | Uptime, total tasks completed, tokens processed, IQ earned |
| Models | Install or remove models by size tier |
| Chat | Live chat with any installed model |
| Tasks | Full task log with timing and token counts |

---

## Configuration

All settings live in `config.yaml`.

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

## IQ rewards

Every completed inference task earns simulated IQ tokens, tracked locally:

```
IQ = (tokens_in + tokens_out) × 0.001
```

Stored in `data/node.db`. Phase 1 will connect this to the live chain — your balance carries over.

---

## Project structure

| Path | Role |
|---|---|
| `node/server.py` | FastAPI node — REST and WebSocket endpoints |
| `node/ollama_client.py` | Async wrapper around Ollama's local API |
| `node/tasks.py` | Async task queue and inference processor |
| `node/dashboard.py` | Streamlit dashboard |
| `node/cli.py` | CLI — pull models, query, check status |
| `node/db.py` | SQLite — tasks, stats, IQ ledger |
| `config.yaml` | Ports, node name, model catalog |

---

## Roadmap

- **Phase 0** ✅ — Local node, offline inference, IQ simulation, dashboard
- **Phase 1** — On-chain IQ integration, node registry, peer discovery
- **Phase 2** — Multi-node task routing, reputation system, token economy

---

## Contributing

Issues and pull requests are welcome. Please open an issue before starting significant work so we can discuss direction.

---

*ChainMind — Decentralized Intelligence Protocol*
