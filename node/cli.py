"""ChainMind Network CLI."""

from __future__ import annotations

import subprocess
import sys
import time
from pathlib import Path
from typing import Optional

import httpx
import typer
import yaml
from rich import print as rprint
from rich.console import Console
from rich.panel import Panel
from rich.progress import Progress, SpinnerColumn, TextColumn, BarColumn
from rich.table import Table

app = typer.Typer(name="chainmind", help="ChainMind Network Node CLI", no_args_is_help=True)
console = Console()

_cfg_path = Path(__file__).parent.parent / "config.yaml"
with open(_cfg_path) as f:
    CFG = yaml.safe_load(f)

NODE_URL = f"http://localhost:{CFG['node']['port']}"
CATALOG: dict = CFG.get("models", {})

node_app    = typer.Typer(help="Manage the node server")
model_app   = typer.Typer(help="Manage AI models")
network_app = typer.Typer(help="Manage peer network")
app.add_typer(node_app,    name="node")
app.add_typer(model_app,   name="model")
app.add_typer(network_app, name="network")

# ── Helpers ───────────────────────────────────────────────────────────────────
def _get(path: str):
    try:
        return httpx.get(f"{NODE_URL}{path}", timeout=5).json()
    except Exception:
        return None

def _post(path: str, payload: dict):
    try:
        return httpx.post(f"{NODE_URL}{path}", json=payload, timeout=10).json()
    except Exception:
        return None

def _delete(path: str):
    try:
        return httpx.delete(f"{NODE_URL}{path}", timeout=5).json()
    except Exception:
        return None

def _require_online():
    h = _get("/health")
    if not h or h.get("status") != "ok":
        console.print("[red]Node is offline. Run: start.bat node[/red]")
        raise typer.Exit(1)

def _find_ollama() -> Optional[str]:
    """Find ollama — system PATH first (installed via OllamaSetup.exe)."""
    import shutil
    sys_ollama = shutil.which("ollama")
    if sys_ollama:
        return sys_ollama
    # Legacy fallback: tools/ folder from old install
    tools_dir = Path(__file__).parent.parent / "tools"
    for name in ("ollama.exe", "ollama"):
        candidate = tools_dir / name
        if candidate.exists():
            return str(candidate)
    return None

# ── Node commands ─────────────────────────────────────────────────────────────
@node_app.command("start")
def node_start():
    """Start the ChainMind node server (auto-installs/starts Ollama + pulls recommended model)."""
    console.print(Panel("[bold]Starting ChainMind Network Node…[/bold]", style="purple", expand=False))

    # ── Ollama bootstrap: install → start → pull recommended model ────────────
    try:
        from node.ollama_bootstrap import ensure_ollama_ready
        with console.status("[cyan]Checking Ollama AI engine…[/cyan]"):
            result = ensure_ollama_ready(catalog=CATALOG, verbose=False)

        if result.get("skipped"):
            console.print(
                "[yellow]⚠ Ollama not found.[/yellow] "
                "Install from [link=https://ollama.ai/download]https://ollama.ai/download[/link]"
            )
        elif result.get("running"):
            pulled = result.get("model_pulled")
            models = result.get("models", [])
            if pulled:
                console.print(f"[green]✅ Ollama ready · Model pulled: {pulled}[/green]")
            elif models:
                console.print(f"[green]✅ Ollama ready · Models: {', '.join(models[:3])}[/green]")
            else:
                console.print("[green]✅ Ollama running.[/green]")
        else:
            console.print("[yellow]⚠ Ollama installed but could not start.[/yellow]")
    except Exception as exc:
        console.print(f"[yellow]Ollama bootstrap warning: {exc}[/yellow]")

    import uvicorn
    from node.server import app as fastapi_app
    uvicorn.run(fastapi_app, host=CFG["node"]["host"], port=CFG["node"]["port"], log_level="warning")


@node_app.command("status")
def node_status():
    """Show node health, reputation and stats."""
    _require_online()
    stats  = _get("/stats") or {}
    health = _get("/health") or {}
    rep    = stats.get("reputation") or {}

    table = Table(title="ChainMind Node Status", show_header=False, border_style="purple")
    table.add_column("Key",   style="purple", width=20)
    table.add_column("Value")
    table.add_row("Node",         stats.get("node_name", "?"))
    table.add_row("Node ID",      (stats.get("node_id") or "")[:24] + "…")
    table.add_row("Ollama",       "✅ running" if health.get("ollama") else "❌ stopped")
    table.add_row("Tier",         rep.get("tier_label", "Nano"))
    table.add_row("IQ Earned",    f"{rep.get('iq_earned', 0):.6f}")
    table.add_row("Reputation",   f"{rep.get('reputation_score', 100):.1f}/1000")
    table.add_row("Tasks Done",   str(rep.get("tasks_done", 0)))
    table.add_row("Peers Online", str(stats.get("peers_online", 0)))
    table.add_row("Uptime",       rep.get("uptime", "0h 0m"))
    console.print(table)


