# IntelliChain Node — User Manual
## Phase 1: Testnet Edition

> "Making AI Free for Every Person on Planet Earth"

---

## Table of Contents

1. [What Is IntelliChain?](#1-what-is-intellichain)
2. [What You Just Installed](#2-what-you-just-installed)
3. [Quick Start (5 minutes)](#3-quick-start)
4. [The Dashboard — Full Guide](#4-the-dashboard)
5. [Managing AI Models](#5-managing-ai-models)
6. [Joining the Network](#6-joining-the-network)
7. [Running Queries](#7-running-queries)
8. [Node Tiers & IQ Tokens](#8-node-tiers--iq-tokens)
9. [Reputation System](#9-reputation-system)
10. [Command Reference](#10-command-reference)
11. [Troubleshooting](#11-troubleshooting)
12. [FAQ](#12-faq)

---

## 1. What Is IntelliChain?

IntelliChain is a **decentralized AI network**. Instead of paying OpenAI or Google to run AI, your computer becomes a node in a global mesh of AI-running machines. Every time your node answers a question, it earns **IQ tokens** — a simulated reward that will become real on-chain in Phase 2.

The core idea in one sentence: **Contribute intelligence, earn rewards.**

No company controls it. No account required. No monthly fee. Your hardware, your AI, your earnings.

---

## 2. What You Just Installed

| Component | What It Does |
|---|---|
| **Node Server** | Runs on port 8000. Receives tasks, processes them with AI, returns results |
| **Ollama** | Lightweight AI engine that runs models locally, fully offline |
| **Dashboard** | Web UI on port 8501 — manage everything from a browser |
| **Peer Discovery** | Gossip protocol — your node automatically finds and connects to other nodes |
| **Orchestrator** | Splits big tasks across multiple nodes in the network |
| **Reputation System** | Tracks your node's reliability score (0–1000) |
| **IQ Token Ledger** | Records every token earned from every task completed |
| **SQLite Database** | Stores all tasks, peers, reputation events, and earnings locally |

Everything runs **100% on your machine**. No data leaves unless you explicitly join the network.

---

## 3. Quick Start

### Step 1 — Run the installer (if not done)
**Windows:** Double-click `install.bat`  
**Mac/Linux:** `chmod +x install.sh && ./install.sh`

### Step 2 — Pull a model

The smallest model (TinyLlama) is about 600 MB and runs on any machine:

**Windows:**
```
start.bat model pull tinyllama
```
**Mac/Linux:**
```
./start.sh model pull tinyllama
```

### Step 3 — Start everything

**Windows:**
```
start.bat all
```
**Mac/Linux:**
```
./start.sh all
```

This starts:
- Ollama AI engine (background)
- IntelliChain node server on port 8000
- Dashboard on http://localhost:8501

### Step 4 — Open the dashboard

Your browser should open automatically. If not, go to:
```
http://localhost:8501
```

### Step 5 — Ask your first question

In the dashboard, go to **💬 Chat**, select `tinyllama`, and type anything.

Or from the terminal:
```
start.bat ask "What is artificial intelligence?"
```

---

## 4. The Dashboard

The dashboard has 7 sections accessible from the left sidebar:

### 🏠 Overview
Your node's live stats at a glance:
- **Tasks Completed** — total inference jobs processed
- **Tokens Processed** — total AI tokens generated
- **IQ Earned** — your simulated token balance
- **Reputation** — your reliability score (0–1000)
- **Peers Online** — how many other nodes you're connected to
- **Tier Progress** — how close you are to your next node tier
- **IQ Gauge** — visual meter of your earnings

### 🌐 Network
Connect to and manage peers:
- **Connect to Peer** — enter another node's URL to join their network segment
- **Network Map** — visual graph of your connected peers
- **Peer List** — all known peers with status, tier, and IQ earnings
- **Your Node Info** — your URL and ID to share with others

### 🤖 Models
Download and manage AI models:
- Browse by size (Tiny → Large)
- One-click download
- Remove models you no longer need
- Pull any model by name

### 💬 Chat
Talk to your local AI:
- Select any installed model
- Toggle **"Use network"** to distribute the task across peers
- Full chat history in session
- Shows routing info, token count, and response time

### 📋 Tasks
Full log of every task processed:
- Filter by status (done/error/running/pending)
- See where each task was routed (local/peer/split)
- Token counts and duration for every task

### 🏆 Leaderboard
All known nodes ranked by IQ earned:
- Your position highlighted at the top
- Bar chart showing IQ distribution across peers
- Updated whenever peers report in

### ⚙️ Settings
Node configuration info:
- Your Node ID and URL
- Network heartbeat settings
- How to edit config.yaml for permanent changes

---

## 5. Managing AI Models

Models are downloaded once and stored on your machine. They run fully offline.

### Model Size Guide

| Size | Model | Disk Space | Speed | Quality | Recommended For |
|---|---|---|---|---|---|
| Tiny | tinyllama | ~600 MB | Very Fast | Basic | Testing, low-RAM machines |
| Tiny | qwen2:0.5b | ~350 MB | Fastest | Basic | Raspberry Pi, phones |
| Tiny | phi3:mini | ~2.3 GB | Fast | Good | General use |
| Small | llama3.2:3b | ~2 GB | Fast | Good | Daily tasks |
| Medium | mistral | ~4.1 GB | Medium | Great | Complex tasks |
| Medium | llama3.1:8b | ~4.7 GB | Medium | Great | Best quality/speed |
| Large | llama3.1:70b | ~40 GB | Slow | Excellent | Maximum quality |

### Commands

```bash
# List installed models
start.bat model list

# Browse all available models
start.bat model catalog

# Download a model
start.bat model pull tinyllama
start.bat model pull mistral
start.bat model pull llama3.1:8b

# Remove a model
start.bat model delete tinyllama
```

### Tips
- Start with **tinyllama** to test everything works, then upgrade
- **phi3:mini** is the best tiny model for general use
- **mistral** is the sweet spot for quality vs. speed on most laptops
- You can have multiple models installed and switch between them in chat

---

## 6. Joining the Network

This is what makes IntelliChain different from just running Ollama alone.

### How Peer Discovery Works

1. Your node broadcasts a "hello" message to known peers
2. Each peer responds with their peer list
3. You connect to new peers from that list
4. The process repeats — the network grows automatically

This is called a **gossip protocol**, the same technique used by BitTorrent and many blockchains.

### Connecting to Your First Peer

#### Option A — Dashboard
1. Open the dashboard → **🌐 Network**
2. Paste a peer URL in the text box: `http://192.168.1.100:8000`
3. Click **Connect**

#### Option B — Terminal
```bash
start.bat network connect http://192.168.1.100:8000
```

#### Option C — Bootstrap peers (permanent)
Edit `config.yaml` and add peers to the `bootstrap_peers` list:
```yaml
network:
  bootstrap_peers:
    - "http://friend-pc.local:8000"
    - "http://203.0.113.10:8000"
```
These peers are connected automatically every time the node starts.

### Sharing Your Node URL

For others to connect to **you**, they need your IP and port:
- **Local network:** `http://YOUR-LOCAL-IP:8000` (find your IP with `ipconfig` on Windows)
- **Over the internet:** You'll need to forward port 8000 on your router

### Network Commands

```bash
# See all peers
start.bat network status

# Connect to a peer
start.bat network connect http://192.168.1.5:8000

# List peers
start.bat network peers
```

### Distributed Task Routing

Once you have peers connected, you can split tasks across the network:

```bash
# Route this task to the best available peer
start.bat ask "Summarize quantum computing" --network
```

Or in chat, check the **"Use network"** checkbox.

When the network is used:
- Your orchestrator finds the best available peers
- The prompt is split into sub-tasks
- Each peer processes their part
- Results are merged into one coherent response

---

## 7. Running Queries

### From the Dashboard
Go to **💬 Chat** and type your message.

### From the Terminal

```bash
# Basic query (runs locally)
start.bat ask "Explain blockchain in simple terms"

# Specify a model
start.bat ask "Write a Python function to sort a list" --model mistral

# Route via peer network
start.bat ask "Tell me a story" --network
```

### Via the API (for developers)

Your node exposes a REST API at `http://localhost:8000`.

**Submit a task:**
```bash
curl -X POST http://localhost:8000/infer \
  -H "Content-Type: application/json" \
  -d '{"prompt": "Hello world", "model": "tinyllama"}'
```
Returns: `{"task_id": "abc123...", "status": "queued"}`

**Check result:**
```bash
curl http://localhost:8000/tasks/abc123...
```

**Streaming via WebSocket:**
```python
import asyncio, websockets, json

async def stream():
    async with websockets.connect("ws://localhost:8000/ws/infer") as ws:
        await ws.send(json.dumps({"prompt": "Tell me a joke", "model": "tinyllama"}))
        async for msg in ws:
            data = json.loads(msg)
            if data.get("chunk"):
                print(data["chunk"], end="", flush=True)
            if data.get("done"):
                break

asyncio.run(stream())
```

---

## 8. Node Tiers & IQ Tokens

### Node Tiers

Your tier is determined by tasks completed. Higher tiers earn more IQ per task.

| Tier | Tasks Needed | IQ Multiplier | Hardware Target |
|---|---|---|---|
| 🔵 Nano | 0+ | 1x | Raspberry Pi / phone |
| 🟢 Micro | 50+ | 3x | Laptop / old PC |
| 🟡 Standard | 200+ | 8x | Gaming PC with GPU |
| 🟠 Pro | 1,000+ | 20x | Multi-GPU workstation |
| 🔴 Enterprise | 5,000+ | 50x | Server rack |

### IQ Token Formula

```
IQ = (tokens_in + tokens_out) × 0.001 × tier_multiplier
```

Example: A Micro node processes a task using 500 tokens total:
```
IQ = 500 × 0.001 × 3 = 1.5 IQ
```

### IQ Token Uses (Phase 1 — Simulated)

| Use | Description |
|---|---|
| Earn | Complete inference tasks |
| Spend | Query the network (coming in Phase 2) |
| Stake | Priority task routing (coming in Phase 2) |
| Governance | Vote on protocol changes (Phase 3) |

Your IQ balance is stored in `data/node.db`. In Phase 2, this will be migrated to an on-chain wallet.

---

## 9. Reputation System

Every node has a **reputation score** from 0 to 1000. You start at 100.

### How Reputation Changes

| Event | Change |
|---|---|
| Task completed successfully | +2 |
| Task failed or errored | -5 |
| Peer validates your output | +1 |
| Response time too slow | -1 |
| Node goes offline unexpectedly | -3 |

### Why Reputation Matters

- High reputation = priority task routing from other nodes
- Low reputation = fewer tasks, lower earnings
- Reputation below 50 = node flagged as unreliable (future)
- Reputation of 1000 = maximum trust, enterprise-level routing

### Viewing Your Reputation

```bash
start.bat status
```
Or check the **🏠 Overview** page in the dashboard.

---

## 10. Command Reference

### Windows (`start.bat`)

```
start.bat node              Start the node server
start.bat dashboard         Open the dashboard
start.bat all               Start node + dashboard together
start.bat status            Show node status

start.bat model list        List installed models
start.bat model catalog     Browse available models
start.bat model pull NAME   Download a model
start.bat model delete NAME Remove a model

start.bat network status    Show network info
start.bat network connect URL   Connect to a peer
start.bat network peers     List all peers

start.bat ask "PROMPT"          Local inference
start.bat ask "PROMPT" --network Network inference
start.bat leaderboard       Show IQ leaderboard
```

### Mac/Linux (`./start.sh`)

Same commands, just replace `start.bat` with `./start.sh`.

### API Endpoints

| Endpoint | Method | Description |
|---|---|---|
| `/health` | GET | Node health check |
| `/stats` | GET | Full node statistics |
| `/infer` | POST | Submit inference task |
| `/tasks` | GET | List recent tasks |
| `/tasks/{id}` | GET | Get task status/result |
| `/models` | GET | List local models + catalog |
| `/models/pull` | POST | Download a model |
| `/models/{name}` | DELETE | Remove a model |
| `/network/status` | GET | Network and peer info |
| `/network/announce` | POST | Peer announcement (internal) |
| `/network/peers` | GET | Get peer list (gossip) |
| `/network/connect` | POST | Connect to a peer URL |
| `/reputation` | GET | Reputation summary |
| `/leaderboard` | GET | IQ leaderboard |
| `/ws/infer` | WS | Streaming inference |
| `/ws/pull` | WS | Model download progress |

---

## 11. Troubleshooting

### Node won't start
- Make sure you ran `install.bat` first
- Make sure Ollama is installed (the installer should have done this)
- Check if port 8000 is already in use — change it in `config.yaml`

### "Ollama not running" error
Run manually: open a new terminal and type `ollama serve`

### Dependencies failed to install
Your Python version may be very new. Try installing Python 3.12:
- Windows: https://www.python.org/downloads/release/python-3126/
- Delete the `.venv` folder and run `install.bat` again

### Dashboard won't load
- Make sure the node is running first (`start.bat node`)
- Open http://localhost:8501 manually in your browser
- Check your firewall isn't blocking port 8501

### Can't connect to peers
- Make sure both nodes have port 8000 accessible
- On a local network, check your firewall allows port 8000
- Over the internet, you need to forward port 8000 on your router
- Check the peer URL format: `http://IP:8000` (include `http://`)

### No models showing in Chat
- Pull a model first: `start.bat model pull tinyllama`
- Wait for the download to complete, then refresh the dashboard

### Chat is very slow
- Use a smaller model (tinyllama is the fastest)
- Make sure your GPU drivers are up to date — Ollama uses GPU automatically if available

---

## 12. FAQ

**Q: Do I need to leave my computer on 24/7?**  
A: No. The node only earns IQ when it's running. Start it when you want to contribute.

**Q: Can my node get hacked?**  
A: The node only listens on localhost by default. To expose it to the internet, you need to change `host` in config.yaml. Only do this if you understand port forwarding.

**Q: Will this slow down my computer?**  
A: Ollama only uses resources when processing a task. When idle, it uses almost nothing.

**Q: Are the IQ tokens real money?**  
A: Not yet. Phase 1 is a simulation/leaderboard. Phase 2 will introduce real on-chain tokens.

**Q: Can I run multiple nodes?**  
A: Yes — on different machines. Use different ports (change `port` in config.yaml) if running on the same machine.

**Q: What data does the node send to peers?**  
A: Only: your Node ID, URL, name, tier, and list of installed models. Task content stays local by default.

**Q: How do I update the node?**  
A: Download the new zip, extract it over the existing folder (your `data/` folder with your IQ balance is preserved), and re-run `install.bat`.

**Q: How do I back up my IQ earnings?**  
A: Copy the `data/` folder. Your IQ balance is in `data/node.db`.

**Q: What is the maximum IQ I can earn?**  
A: There's no cap. The more tasks your node processes, the more IQ it earns.

**Q: Can I contribute without a GPU?**  
A: Absolutely. The Nano and Micro tiers are designed for CPU-only machines. Tiny models like `qwen2:0.5b` run fine on any modern laptop.

---

*IntelliChain Protocol — Phase 1 Testnet*  
*"Making AI Free for Every Person on Planet Earth"*
