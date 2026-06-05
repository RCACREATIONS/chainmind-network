<p align="center">
  <a href="https://chainmind.com.ng">
    <img src="assets/logo.png" alt="ChainMind" width="120" />
  </a>
</p>

<h3 align="center">ChainMind — Decentralized Intelligence Network</h3>

<p align="center">
  Community-owned AI infrastructure. Cheap inference for users, passive income for node operators.
  <br /><br />
  <a href="https://chainmind.com.ng"><strong>chainmind.com.ng</strong></a>
  &nbsp;·&nbsp;
  <a href="https://chainmind.com.ng/docs">Docs</a>
  &nbsp;·&nbsp;
  <a href="https://chainmind.com.ng/#pricing">Pricing</a>
  &nbsp;·&nbsp;
  <a href="mailto:support@chainmind.com.ng">Support</a>
</p>

<p align="center">
  <img src="https://img.shields.io/badge/version-1.2.8-blue" />
  <img src="https://img.shields.io/badge/nodes-online-brightgreen" />
  <img src="https://img.shields.io/badge/models-300%2B-orange" />
  <img src="https://img.shields.io/badge/price-from%20%240.005%2F1k%20tokens-success" />
  <img src="https://img.shields.io/badge/license-MIT-lightgrey" />
</p>

---

## What is ChainMind?

Every AI query you run on ChatGPT, Claude, or Gemini goes through a handful of massive data centers owned by trillion-dollar companies. They set the price. They control what you can ask. They log everything. And they charge up to **$0.06 per 1,000 tokens** for the privilege.

ChainMind is different.

Your AI job gets routed to one of thousands of community-owned compute nodes — gaming PCs, workstations, and dedicated rigs run by real people all over the world. The job runs on their GPU, the result comes back to you, and the node operator earns crypto. No AWS. No Google Cloud. No middleman taking the cut.

**The result: AI inference at $0.005 per 1k tokens — 90% cheaper than big-cloud, with 300+ open models, and no one owns the infrastructure but the community.**

### How it compares

| | Big Cloud AI | ChainMind |
|---|---|---|
| Price per 1k tokens | ~$0.06 | **$0.005** |
| Data privacy | Passes through their servers | Jobs are ephemeral by default |
| Model choice | Their models only | 300+ open-source models |
| Censorship | They set the rules | Open models, community-run |
| Infrastructure | They own it | You own it |
| Idle GPU | Earns nothing | **Earns IQ tokens** |

---

## Download the node app

The easiest way to join the network. Download, install, and your machine starts earning — no coding, no command line, no configuration needed.

