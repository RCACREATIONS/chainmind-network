# ChainMind Network Node

Decentralized AI inference node. Community-owned compute network — cheap inference for users, passive income for node operators.

## Stack

- **Backend**: FastAPI + uvicorn (port 8000)
- **Dashboard**: Streamlit (port 5000, shown in preview)
- **Database**: SQLite (`data/node.db`)
- **Inference**: Ollama (external, port 11434 — not available on Replit)

## How to run

The workflow `Start application` runs `python start_replit.py`, which starts both services:

1. FastAPI node server on `localhost:8000`
2. Streamlit dashboard on `0.0.0.0:5000` (visible in the Replit preview)

## Key files

| File | Role |
|---|---|
| `start_replit.py` | Replit entrypoint — starts both FastAPI and Streamlit |
| `node/server.py` | FastAPI REST + WebSocket endpoints |
| `node/dashboard.py` | Streamlit dashboard UI |
| `node/ollama_client.py` | Async Ollama wrapper |
| `node/tasks.py` | Async task queue and inference processor |
| `node/db.py` | SQLite layer |
| `config.yaml` | Ports, node name, model catalog, network config |

## Replit limitations

- **Ollama is not available** on Replit — the dashboard will show "Node is offline" and inference jobs will fail. All other UI and API functionality works normally.
- To run with real inference, deploy on a machine with Ollama installed and a supported GPU/CPU.

## User preferences

- Keep existing project structure — do not restructure or migrate.