# ── Model commands ────────────────────────────────────────────────────────────
@model_app.command("list")
def model_list():
    """List installed models."""
    _require_online()
    data  = _get("/models") or {}
    local = data.get("local", [])
    if not local:
        console.print("[yellow]No models installed. Use: model pull <name>[/yellow]")
        return
    table = Table(title="Installed Models")
    table.add_column("Name",  style="purple")
    table.add_column("Size",  justify="right")
    for m in local:
        size_gb = m.get("size", 0) / 1e9
        table.add_row(m["name"], f"{size_gb:.2f} GB")
    console.print(table)


@model_app.command("catalog")
def model_catalog():
    """Browse all available models by size."""
    for group, models in CATALOG.items():
        console.print(f"\n[bold]{group.upper()}[/bold]")
        for m in models:
            console.print(f"  [purple]{m['name']:35}[/purple] {m['label']}")


@model_app.command("pull")
def model_pull(model_name: str = typer.Argument(..., help="Model name, e.g. tinyllama")):
    """Download a model via Ollama (works with or without the node running)."""
    node_online = _get("/health") is not None

    if node_online:
        import websockets.sync.client  # type: ignore
        ws_url = f"ws://localhost:{CFG['node']['port']}/ws/pull?model={model_name}"
        console.print(f"[purple]Pulling [bold]{model_name}[/bold] via node…[/purple]")
        try:
            with websockets.sync.client.connect(ws_url, open_timeout=10) as ws:
                with Progress(SpinnerColumn(), TextColumn("{task.description}"), BarColumn(),
                              console=console, transient=True) as prog:
                    task = prog.add_task("Connecting…", total=100)
                    for raw in ws:
                        event     = yaml.safe_load(raw)
                        status    = event.get("status", "")
                        completed = event.get("completed", 0)
                        total     = event.get("total", 0)
                        if total:
                            prog.update(task, completed=int(completed / total * 100))
                        prog.update(task, description=status)
                        if status == "success":
                            break
            console.print(f"[green]✓ {model_name} ready[/green]")
            return
        except Exception:
            console.print("[yellow]Node WebSocket unavailable — falling back to direct Ollama pull…[/yellow]")

    # Node offline — call Ollama directly
    ollama_exe = _find_ollama()
    if not ollama_exe:
        console.print(
            "[red]Ollama not found.[/red]\n"
            "Re-run install.bat — it will download and install Ollama properly.\n"
            "Or install manually from https://ollama.ai/download"
        )
        raise typer.Exit(1)

    console.print(f"[purple]Pulling [bold]{model_name}[/bold] via Ollama…[/purple]")
    try:
        result = subprocess.run([ollama_exe, "pull", model_name])
        if result.returncode == 0:
            console.print(f"[green]✓ {model_name} ready[/green]")
        else:
            console.print(f"[red]Pull failed (exit {result.returncode})[/red]")
            raise typer.Exit(1)
    except OSError as e:
        console.print(
            f"[red]Cannot launch Ollama:[/red] {e}\n\n"
            "[yellow]Fix:[/yellow] Delete the [bold]tools\\[/bold] folder and re-run install.bat.\n"
            "install.bat will download the full Ollama installer (OllamaSetup.exe) automatically."
        )
        raise typer.Exit(1)


@model_app.command("delete")
def model_delete(model_name: str):
    """Remove a local model."""
    _require_online()
    r = httpx.delete(f"{NODE_URL}/models/{model_name}", timeout=10)
    if r.status_code == 200:
        console.print(f"[green]✓ Deleted {model_name}[/green]")
    else:
        console.print(f"[red]Failed: {r.text}[/red]")


# ── Network commands ──────────────────────────────────────────────────────────
@network_app.command("status")
def network_status():
    """Show peer network status."""
    _require_online()
    net   = _get("/network/status") or {}
    peers = net.get("peers", [])

    console.print(Panel(
        f"[purple]Node:[/purple] {net.get('node_name','?')}\n"
        f"[purple]ID:[/purple]   {(net.get('node_id') or '')[:32]}…\n"
        f"[purple]URL:[/purple]  {net.get('self_url','?')}\n"
        f"Total peers: {net.get('total_peers',0)} | Online: {net.get('online_peers',0)}",
        title="Network Status", border_style="purple"
    ))

    if peers:
        table = Table(title="Known Peers")
        table.add_column("Name / ID", style="purple")
        table.add_column("URL")
        table.add_column("Tier")
        table.add_column("Status")
        table.add_column("Rep")
        for p in peers:
            name   = p.get("name") or p["id"][:12] + "…"
            status = p.get("status", "unknown")
            dot    = {"online": "🟢", "offline": "🔴", "degraded": "🟡"}.get(status, "⚪")
            table.add_row(name, p["url"], p.get("tier","?"),
                          f"{dot} {status}", f"{p.get('reputation',100):.0f}")
        console.print(table)
    else:
        console.print("[yellow]No peers yet. Use: network connect <url>[/yellow]")