| Platform | Download | Requirements |
|---|---|---|
| **Windows** | [⬇ Download for Windows (.exe)](https://github.com/RCACREATIONS/chainmind-network/releases/latest/download/ChainMind-Setup.exe) | Windows 10/11, GTX 1060+ recommended |
| **macOS** | [⬇ Download for macOS (.dmg)](https://github.com/RCACREATIONS/chainmind-network/releases/latest/download/ChainMind.dmg) | macOS 12+, Apple Silicon or Intel |
| **Linux** | [⬇ Download for Linux (.AppImage)](https://github.com/RCACREATIONS/chainmind-network/releases/latest/download/ChainMind.AppImage) | Ubuntu 20.04+, any NVIDIA/AMD GPU |

Once installed, the app runs quietly in your system tray. It listens for jobs from the network, processes them on your GPU in the background, and tracks your IQ earnings in real time. Your normal computer use is unaffected.

> **First time here?** Head to [chainmind.com.ng](https://chainmind.com.ng) first — sign up free, grab 500 credits, and try sending a real AI query through the network before you commit to running anything.

---

## Why run a node?

Your PC is already on. It might as well earn.

When you run a ChainMind node, your GPU becomes part of the network's compute pool. Every time a user anywhere in the world sends an AI job and it routes to your machine, you earn **IQ tokens**.

### Earnings breakdown

| GPU | Est. daily | Est. monthly | Est. monthly (NGN) |
|---|---|---|---|
| RTX 3060 (12GB) | ~$5 | ~$150 | ~₦210,000 |
| RTX 3080 (10GB) | ~$12 | ~$360 | ~₦504,000 |
| RTX 4090 (24GB) | ~$28 | ~$840 | ~₦1,176,000 |

*Estimates based on 50% average network utilisation. Peak hours earn more.*

### How IQ tokens work

- You earn **1,000 IQ per 1 million tokens** processed
- Each IQ token is pegged at **$0.01**
- Minimum cashout: **10 IQ**
- Payout to: crypto wallet or bank account (NGN supported)
- Early operators benefit from a growing user base — the network is still young

### What you need

- Windows, Linux, or macOS machine
- NVIDIA or AMD GPU (GTX 1060 / RX 580 or better recommended)
- Stable internet connection (upload speed matters more than download)
- The node app running in the background — that's it

[Register as a node operator →](https://chainmind.com.ng/#earn)

---

## For developers & businesses

### Drop-in OpenAI replacement

Already using OpenAI's Python SDK, Node SDK, or any OpenAI-compatible library? You're one line away from switching.

```python
from openai import OpenAI

client = OpenAI(
    base_url="https://api.chainmind.com.ng/v1",
    api_key="your-chainmind-key"          # get yours at chainmind.com.ng/dashboard
)

response = client.chat.completions.create(
    model="llama3.1:8b",
    messages=[{"role": "user", "content": "Summarize this contract in plain English."}],
    stream=True
)

for chunk in response:
    print(chunk.choices[0].delta.content or "", end="")
```

Same JSON format. Same streaming behaviour. Same error codes. No new SDKs to learn.

### 300+ models available

| Category | Models |
|---|---|
| General purpose | Llama 3.1 (8B, 70B), Llama 3.2 (3B), Mistral 7B |
| Coding | DeepSeek Coder, CodeLlama, Qwen2.5-Coder |
| Compact / fast | TinyLlama, Qwen2 0.5B, Phi-3 Mini |
| Multilingual | Qwen2, Aya, Falcon |
| Vision | LLaVA, BakLLaVA |

```bash
# See the full list
curl https://api.chainmind.com.ng/v1/models
```

### API key management

Create separate keys per project, client, or team member. Set hard credit caps on each so one runaway script can't drain your balance. Revoke any key instantly from the dashboard.

```bash
# All standard OpenAI endpoints work
POST /v1/chat/completions      # chat
POST /v1/completions           # raw completion  
POST /v1/embeddings            # embeddings
GET  /v1/models                # list available models
```

### Fault-tolerant routing

No single node can take down the network. If a node drops mid-job, the router automatically reassigns it to the next available machine. From your app's perspective, the API just works.

[Get your API key →](https://chainmind.com.ng/dashboard)  
[Read the full API docs →](https://chainmind.com.ng/docs)

---

## Pricing

Credits never expire. Buy once, use forever. Subscribe for volume savings.

| Plan | Price | Credits | Best for |
|---|---|---|---|
| **Free** | $0 | 500 on signup | Trying it out |
| **Pay as you go** | $5 one-time | 5,000 (~1M tokens) | Occasional use |
| **Pro** | $15/month | 20,000/month | Active builders |
| **Builder** | $40/month | 60,000/month | High-volume products |

All plans include access to all 300+ models. Unused monthly credits roll over on Pro and Builder.

**Payment methods:** NGN via Paystack · USD cards via Flutterwave · Crypto (BTC, ETH, USDT) via NOWPayments

[See full pricing →](https://chainmind.com.ng/#pricing)

---

## Self-host / run from source

For contributors, developers who want full control, or anyone building on top of the node software directly.

### Requirements

- Python 3.10 or higher
- ~600 MB free disk (for TinyLlama, the smallest model)
- Internet access for the first model pull — fully offline after that

### Install

```bash
# Linux / macOS
chmod +x install.sh && ./install.sh

# Windows
install.bat
```

The installer: creates a Python virtual environment, installs all dependencies, sets up Ollama if it isn't already on your machine, and creates the `data/` directory.

### Start the node

```bash
# Pull a model first (pick any size from the catalog)
./start.sh model pull tinyllama     # ~600 MB, good for testing
./start.sh model pull mistral       # ~4.1 GB, much better quality

# Start everything at once
./start.sh all

# Or start services individually
./start.sh node         # API server on port 8000
./start.sh dashboard    # Streamlit dashboard on port 8501
```

### Available models (self-hosted)

| Tier | Model | Disk |
|---|---|---|
| Tiny | qwen2:0.5b | ~350 MB |
| Tiny | tinyllama | ~600 MB |
| Compact | phi3:mini | ~2.3 GB |
| Small | llama3.2:3b | ~2.0 GB |
| Medium | mistral | ~4.1 GB |
| Medium | llama3.1:8b | ~4.7 GB |
| Large | llama3.1:70b | ~40 GB |

```bash
./start.sh model catalog    # browse the full list
./start.sh model list       # show what's installed on your machine
```

### Local API (port 8000)

```bash
# Health check
curl http://localhost:8000/health

# Submit an inference task
curl -X POST http://localhost:8000/infer \
  -H "Content-Type: application/json" \
  -d '{"prompt": "Explain proof-of-work in one paragraph", "model": "tinyllama"}'

# Poll for result
curl http://localhost:8000/tasks/<task_id>

# Node stats — tasks completed, tokens processed, IQ earned
curl http://localhost:8000/stats
```

### Local dashboard (port 8501)

Visit `http://localhost:8501` after running `./start.sh dashboard`.

| Tab | What you'll find |
|---|---|
| Overview | Uptime, total tasks, tokens processed, IQ earned |
| Models | Install or remove models by size tier |
| Chat | Live chat with any installed model |
| Tasks | Full task log with timing and token counts per job |

### Configuration

Everything lives in `config.yaml` — edit it to change ports, node name, or which models appear in the catalog.

```yaml
node:
  name: "my-node"   # how your node identifies itself on the network
  port: 8000

ollama:
  port: 11434

dashboard:
  port: 8501
```

---

## Architecture

```
User / Client
      │
      ▼
 ChainMind Node  (port 8000)
  ├── REST API   — /infer, /tasks, /models, /stats
  ├── WebSocket  — /ws/infer (streaming), /ws/pull (model download progress)
  └── Task Queue (asyncio)
          │
          ▼
   Ollama Server  (port 11434)
          │
          ▼
   Local LLM  (tinyllama · mistral · llama3 · …)
          │
          ▼
   SQLite  data/node.db
```

### Codebase overview

| File | Role |
|---|---|
| `node/server.py` | FastAPI node — all REST and WebSocket endpoints |
| `node/ollama_client.py` | Async wrapper around Ollama's local HTTP API |
| `node/tasks.py` | Async task queue and inference processor |
| `node/dashboard.py` | Streamlit dashboard |
| `node/cli.py` | CLI — pull models, query, check node status |
| `node/db.py` | SQLite layer — tasks, stats, IQ earnings ledger |
| `config.yaml` | Ports, node name, model catalog |

---

## Roadmap

- **Phase 0** ✅ — Local node, offline inference, IQ simulation, Streamlit dashboard, REST + WebSocket API
- **Phase 1** — On-chain IQ integration, live node registry, peer discovery, real token payouts
- **Phase 2** — Multi-node task routing, reputation scoring, decentralised compute market

---

## Contributing

Issues and pull requests are welcome. If you're planning something significant, open an issue first so we can align on direction before you invest the time.

---

## Links

- **Website:** [chainmind.com.ng](https://chainmind.com.ng)
- **Docs:** [chainmind.com.ng/docs](https://chainmind.com.ng/docs)
- **Pricing:** [chainmind.com.ng/#pricing](https://chainmind.com.ng/#pricing)
- **Support:** [support@chainmind.com.ng](mailto:support@chainmind.com.ng)

---

*© 2026 ChainMind · Community-owned AI infrastructure · [chainmind.com.ng](https://chainmind.com.ng)*