@network_app.command("connect")
def network_connect(url: str = typer.Argument(..., help="Peer URL, e.g. http://192.168.1.100:8000")):
    """Connect to a peer node."""
    _require_online()
    with console.status(f"Connecting to {url}…"):
        result = _post("/network/connect", {"url": url})
    if result and "error" not in result:
        console.print(f"[green]✓ Connected to {result.get('name', url)}[/green]")
    else:
        console.print(f"[red]Failed: {result}[/red]")


@network_app.command("peers")
def network_peers():
    """List all known peers."""
    network_status()


@network_app.command("remove")
def network_remove(peer_id: str = typer.Argument(..., help="Peer ID to remove")):
    """Remove a peer from the network."""
    _require_online()
    _delete(f"/network/peers/{peer_id}")
    console.print(f"[green]✓ Removed {peer_id}[/green]")


# ── Leaderboard ───────────────────────────────────────────────────────────────
@app.command("leaderboard")
def leaderboard():
    """Show the IQ token leaderboard."""
    _require_online()
    data  = _get("/leaderboard") or {}
    board = data.get("leaderboard", [])
    local = data.get("local_node") or {}

    console.print(Panel(
        f"Your IQ: [bold yellow]{local.get('iq_earned',0):.6f}[/bold yellow] | "
        f"Tier: [bold purple]{local.get('tier_label','Nano')}[/bold purple] | "
        f"Reputation: [bold]{local.get('reputation_score',100):.0f}/1000[/bold]",
        title="🏆 Leaderboard", border_style="purple"
    ))

    table = Table()
    table.add_column("#",     width=3)
    table.add_column("Name / ID", style="purple")
    table.add_column("Tier")
    table.add_column("IQ Earned",  justify="right", style="yellow")
    table.add_column("Tasks",      justify="right")
    table.add_column("Rep",        justify="right")
    table.add_column("Status")
    for i, p in enumerate(board[:20], 1):
        name = p.get("name") or p["id"][:12] + "…"
        dot  = {"online": "🟢", "offline": "🔴"}.get(p.get("status",""), "⚪")
        table.add_row(str(i), name, p.get("tier","?"),
                      f"{p.get('iq_earned',0):.6f}", str(p.get("tasks_done",0)),
                      f"{p.get('reputation',100):.0f}", f"{dot} {p.get('status','?')}")
    console.print(table)


# ── Ask ───────────────────────────────────────────────────────────────────────
@app.command("ask")
def ask(
    prompt:  str           = typer.Argument(..., help="Prompt to send"),
    model:   Optional[str] = typer.Option(None, "--model", "-m"),
    network: bool          = typer.Option(False, "--network", "-n", help="Route via peer network"),
):
    """Send a one-shot inference request."""
    _require_online()
    payload: dict = {"prompt": prompt, "use_network": network}
    if model:
        payload["model"] = model

    resp = _post("/infer", payload)
    if not resp:
        console.print("[red]Node error[/red]")
        raise typer.Exit(1)

    task_id = resp["task_id"]
    t: dict = {}
    with console.status("Waiting for response…"):
        for _ in range(300):
            time.sleep(1)
            t = _get(f"/tasks/{task_id}") or {}
            if t.get("status") in ("done", "error"):
                break

    result = t.get("result") or t.get("status", "error")
    routed = t.get("routed_to", "local")
    tok    = (t.get("tokens_in",0) or 0) + (t.get("tokens_out",0) or 0)
    dur    = (t.get("duration_ms",0) or 0) / 1000

    console.print(Panel(result, title="Response", border_style="purple"))
    console.print(f"[dim]Routed: {routed} · {tok} tokens · {dur:.1f}s[/dim]")


# ── Dashboard ─────────────────────────────────────────────────────────────────
@app.command("dashboard")
def dashboard():
    """Launch the ChainMind dashboard."""
    dash_path = Path(__file__).parent / "dashboard.py"
    console.print("[purple]Opening ChainMind dashboard on http://localhost:8501[/purple]")
    subprocess.run([sys.executable, "-m", "streamlit", "run", str(dash_path),
                    "--server.headless", "true"])


if __name__ == "__main__":
    app()
