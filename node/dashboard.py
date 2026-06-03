"""ChainMind Network Dashboard — Modern White + Purple UI."""

from __future__ import annotations

import json
import time
from pathlib import Path

import httpx
import os as _os
import sys as _sys
import pandas as pd
import plotly.graph_objects as go
import streamlit as st
import yaml

if _os.environ.get("CHAINMIND_CONFIG"):
    _cfg_path = Path(_os.environ["CHAINMIND_CONFIG"])
elif getattr(_sys, "frozen", False):
    _cfg_path = Path(_sys.executable).parent / "config.yaml"
else:
    _cfg_path = Path(__file__).parent.parent / "config.yaml"

with open(_cfg_path) as f:
    CFG = yaml.safe_load(f)

NODE_URL = f"http://localhost:{CFG['node']['port']}"

st.set_page_config(
    page_title="ChainMind Network",
    page_icon="🔮",
    layout="wide",
    initial_sidebar_state="expanded",
)

st.markdown("""
<style>
/* ── Base ───────────────────────────────────────────────────────────────── */
html, body, [data-testid="stAppViewContainer"] {
    background: #ffffff;
    color: #1e1b4b;
    font-family: 'Inter', 'Segoe UI', sans-serif;
}
[data-testid="stMain"] { background: #ffffff; }

/* ── Sidebar ────────────────────────────────────────────────────────────── */
[data-testid="stSidebar"] {
    background: linear-gradient(180deg, #f5f3ff 0%, #ede9fe 100%);
    border-right: 1px solid #ddd6fe;
}
[data-testid="stSidebar"] * { color: #1e1b4b !important; }
[data-testid="stSidebar"] .stRadio label { color: #4c1d95 !important; font-weight: 500; }
[data-testid="stSidebar"] hr { border-color: #c4b5fd !important; }

/* ── Metric cards ───────────────────────────────────────────────────────── */
[data-testid="metric-container"] {
    background: #ffffff;
    border: 1px solid #ede9fe;
    border-radius: 14px;
    padding: 18px 20px;
    box-shadow: 0 1px 6px rgba(124,58,237,0.07);
}
[data-testid="metric-container"] [data-testid="stMetricLabel"] { color: #6d28d9 !important; font-size: 13px; font-weight: 600; letter-spacing: .03em; }
[data-testid="metric-container"] [data-testid="stMetricValue"] { color: #1e1b4b !important; font-size: 28px; font-weight: 700; }

/* ── Buttons ────────────────────────────────────────────────────────────── */
.stButton > button {
    background: #7c3aed;
    color: #ffffff;
    border: none;
    border-radius: 8px;
    font-weight: 600;
    padding: 8px 18px;
    transition: background .18s;
}
.stButton > button:hover { background: #6d28d9; }

/* ── Dataframe ──────────────────────────────────────────────────────────── */
[data-testid="stDataFrame"] { border-radius: 10px; overflow: hidden; border: 1px solid #ede9fe; }

/* ── Tabs ───────────────────────────────────────────────────────────────── */
[data-testid="stTab"] button { color: #7c3aed !important; font-weight: 600; }
[data-testid="stTab"] button[aria-selected="true"] { border-bottom: 2px solid #7c3aed !important; }

/* ── Card helper ────────────────────────────────────────────────────────── */
.cm-card {
    background: #ffffff;
    border: 1px solid #ede9fe;
    border-radius: 14px;
    padding: 20px 24px;
    margin: 8px 0;
    box-shadow: 0 2px 8px rgba(124,58,237,0.06);
}
.cm-badge-ok   { background:#d1fae5; color:#065f46; padding:3px 10px; border-radius:20px; font-size:12px; font-weight:600; }
.cm-badge-err  { background:#fee2e2; color:#991b1b; padding:3px 10px; border-radius:20px; font-size:12px; font-weight:600; }
.cm-badge-warn { background:#fef3c7; color:#92400e; padding:3px 10px; border-radius:20px; font-size:12px; font-weight:600; }
.cm-badge-fits { background:#ede9fe; color:#5b21b6; padding:3px 10px; border-radius:20px; font-size:12px; font-weight:600; }
.cm-badge-big  { background:#fee2e2; color:#991b1b; padding:3px 10px; border-radius:20px; font-size:12px; font-weight:600; }
.cm-badge-central { background:#f0fdf4; color:#065f46; padding:3px 10px; border-radius:20px; font-size:12px; font-weight:600; }

/* ── Headings ───────────────────────────────────────────────────────────── */
h1 { color: #1e1b4b !important; font-weight: 800 !important; letter-spacing: -.01em; }
h2, h3 { color: #2e1065 !important; font-weight: 700 !important; }

/* ── Alerts ─────────────────────────────────────────────────────────────── */
[data-testid="stAlert"] { border-radius: 10px; }

/* ── Input fields ───────────────────────────────────────────────────────── */
[data-testid="stTextInput"] input, [data-testid="stTextArea"] textarea {
    border: 1px solid #ddd6fe;
    border-radius: 8px;
    background: #faf5ff;
    color: #1e1b4b;
}
[data-testid="stTextInput"] input:focus, [data-testid="stTextArea"] textarea:focus {
    border-color: #7c3aed;
    box-shadow: 0 0 0 3px rgba(124,58,237,.12);
}

/* ── Progress bar ───────────────────────────────────────────────────────── */
[data-testid="stProgressBar"] > div > div { background: #7c3aed !important; }

/* ── Divider ────────────────────────────────────────────────────────────── */
hr { border-color: #ede9fe !important; }
</style>
""", unsafe_allow_html=True)

TIER_COLORS = {
    "nano":       "#7c3aed",
    "micro":      "#6d28d9",
    "standard":   "#5b21b6",
    "pro":        "#4c1d95",
    "enterprise": "#3b0764",
}
TIER_BG = {
    "nano":       "#f5f3ff",
    "micro":      "#ede9fe",
    "standard":   "#ddd6fe",
    "pro":        "#c4b5fd",
    "enterprise": "#a78bfa",
}

PURPLE   = "#7c3aed"
PURPLE_L = "#8b5cf6"
PURPLE_LL= "#ede9fe"
TEXT     = "#1e1b4b"
BG       = "#ffffff"

def _auth_headers() -> dict:
    """Return Authorization header if api_token is configured."""
    token = CFG.get("node", {}).get("api_token", "")
    return {"Authorization": f"Bearer {token}"} if token else {}

@st.cache_data(ttl=3)
def fetch(path):
    try:
        r = httpx.get(f"{NODE_URL}{path}", headers=_auth_headers(), timeout=5)
        return r.json()
    except Exception:
        return None

def post(path, payload):
    try:
        return httpx.post(f"{NODE_URL}{path}", json=payload, headers=_auth_headers(), timeout=10).json()
    except Exception as e:
        return {"error": str(e)}

def delete(path):
    try:
        return httpx.delete(f"{NODE_URL}{path}", headers=_auth_headers(), timeout=5).json()
    except Exception as e:
        return {"error": str(e)}

def node_online():
    h = fetch("/health")
    return isinstance(h, dict) and h.get("status") == "ok"

def status_dot(s):
    return {"online": "🟢", "offline": "🔴", "degraded": "🟡"}.get(s, "⚪")

def plotly_layout(**kw):
    return dict(
        paper_bgcolor=BG, plot_bgcolor=BG,
        font=dict(color=TEXT, family="Inter, Segoe UI, sans-serif"),
        margin=dict(t=20, b=20, l=20, r=20),
        **kw
    )

def _to_dataframe(data) -> pd.DataFrame:
    """
    Safely convert API response to a DataFrame.
    Handles: list-of-dicts (normal), single dict (wrap it), empty list/None.
    Fixes: ValueError 'If using all scalar values, you must pass an index'
    """
    if not data:
        return pd.DataFrame()
    if isinstance(data, dict):
        data = [data]
    return pd.DataFrame(data)

# ── Sidebar ───────────────────────────────────────────────────────────────────
with st.sidebar:
    # ── ChainMind brand logo — CM cube + network nodes + wordmark ─────────────
    _CM_LOGO = """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 220 220" width="90" height="90">
      <defs>
        <linearGradient id="g1" x1="0%" y1="0%" x2="100%" y2="100%">
          <stop offset="0%"   stop-color="#a855f7"/>
          <stop offset="100%" stop-color="#6366f1"/>
        </linearGradient>
      </defs>
      <!-- Wireframe cube (thin dark lines) -->
      <g stroke="#1e1b4b" stroke-width="1.6" fill="none" stroke-linejoin="round" opacity="0.5">
        <polygon points="110,22 166,52 166,112 110,142 54,112 54,52"/>
        <line x1="110" y1="22"  x2="110" y2="82"/>
        <line x1="166" y1="52"  x2="110" y2="82"/>
        <line x1="54"  y1="52"  x2="110" y2="82"/>
        <line x1="110" y1="82"  x2="110" y2="142"/>
        <line x1="110" y1="82"  x2="166" y2="112"/>
        <line x1="110" y1="82"  x2="54"  y2="112"/>
      </g>
      <!-- Network node dots -->
      <g fill="#2e1065" opacity="0.75">
        <circle cx="110" cy="22"  r="4.5"/>
        <circle cx="166" cy="52"  r="4.5"/>
        <circle cx="54"  cy="52"  r="4.5"/>
        <circle cx="110" cy="82"  r="4.5"/>
        <circle cx="166" cy="112" r="4.5"/>
        <circle cx="54"  cy="112" r="4.5"/>
        <circle cx="110" cy="142" r="4.5"/>
        <circle cx="138" cy="37"  r="3"/>
        <circle cx="82"  cy="37"  r="3"/>
      </g>
      <!-- C letterform (gradient, chunky rounded) -->
      <path d="M 56,148 L 56,88
               Q 56,72 72,72 L 98,72 L 98,84
               L 74,84 Q 68,84 68,90
               L 68,146 Q 68,152 74,152
               L 98,152 L 98,164
               L 72,164 Q 56,164 56,148 Z"
            fill="url(#g1)"/>
      <!-- M letterform (gradient) -->
      <path d="M 104,72 L 118,72 L 132,106 L 146,72
               L 160,72 L 160,164
               L 148,164 L 148,106
               L 132,132 L 116,106
               L 116,164 L 104,164 Z"
            fill="url(#g1)"/>
    </svg>"""
    st.markdown(
        f"<div style='text-align:center;padding:10px 0 2px'>"
        f"{_CM_LOGO}"
        f"<div style='font-size:13px;font-weight:900;color:{PURPLE};"
        f"letter-spacing:.14em;margin-top:0px;font-family:\"Segoe UI\",system-ui,sans-serif'>"
        f"CHAINMIND</div>"
        f"<div style='font-size:9px;color:#6d28d9;font-weight:600;letter-spacing:.18em;margin-top:2px'>"
        f"NETWORK</div>"
        f"</div>",
        unsafe_allow_html=True,
    )
    st.caption(CFG["node"]["name"])

    online = node_online()
    if online:
        stats = fetch("/stats") or {}
        rep   = stats.get("reputation") or {}
        tier  = rep.get("tier", "nano")
        col   = TIER_COLORS.get(tier, PURPLE)
        st.markdown(
            f"<div class='cm-card' style='padding:12px 16px;margin:8px 0'>"
            f"<div style='font-size:12px;color:#6d28d9;font-weight:600;margin-bottom:4px'>NODE STATUS</div>"
            f"<div style='display:flex;align-items:center;gap:6px'>"
            f"<span style='color:#10b981;font-size:10px'>●</span>"
            f"<span style='font-weight:700;color:{TEXT}'>Online</span></div>"
            f"<div style='margin-top:8px;font-size:13px'>"
            f"<span style='background:{PURPLE_LL};color:{PURPLE};padding:2px 8px;border-radius:12px;font-weight:700;font-size:12px'>"
            f"{rep.get('tier_label','🔵 Nano')}</span></div>"
            f"<div style='margin-top:8px;font-size:12px;color:#4c1d95'>"
            f"IQ <b>{rep.get('iq_earned',0):.4f}</b> &nbsp;·&nbsp; "
            f"Rep <b>{rep.get('reputation_score',0):.0f}</b> &nbsp;·&nbsp; "
            f"Peers <b>{stats.get('peers_online',0)}</b></div>"
            f"</div>",
            unsafe_allow_html=True,
        )
    else:
        st.markdown(
            f"<div class='cm-card' style='padding:12px 16px;margin:8px 0;border-color:#fecaca'>"
            f"<span style='color:#ef4444;font-size:10px'>●</span> "
            f"<b style='color:#991b1b'>Offline</b>"
            f"</div>",
            unsafe_allow_html=True,
        )

    st.divider()
    page = st.radio("Navigation", [
        "🏠 Overview", "🖥 System", "🌐 Network", "🤖 Models",
        "💬 Chat", "✅ Verify", "📋 Tasks", "🏆 Leaderboard",
        "🗳 Governance", "💰 Billing & Account", "⚙️ Settings",
    ], label_visibility="collapsed")

def offline_banner():
    st.markdown(
        f"<div class='cm-card' style='border-color:#fecaca;background:#fff5f5;padding:16px 20px'>"
        f"<span style='color:#ef4444'>●</span> "
        f"<b style='color:#991b1b'>Node is offline.</b> "
        f"Run <code>start.bat node</code> (Windows) or <code>./start.sh node</code> (Mac/Linux)."
        f"</div>",
        unsafe_allow_html=True,
    )

# ════════════════════════════════════════════════════════
if page == "🏠 Overview":
    st.title("Overview")

    if not online:
        offline_banner()
        st.stop()

    stats  = fetch("/stats") or {}
    rep    = stats.get("reputation") or {}
    health = fetch("/health") or {}

    c1, c2, c3, c4, c5 = st.columns(5)
    c1.metric("Tasks Done",   stats.get("total_tasks", 0))
    c2.metric("Tokens",       f"{stats.get('total_tokens', 0):,}")
    c3.metric("IQ Earned",    f"{rep.get('iq_earned', 0):.4f}")
    c4.metric("Reputation",   f"{rep.get('reputation_score', 100):.0f}")
    c5.metric("Peers Online", stats.get("peers_online", 0))

    st.divider()
    col_l, col_r = st.columns(2)

    with col_l:
        st.subheader("Tier Progress")
        tier  = rep.get("tier", "nano")
        col   = TIER_COLORS.get(tier, PURPLE)
        bg    = TIER_BG.get(tier, PURPLE_LL)
        st.markdown(
            f"<div class='cm-card'>"
            f"<div style='font-size:13px;color:#6d28d9;font-weight:600;margin-bottom:6px'>CURRENT TIER</div>"
            f"<div style='background:{bg};display:inline-block;padding:4px 14px;border-radius:20px;"
            f"font-size:18px;font-weight:800;color:{col}'>{rep.get('tier_label','🔵 Nano')}</div>"
            f"<div style='margin-top:10px;color:#4c1d95;font-size:13px'>{rep.get('tier_hardware','')}</div>"
            f"<div style='color:#6d28d9;font-size:13px;margin-top:4px'>"
            f"<b>{rep.get('iq_multiplier',1)}×</b> IQ multiplier</div>"
            f"</div>",
            unsafe_allow_html=True,
        )
        nxt = rep.get("next_tier_label")
        pct = rep.get("progress_pct", 0)
        if nxt:
            st.progress(min(pct / 100, 1.0), text=f"{pct}% to {nxt} — {rep.get('tasks_needed',0)} tasks to go")
        else:
            st.success("🏆 Maximum tier reached — Enterprise!")
        st.caption(f"Ollama: {'✅ Running' if health.get('ollama') else '❌ Not running'} · Uptime: {rep.get('uptime','0h 0m')}")

    with col_r:
        st.subheader("IQ Earned")
        iq = rep.get("iq_earned", 0)
        fig = go.Figure(go.Indicator(
            mode="gauge+number",
            value=iq,
            number={"suffix": " IQ", "font": {"size": 28, "color": TEXT}},
            gauge={
                "axis": {"range": [0, max(iq * 2, 10)], "tickcolor": TEXT},
                "bar":  {"color": PURPLE},
                "bgcolor": PURPLE_LL,
                "steps": [{"range": [0, max(iq * 2, 10)], "color": "#f5f3ff"}],
                "borderwidth": 0,
            },
        ))
        fig.update_layout(height=230, **plotly_layout())
        st.plotly_chart(fig, width='stretch')

    st.subheader("Recent Tasks")
    tasks = fetch("/tasks?limit=10") or []
    if tasks:
        df = _to_dataframe(tasks)
        if not df.empty and "created_at" in df.columns:
            df["time"]    = pd.to_datetime(df["created_at"], unit="s").dt.strftime("%H:%M:%S")
            df["dur_s"]   = (df.get("duration_ms", pd.Series([0]*len(df))) / 1000).round(2)
            df["privacy"] = "🔒 encrypted"
            sm = {"done": "✅ done", "error": "❌ error", "running": "⏳ running", "pending": "🕐 pending"}
            if "status" in df.columns:
                df["status"] = df["status"].map(lambda s: sm.get(s, s))
            cols = [c for c in ["time", "status", "model", "tokens_in", "tokens_out", "dur_s", "routed_to", "privacy"] if c in df.columns]
            st.dataframe(df[cols], width='stretch', hide_index=True)
        else:
            st.dataframe(df, width='stretch', hide_index=True)
    else:
        st.markdown(
            "<div class='cm-card' style='text-align:center;color:#6d28d9;padding:30px'>"
            "No tasks yet — go to <b>💬 Chat</b> to run your first inference."
            "</div>",
            unsafe_allow_html=True,
        )

# ════════════════════════════════════════════════════════
elif page == "🖥 System":
    st.title("Your Hardware")
    st.caption("ChainMind automatically selects models that fit your machine.")

    if not online:
        offline_banner(); st.stop()

    sys_data = fetch("/system") or {}
    hw       = sys_data.get("hardware", {})
    compat   = sys_data.get("compatible_models", {})
    tier     = sys_data.get("recommended_tier", "nano")
    col      = TIER_COLORS.get(tier, PURPLE)

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("RAM",       f"{hw.get('ram_gb','?')} GB")
    c2.metric("CPU Cores", hw.get("cpu_cores", "?"))
    c3.metric("GPU VRAM",  f"{hw.get('gpu_vram_gb',0)} GB" if hw.get("has_gpu") else "No GPU")
    c4.metric("Disk Free", f"{hw.get('disk_free_gb','?')} GB")

    st.divider()
    col_l, col_r = st.columns(2)

    with col_l:
        st.subheader("Hardware Profile")
        st.markdown(f"<div class='cm-card'>"
            f"<div style='display:grid;grid-template-columns:1fr 1fr;gap:10px;font-size:13px'>"
            f"<div><span style='color:#6d28d9;font-weight:600'>OS</span><br/>{hw.get('os','')} {hw.get('arch','')}</div>"
            f"<div><span style='color:#6d28d9;font-weight:600'>Python</span><br/>{hw.get('python','')}</div>"
            f"<div><span style='color:#6d28d9;font-weight:600'>GPU</span><br/>{'✅ ' + hw.get('gpu_name','') if hw.get('has_gpu') else '— CPU-only mode'}</div>"
            f"<div><span style='color:#6d28d9;font-weight:600'>RAM Available</span><br/>{hw.get('ram_available_gb','?')} / {hw.get('ram_gb','?')} GB</div>"
            f"</div></div>", unsafe_allow_html=True)

    with col_r:
        st.subheader("Your Node Tier")
        try:
            from node.reputation import TIER_LABELS as _TL, TIER_HARDWARE as _TH, TIER_MULTIPLIERS as _TM
        except ImportError:
            try:
                from .reputation import TIER_LABELS as _TL, TIER_HARDWARE as _TH, TIER_MULTIPLIERS as _TM
            except ImportError:
                import sys as _sys, os as _os
                _sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
                from reputation import TIER_LABELS as _TL, TIER_HARDWARE as _TH, TIER_MULTIPLIERS as _TM
        TIER_LABELS, TIER_HARDWARE, TIER_MULTIPLIERS = _TL, _TH, _TM
        for t in ["nano", "micro", "standard", "pro", "enterprise"]:
            active = t == tier
            c  = TIER_COLORS[t]
            bg = TIER_BG[t] if active else "transparent"
            border = f"2px solid {c}" if active else "1px solid #ede9fe"
            marker = " ← You" if active else ""
            st.markdown(
                f"<div style='background:{bg};border:{border};border-radius:8px;"
                f"padding:6px 12px;margin:3px 0;font-size:12px;display:flex;justify-content:space-between'>"
                f"<span style='color:{c};font-weight:700'>{TIER_LABELS[t]}</span>"
                f"<span style='color:#6d28d9'>{TIER_MULTIPLIERS[t]}× IQ</span>"
                f"<span style='color:#4c1d95'>{TIER_HARDWARE[t]}{marker}</span>"
                f"</div>",
                unsafe_allow_html=True,
            )

    st.divider()
    st.subheader("Compatible Models")
    st.caption("Only models that fit your RAM and disk space are marked as available.")
    if compat:
        for group, models in compat.items():
            with st.expander(group.upper(), expanded=True):
                for m in models:
                    fits  = m.get("fits", True)
                    badge = f"<span class='cm-badge-fits'>✓ Fits</span>" if fits else f"<span class='cm-badge-big'>✗ {m.get('reason','Too large')}</span>"
                    st.markdown(
                        f"<div style='display:flex;align-items:center;gap:10px;padding:4px 0;font-size:13px'>"
                        f"<b>{m['label']}</b> {badge} "
                        f"<span style='color:#6d28d9'>RAM: {m.get('ram_gb','?')}GB | Disk: {m.get('disk_gb','?')}GB</span>"
                        f"</div>",
                        unsafe_allow_html=True,
                    )
    else:
        st.info("System info not available — make sure the node server is running and the /system endpoint is implemented.")

# ════════════════════════════════════════════════════════
elif page == "🌐 Network":
    st.title("Peer Network")
    if not online:
        offline_banner(); st.stop()

    net   = fetch("/network/status") or {}
    peers = net.get("peers", [])

    central_cfg = CFG.get("central", {})
    central_enabled = (
        central_cfg.get("enabled", False)
        and bool(central_cfg.get("url", ""))
        and bool(central_cfg.get("node_secret", ""))
    )

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Node ID",           (net.get("node_id") or "")[:12] + "…")
    c2.metric("Total Peers Known", net.get("total_peers", 0))
    c3.metric("Peers Online",      net.get("online_peers", 0))
    c4.metric("Central Server",    "🟢 Connected" if central_enabled else "⚪ Disabled")

    st.divider()

    col_l, col_r = st.columns(2)

    with col_l:
        st.subheader("Connect to a Peer")
        peer_url = st.text_input("Peer URL", placeholder="http://192.168.1.100:8000")
        if st.button("🔌 Connect", type="primary") and peer_url.strip():
            with st.spinner("Connecting…"):
                result = post("/network/connect", {"url": peer_url.strip()})
            if "error" in result:
                st.error(f"Failed: {result['error']}")
            else:
                st.success(f"Connected to {result.get('name', peer_url)}")
                st.cache_data.clear()

        st.subheader("Your Node URL")
        pub_url = net.get("public_url")
        if pub_url:
            st.code(pub_url, language="text")
            st.caption("🌍 Public URL — share this with anyone, anywhere.")
        else:
            st.markdown(
                f"<div class='cm-card' style='border-color:#fef3c7;background:#fffbeb;padding:12px 16px'>"
                f"⚠️ <b>Public IP not yet detected.</b> "
                f"The node is still starting up, or IP detection failed. "
                f"You can set <code>node.public_url</code> in <code>config.yaml</code> to override."
                f"</div>",
                unsafe_allow_html=True,
            )
            st.caption(f"Local fallback: {NODE_URL}")

    with col_r:
        st.subheader("Network Map")
        if peers:
            import math
            n  = len(peers) + 1
            angles = [2 * math.pi * i / n for i in range(n)]
            nx = [0] + [math.cos(a) * 1.5 for a in angles[1:]]
            ny = [0] + [math.sin(a) * 1.5 for a in angles[1:]]
            ex, ey = [], []
            for x, y in zip(nx[1:], ny[1:]):
                ex += [0, x, None]; ey += [0, y, None]
            labels = [CFG["node"]["name"]] + [p.get("name") or p["id"][:8] for p in peers]
            colors = [PURPLE] + ["#10b981" if p.get("status") == "online" else "#ef4444" for p in peers]
            fig = go.Figure()
            fig.add_trace(go.Scatter(x=ex, y=ey, mode="lines",
                line=dict(width=1, color=PURPLE_LL), hoverinfo="none"))
            fig.add_trace(go.Scatter(x=nx, y=ny, mode="markers+text",
                marker=dict(size=22, color=colors, line=dict(width=2, color="#ffffff")),
                text=labels, textposition="top center",
                textfont=dict(color=TEXT, size=11)))
            fig.update_layout(height=280, showlegend=False, **plotly_layout(
                xaxis=dict(visible=False), yaxis=dict(visible=False)))
            st.plotly_chart(fig, width='stretch')
        else:
            st.markdown(
                "<div class='cm-card' style='text-align:center;color:#6d28d9;padding:30px'>"
                "No peers yet. Connect to a peer URL or browse the Central Directory below."
                "</div>",
                unsafe_allow_html=True,
            )

    st.divider()

    tab_local, tab_central = st.tabs(["🔗 Local Peers (Gossip)", "🌍 Central Server Directory"])

    with tab_local:
        st.caption("Peers discovered via gossip — your node talks to these directly, peer-to-peer.")
        if peers:
            for p in peers:
                pc1, pc2, pc3, pc4, pc5 = st.columns([3, 2, 1, 1, 1])
                raw_url = p.get("url", "")
                masked_url = raw_url[:10] + "***" if raw_url else "hidden"
                peer_display = f"**{p.get('name') or p['id'][:12]+'…'}**  \n`{masked_url}`"
                pc1.markdown(peer_display)
                pc2.caption(f"ID: {p['id'][:16]}…")
                t   = p.get("tier", "nano")
                col = TIER_COLORS.get(t, PURPLE)
                pc3.markdown(f"<span style='color:{col};font-weight:700'>{t.upper()}</span>", unsafe_allow_html=True)
                pc4.markdown(f"{status_dot(p.get('status','unknown'))} {p.get('status','?')}")
                if pc5.button("🗑", key=f"rm_{p['id']}"):
                    delete(f"/network/peers/{p['id']}")
                    st.cache_data.clear(); st.rerun()
        else:
            st.markdown(
                "<div class='cm-card' style='text-align:center;color:#6d28d9;padding:24px'>"
                "No local peers yet. Connect manually above, or use the Central Server Directory tab."
                "</div>",
                unsafe_allow_html=True,
            )

    with tab_central:
        if not central_enabled:
            st.markdown(
                "<div class='cm-card' style='border-color:#fef3c7;background:#fffbeb'>"
                "⚠️ <b>Central server not configured.</b> "
                "Set <code>central.enabled: true</code> and <code>central.url</code> in <code>config.yaml</code> to enable the directory."
                "</div>",
                unsafe_allow_html=True,
            )
        else:
            central_url = central_cfg.get("url", "").rstrip("/")
            st.caption(
                f"Live directory from **{central_url}** — nodes register here on startup, "
                f"then gossip directly once discovered."
            )

            if st.button("🔄 Refresh Directory"):
                st.cache_data.clear()

            @st.cache_data(ttl=30)
            def fetch_central_peers():
                return fetch("/network/central_peers") or []

            central_peers = fetch_central_peers()

            stats_data = fetch("/stats") or {}
            rep_data   = stats_data.get("reputation") or {}
            my_tier    = rep_data.get("tier", "nano")
            my_iq      = rep_data.get("iq_earned", 0)
            tier_col   = TIER_COLORS.get(my_tier, PURPLE)
            tier_bg    = TIER_BG.get(my_tier, PURPLE_LL)
            node_id_short = (net.get("node_id") or "")[:16]
            st.markdown(
                f"<div class='cm-card' style='background:#f0fdf4;border-color:#bbf7d0;padding:14px 18px;margin-bottom:12px'>"
                f"<div style='font-size:12px;color:#065f46;font-weight:600;margin-bottom:6px'>YOUR NODE IS REGISTERED ON THE CENTRAL SERVER</div>"
                f"<div style='display:flex;gap:16px;align-items:center;flex-wrap:wrap;font-size:13px;color:#166534'>"
                f"<span><b>{CFG['node']['name']}</b></span>"
                f"<span style='background:{tier_bg};color:{tier_col};padding:2px 8px;border-radius:10px;font-size:12px;font-weight:700'>{my_tier.upper()}</span>"
                f"<span>IQ: <b>{my_iq:.4f}</b></span>"
                f"<span style='font-size:11px;color:#047857'>ID: {node_id_short}…</span>"
                f"</div>"
                f"</div>",
                unsafe_allow_html=True,
            )

            if not central_peers:
                st.markdown(
                    "<div class='cm-card' style='border-color:#ddd6fe;background:#faf5ff;padding:20px 24px'>"
                    "<div style='font-size:14px;font-weight:700;color:#4c1d95;margin-bottom:6px'>You are the first node online!</div>"
                    "<div style='font-size:13px;color:#6d28d9;line-height:1.6'>"
                    "No other nodes are in the central directory yet. "
                    "Share your node URL with other operators so they can connect to you, "
                    "or check back later as more nodes come online."
                    "</div>"
                    "</div>",
                    unsafe_allow_html=True,
                )
            else:
                local_peer_ids = {p["id"] for p in peers}
                already_known = sum(1 for p in central_peers if p.get("id") in local_peer_ids)
                new_count     = len(central_peers) - already_known
                st.markdown(
                    f"<div class='cm-card' style='background:#f0fdf4;border-color:#bbf7d0;padding:12px 18px'>"
                    f"<span class='cm-badge-central'>🌍 {len(central_peers)} nodes online</span> &nbsp;"
                    f"<span style='font-size:13px;color:#166534'>"
                    f"{already_known} already in your peer list · "
                    f"<b>{new_count} new</b> available to connect"
                    f"</span>"
                    f"</div>",
                    unsafe_allow_html=True,
                )

                if new_count > 0:
                    if st.button(f"⚡ Connect to all {new_count} new peer(s)", type="primary"):
                        connected = 0
                        errors    = 0
                        with st.spinner(f"Connecting to {new_count} peers…"):
                            for p in central_peers:
                                if p.get("id") not in local_peer_ids:
                                    r = post("/network/connect", {"url": p["url"]})
                                    if "error" not in r:
                                        connected += 1
                                    else:
                                        errors += 1
                        if connected:
                            st.success(f"Connected to {connected} peer(s)." + (f" {errors} failed." if errors else ""))
                        else:
                            st.error(f"All {errors} connection(s) failed.")
                        st.cache_data.clear(); st.rerun()

                st.markdown("<br/>", unsafe_allow_html=True)

                for p in central_peers:
                    peer_id    = p.get("id", "")
                    peer_url   = p.get("url", "")
                    peer_name  = p.get("name") or peer_id[:12] + "…"
                    peer_tier  = p.get("tier", "nano")
                    peer_iq    = p.get("iq_earned", 0)
                    peer_rep   = p.get("reputation", 0)
                    peer_jobs  = p.get("jobs_done", 0)
                    peer_models= p.get("models", [])
                    is_known   = peer_id in local_peer_ids
                    tier_col   = TIER_COLORS.get(peer_tier, PURPLE)
                    tier_bg    = TIER_BG.get(peer_tier, PURPLE_LL)

                    with st.container():
                        ca, cb, cc, cd, ce = st.columns([3, 2, 2, 2, 1])

                        peer_line = f"**{peer_name}**  \n" + f"<span style='font-size:11px;color:#6d28d9'>`{peer_url}`</span>"
                        ca.markdown(peer_line, unsafe_allow_html=True)

                        cb.markdown(
                            f"<span style='background:{tier_bg};color:{tier_col};"
                            f"padding:2px 8px;border-radius:12px;font-size:12px;font-weight:700'>"
                            f"{peer_tier.upper()}</span>",
                            unsafe_allow_html=True,
                        )
                        if peer_models:
                            model_preview = ", ".join(peer_models[:2])
                            if len(peer_models) > 2:
                                model_preview += f" +{len(peer_models)-2}"
                            cb.caption(model_preview)

                        cc.caption(f"IQ: **{peer_iq:.4f}**")
                        cc.caption(f"Rep: {peer_rep:.0f} · Jobs: {peer_jobs}")

                        if is_known:
                            cd.markdown("<span class='cm-badge-ok'>✓ In peer list</span>", unsafe_allow_html=True)
                        else:
                            cd.markdown("<span class='cm-badge-warn'>Not connected</span>", unsafe_allow_html=True)

                        if not is_known:
                            if ce.button("🔌", key=f"central_connect_{peer_id}", help=f"Connect to {peer_name}"):
                                with st.spinner(f"Connecting to {peer_name}…"):
                                    result = post("/network/connect", {"url": peer_url})
                                if "error" in result:
                                    st.error(f"Failed: {result['error']}")
                                else:
                                    st.success(f"Connected to {peer_name}!")
                                    st.cache_data.clear(); st.rerun()
                        else:
                            ce.markdown("✅")

                        st.markdown(
                            "<hr style='margin:6px 0;border-color:#ede9fe;border-width:0.5px'/>",
                            unsafe_allow_html=True,
                        )

            st.markdown(
                f"<div class='cm-card' style='background:#f5f3ff;border-color:#ddd6fe;margin-top:16px'>"
                f"<div style='font-size:12px;color:#4c1d95;font-weight:600;margin-bottom:4px'>HOW IT WORKS</div>"
                f"<div style='font-size:12px;color:#5b21b6;line-height:1.6'>"
                f"<b>1.</b> Your node registers with the central server on startup.<br/>"
                f"<b>2.</b> The directory lists all currently-online nodes.<br/>"
                f"<b>3.</b> Once you connect to a peer, you exchange peer lists directly (gossip).<br/>"
                f"<b>4.</b> After that, you no longer need the central server for that peer — "
                f"it's fully peer-to-peer. The central server is just the bootstrap."
                f"</div></div>",
                unsafe_allow_html=True,
            )

# ════════════════════════════════════════════════════════
elif page == "🤖 Models":
    st.title("Model Manager")
    if not online:
        offline_banner(); st.stop()

    data        = fetch("/models") or {}
    local       = data.get("local", [])
    local_names = {m["name"] for m in local}
    compat      = data.get("compatible", {})
    sys_data    = fetch("/system") or {}
    hw          = sys_data.get("hardware", {})

    st.markdown(
        f"<div class='cm-card' style='background:{PURPLE_LL};border-color:#c4b5fd'>"
        f"🖥 <b>{hw.get('ram_gb','?')}GB RAM</b> · "
        f"{'<b>GPU: ' + hw.get('gpu_name','') + '</b>' if hw.get('has_gpu') else 'CPU-only'} · "
        f"<b>{hw.get('disk_free_gb','?')}GB disk free</b> — compatible models shown as available."
        f"</div>",
        unsafe_allow_html=True,
    )

    st.subheader("Installed Models")
    if local:
        for m in local:
            c1, c2, c3 = st.columns([4, 2, 1])
            c1.markdown(f"**{m['name']}**")
            c2.caption(f"{m.get('size', 0)/1e9:.2f} GB")
            if c3.button("🗑 Remove", key=f"del_{m['name']}"):
                httpx.delete(f"{NODE_URL}/models/{m['name']}", timeout=10)
                st.cache_data.clear(); st.rerun()
    else:
        st.markdown(
            "<div class='cm-card' style='text-align:center;color:#6d28d9;padding:24px'>"
            "No models installed. Download one below."
            "</div>",
            unsafe_allow_html=True,
        )

    st.divider()
    st.subheader("Download a Model")
    st.caption("✓ Fits = runs on your machine now. ✗ Too large = skip for now.")

    tabs = st.tabs(["🔵 Tiny", "🟢 Small", "🟡 Medium", "🔴 Large"])
    for tab, key in zip(tabs, ["tiny", "small", "medium", "large"]):
        with tab:
            models_in_group = compat.get(key, data.get("catalog", {}).get(key, []))
            for m in models_in_group:
                fits     = m.get("fits", True)
                is_local = m["name"] in local_names
                ca, cb   = st.columns([5, 1])
                if fits:
                    label = f"{'✅ ' if is_local else ''}**{m['label']}** — RAM: {m.get('ram_gb','?')}GB"
                else:
                    label = f"~~{m['label']}~~ — Needs {m.get('ram_gb','?')}GB RAM"
                ca.markdown(label)
                if not is_local and fits:
                    if cb.button("⬇ Pull", key=f"pull_{m['name']}"):
                        post("/models/pull", {"model": m["name"]})
                        st.success(f"Downloading {m['name']}…")
                        st.cache_data.clear()
                elif is_local:
                    cb.markdown("✅")
                else:
                    cb.markdown("—")

    st.divider()
    st.subheader("Pull Any Model by Name")
    c1, c2 = st.columns([4, 1])
    custom = c1.text_input("Model name", placeholder="llama3.2:3b", label_visibility="collapsed")
    if c2.button("Pull", type="primary") and custom.strip():
        post("/models/pull", {"model": custom.strip()})
        st.success(f"Downloading {custom.strip()}…")

# ════════════════════════════════════════════════════════
elif page == "💬 Chat":
    st.title("Chat")
    if not online:
        offline_banner(); st.stop()

    data        = fetch("/models") or {}
    local       = data.get("local", [])
    model_names = [m["name"] for m in local]

    if not model_names:
        st.markdown(
            "<div class='cm-card' style='border-color:#fef3c7;background:#fffbeb'>"
            "⚠️ No models installed. Go to <b>🤖 Models</b> and pull one first "
            "(e.g. <code>tinyllama</code>)."
            "</div>",
            unsafe_allow_html=True,
        )
        st.stop()

    c1, c2, c3 = st.columns([3, 1, 1])
    selected_model = c1.selectbox("Model", model_names)
    use_network    = c2.checkbox("🌐 Network", help="Distribute task across peers")
    verify         = c3.checkbox("✅ Verify",  help="Run PoUI verification on response")

    if "messages" not in st.session_state:
        st.session_state.messages = []

    for msg in st.session_state.messages:
        with st.chat_message(msg["role"]):
            st.write(msg["content"])
            if msg.get("meta"):
                st.caption(msg["meta"])
            if msg.get("verification"):
                v    = msg["verification"]
                icon = "✅" if v.get("passed") else "❌"
                if v.get("verified"):
                    st.caption(f"PoUI: {icon} {v.get('method','?')} | confidence {v.get('confidence',0):.0%} | {v.get('reason','')}")

    if prompt := st.chat_input("Type a message…"):
        st.session_state.messages.append({"role": "user", "content": prompt})
        with st.chat_message("user"):
            st.write(prompt)
        with st.chat_message("assistant"):
            with st.spinner("Thinking…"):
                try:
                    endpoint = "/infer/verify" if verify else "/infer"
                    r    = httpx.post(f"{NODE_URL}{endpoint}",
                           json={"prompt": prompt, "model": selected_model, "use_network": use_network}, timeout=10)
                    resp = r.json()
                    task_id = resp.get("task_id", "")
                    vdata   = resp.get("verification")

                    if not vdata:
                        for _ in range(300):
                            time.sleep(1)
                            t = httpx.get(f"{NODE_URL}/tasks/{task_id}", timeout=5).json()
                            if t["status"] in ("done", "error"):
                                break
                    else:
                        t = resp

                    reply  = t.get("result") or "Error — no result"
                    routed = t.get("routed_to", "local")
                    tok_in = t.get("tokens_in", 0)
                    tok_out= t.get("tokens_out", 0)
                    dur    = t.get("duration_ms", 0) / 1000
                    meta   = f"Routed: {routed} · {tok_in}→{tok_out} tokens · {dur:.1f}s"
                except Exception as e:
                    reply = f"Error: {e}"; meta = ""; vdata = None

            st.write(reply)
            st.caption(meta)
            if vdata and vdata.get("verified"):
                icon = "✅" if vdata.get("passed") else "❌"
                st.caption(f"PoUI: {icon} {vdata.get('method','?')} | {vdata.get('reason','')}")
            st.session_state.messages.append(
                {"role": "assistant", "content": reply, "meta": meta, "verification": vdata}
            )

    if st.button("🗑 Clear chat"):
        st.session_state.messages = []; st.rerun()

# ════════════════════════════════════════════════════════
elif page == "✅ Verify":
    st.title("PoUI — Proof of Useful Intelligence")
    st.caption("Submit a task and see Layer 1 auto-verification results.")
    if not online:
        offline_banner(); st.stop()

    data        = fetch("/models") or {}
    local       = data.get("local", [])
    model_names = [m["name"] for m in local]

    st.markdown("""
    <div class='cm-card'>
    <b style='color:#7c3aed'>Layer 1 — Deterministic Verification</b><br/>
    <ul style='margin:8px 0 0;color:#1e1b4b;font-size:13px'>
    <li><b>Math</b> — checks if the numeric result is correct</li>
    <li><b>Code</b> — checks if the code is valid Python syntax</li>
    <li><b>Factual / Open</b> — routes to Layer 2 consensus ranking</li>
    </ul>
    </div>
    """, unsafe_allow_html=True)

    c1, c2 = st.columns([4, 1])
    test_prompt = c1.text_input("Test prompt", value="What is 17 * 43?",
        placeholder="e.g. What is 12 + 34? or Write a Python function to reverse a string")
    if model_names:
        sel_model = c2.selectbox("Model", model_names, label_visibility="collapsed")

    if st.button("Run & Verify", type="primary") and model_names:
        with st.spinner("Running inference + verification…"):
            r      = httpx.post(f"{NODE_URL}/infer/verify",
                     json={"prompt": test_prompt, "model": sel_model}, timeout=120)
            result = r.json()

        v = result.get("verification", {})
        col_l, col_r = st.columns(2)
        with col_l:
            st.subheader("Response")
            st.markdown(
                f"<div class='cm-card'>{result.get('result','')}</div>",
                unsafe_allow_html=True,
            )
            st.caption(f"Tokens: {result.get('tokens_in',0)} → {result.get('tokens_out',0)}")
        with col_r:
            st.subheader("Verification Result")
            if v.get("verified"):
                passed = v.get("passed")
                badge  = "<span class='cm-badge-ok'>✅ PASSED</span>" if passed else "<span class='cm-badge-err'>❌ FAILED</span>"
                st.markdown(f"<div class='cm-card'>"
                    f"<div style='margin-bottom:8px'>{badge}</div>"
                    f"<div style='font-size:13px;color:#1e1b4b'>"
                    f"Method: <b>{v.get('method','?').upper()}</b><br/>"
                    f"Confidence: <b>{v.get('confidence',0):.0%}</b><br/>"
                    f"Task type: <b>{v.get('task_type','?')}</b>"
                    + (f"<br/>Expected: <code>{v['expected']}</code> · Got: <code>{v.get('got','?')}</code>" if v.get('expected') else "") +
                    f"<br/><span style='color:#6d28d9'>{v.get('reason','')}</span>"
                    f"</div></div>", unsafe_allow_html=True)
            else:
                st.info(f"Auto-verification not applicable: {v.get('reason','')}")

    st.divider()
    st.subheader("Layer 2 — Consensus Ranking (Multi-Peer)")
    col_a, col_b = st.columns(2)
    resp_a = col_a.text_area("Response A", height=150, placeholder="Paste peer response A…")
    resp_b = col_b.text_area("Response B", height=150, placeholder="Paste peer response B…")

    if st.button("Compare Responses") and resp_a.strip() and resp_b.strip():
        payload = {"responses": [{"peer_id": "peer_a", "result": resp_a}, {"peer_id": "peer_b", "result": resp_b}]}
        result  = httpx.post(f"{NODE_URL}/consensus/rank", json=payload, timeout=10).json()
        scores  = result.get("scores", [])
        st.markdown(
            f"<div class='cm-card'><b>Consensus winner: Peer {scores[0]['peer_id'] if scores else '?'} "
            f"(score: {scores[0]['score']:.2f})</b></div>" if scores else
            "<div class='cm-card'>Could not determine winner.</div>",
            unsafe_allow_html=True,
        )
        for s in scores:
            delta  = result.get("deltas", {}).get(s["peer_id"], 0)
            rep_ch = ("+" if delta >= 0 else "") + str(delta)
            st.caption(f"Peer {s['peer_id']}: similarity {s['score']:.3f} → reputation {rep_ch}")

# ════════════════════════════════════════════════════════
elif page == "📋 Tasks":
    st.title("Task Log")
    if not online:
        offline_banner(); st.stop()

    c1, c2      = st.columns([2, 1])
    limit       = c1.slider("Show last N tasks", 10, 500, 50)
    filter_status = c2.selectbox("Filter", ["all", "done", "error", "running", "pending"])

    tasks = fetch(f"/tasks?limit={limit}") or []
    if filter_status != "all":
        tasks = [t for t in tasks if isinstance(t, dict) and t.get("status") == filter_status]

    if tasks:
        df = _to_dataframe(tasks)
        if not df.empty and "created_at" in df.columns:
            df["time"]    = pd.to_datetime(df["created_at"], unit="s").dt.strftime("%Y-%m-%d %H:%M:%S")
            df["dur_s"]   = (df.get("duration_ms", pd.Series([0]*len(df))) / 1000).round(2)
            df["privacy"] = "🔒 encrypted"
            sm = {"done": "✅ done", "error": "❌ error", "running": "⏳ running", "pending": "🕐 pending"}
            if "status" in df.columns:
                df["status"] = df["status"].map(lambda s: sm.get(s, s))
            cols = [c for c in ["time", "status", "model", "routed_to", "tokens_in", "tokens_out", "dur_s", "privacy"] if c in df.columns]
            st.dataframe(df[cols], width='stretch', hide_index=True)
            done_count = sum(1 for t in tasks if isinstance(t, dict) and "done" in t.get("status", ""))
            err_count  = sum(1 for t in tasks if isinstance(t, dict) and "error" in t.get("status", ""))
            st.caption(f"{len(tasks)} tasks · {done_count} done · {err_count} errors")
        else:
            st.dataframe(df, width='stretch', hide_index=True)
    else:
        st.markdown(
            "<div class='cm-card' style='text-align:center;color:#6d28d9;padding:30px'>No tasks match.</div>",
            unsafe_allow_html=True,
        )

# ════════════════════════════════════════════════════════
elif page == "🏆 Leaderboard":
    st.title("Leaderboard")
    if not online:
        offline_banner(); st.stop()

    board_data = fetch("/leaderboard") or {}
    local      = board_data.get("local_node") or {}
    board      = board_data.get("leaderboard") or []
    tier       = local.get("tier", "nano")
    col        = TIER_COLORS.get(tier, PURPLE)

    st.markdown(
        f"<div class='cm-card' style='background:{PURPLE_LL};border-color:#c4b5fd'>"
        f"<b>Your Node</b> &nbsp;"
        f"<span style='background:{col};color:#fff;padding:2px 10px;border-radius:12px;font-size:12px;font-weight:700'>"
        f"{local.get('tier_label','Nano')}</span><br/>"
        f"<span style='color:#4c1d95;font-size:13px'>"
        f"IQ: <b>{local.get('iq_earned',0):.6f}</b> · Tasks: <b>{local.get('tasks_done',0)}</b> · "
        f"Reputation: <b>{local.get('reputation_score',100):.0f}/1000</b></span>"
        f"</div>",
        unsafe_allow_html=True,
    )

    st.subheader("Network Rankings")
    if board:
        df = _to_dataframe(board)
        if not df.empty:
            if "last_seen" in df.columns:
                df["last_seen"] = pd.to_datetime(df["last_seen"], unit="s", errors="coerce").dt.strftime("%H:%M:%S")
            if "iq_earned" in df.columns:
                df["iq_earned"] = df["iq_earned"].round(6)
            if "reputation" in df.columns:
                df["reputation"] = df["reputation"].round(1)
            sm = {"online": "🟢", "offline": "🔴", "degraded": "🟡", "unknown": "⚪"}
            if "status" in df.columns:
                df["status"] = df["status"].map(lambda s: sm.get(s, "⚪") + " " + s)
            if "name" in df.columns and "id" in df.columns:
                df["name"] = df.apply(lambda r: r["name"] if r["name"] else r["id"][:12] + "…", axis=1)
            cols = [c for c in ["name", "tier", "iq_earned", "tasks_done", "reputation", "status", "last_seen"] if c in df.columns]
            st.dataframe(df[cols], width='stretch', hide_index=True)
        fig = go.Figure(go.Bar(
            x=[p.get("name") or p["id"][:8] for p in board[:20]],
            y=[p.get("iq_earned", 0) for p in board[:20]],
            marker=dict(color=PURPLE, opacity=0.85),
        ))
        fig.update_layout(height=260, xaxis_tickangle=-45, **plotly_layout())
        st.plotly_chart(fig, width='stretch')
    else:
        st.markdown(
            "<div class='cm-card' style='text-align:center;color:#6d28d9;padding:30px'>"
            "No peers on the leaderboard yet. Connect to peers to see rankings."
            "</div>",
            unsafe_allow_html=True,
        )

# ════════════════════════════════════════════════════════
elif page == "🗳 Governance":
    st.title("Governance — Protocol Voting")
    st.caption("IQ holders vote on protocol proposals. 5% quorum required, 67% supermajority to pass.")
    if not online:
        offline_banner(); st.stop()

    gov_data   = fetch("/governance/proposals") or {}
    proposals  = gov_data.get("proposals", [])
    stats_data = fetch("/stats") or {}
    my_iq      = (stats_data.get("reputation") or {}).get("iq_earned", 0)

    st.markdown(
        f"<div class='cm-card' style='background:{PURPLE_LL};border-color:#c4b5fd'>"
        f"Your IQ balance: <b>{my_iq:.4f} IQ</b> — each IQ = 1 vote weight"
        f"</div>",
        unsafe_allow_html=True,
    )

    with st.expander("➕ Create a Proposal (requires ≥1.0 IQ)"):
        p_title = st.text_input("Title", placeholder="IQP-XXX: Short description")
        p_desc  = st.text_area("Description", placeholder="Explain what you're proposing…", height=100)
        p_days  = st.slider("Voting period (days)", 1, 14, 7)
        if st.button("Submit Proposal") and p_title:
            r = post("/governance/propose", {"title": p_title, "description": p_desc, "duration_days": p_days})
            if "error" in r:
                st.error(r["error"])
            else:
                st.success(f"Proposal created: {r.get('id','')[:12]}…")
                st.cache_data.clear(); st.rerun()

    st.subheader("Active Proposals")
    for p in proposals:
        status_badge = {
            "active":   "<span class='cm-badge-warn'>⏳ Active</span>",
            "passed":   "<span class='cm-badge-ok'>✅ Passed</span>",
            "rejected": "<span class='cm-badge-err'>❌ Rejected</span>",
        }.get(p["status"], p["status"])
        total = p.get("total_votes", 0)
        yes_w = p["yes_pct"] / 100 if total > 0 else 0

        with st.expander(f"{p['title']} {status_badge}", expanded=p["status"] == "active"):
            st.markdown(p.get("description", ""), unsafe_allow_html=False)
            st.divider()
            cA, cB, cC, cD = st.columns(4)
            cA.metric("Yes", f"{p['yes_pct']:.1f}%")
            cB.metric("No",  f"{p['no_pct']:.1f}%")
            cC.metric("Participation", f"{p['participation_pct']:.3f}%")
            cD.metric("Time Left", f"{p['time_remaining_h']:.1f}h")
            if total > 0:
                st.progress(yes_w, text=f"{p['yes_pct']:.1f}% yes of {total:.2f} IQ cast")

            if p["status"] == "active":
                vc1, vc2, vc3 = st.columns(3)
                for label, vote, col_btn in [("👍 Yes", "yes", vc1), ("👎 No", "no", vc2), ("🤷 Abstain", "abstain", vc3)]:
                    if col_btn.button(label, key=f"vote_{p['id']}_{vote}"):
                        r2 = post("/governance/vote", {"proposal_id": p["id"], "vote": vote, "iq_weight": my_iq})
                        if "error" in r2:
                            st.error(r2["error"])
                        else:
                            st.success(f"Vote cast: {vote}")
                            st.cache_data.clear(); st.rerun()

# ════════════════════════════════════════════════════════
elif page == "💰 Billing & Account":
    st.title("💰 Billing & Account")

    if not node_online():
        offline_banner()
        st.stop()

    central_url = CFG.get("central", {}).get("url", "https://chainmind.com.ng").rstrip("/")
    central_cfg = CFG.get("central", {})
    central_ok  = (
        central_cfg.get("enabled", False)
        and bool(central_cfg.get("url", ""))
        and bool(central_cfg.get("node_secret", ""))
    )

    st.subheader("Earnings & Withdrawals")
    earnings_data = fetch("/account/earnings") or {}
    earnings = earnings_data.get("earnings") or {}

    local_stats = fetch("/stats") or {}
    local_rep   = local_stats.get("reputation") or {}
    local_iq    = local_rep.get("iq_earned", 0.0)

    if earnings:
        iq_total  = float(earnings.get("iq_earned", local_iq))
        iq_avail  = float(earnings.get("available_iq") or
                          max(0.0, iq_total - float(earnings.get("committed_iq", 0))))
        node_status = earnings.get("status", "—")
    else:
        iq_total  = local_iq
        iq_avail  = local_iq
        node_status = "local"

    c1, c2, c3 = st.columns(3)
    c1.metric("Total IQ Earned", f"{iq_total:,.4f} IQ")
    c2.metric("Available to Withdraw", f"{iq_avail:,.4f} IQ")
    c3.metric("Node Status", node_status.upper())

    if not earnings:
        if not central_ok:
            st.markdown(
                f"<div class='cm-card' style='border-color:#fef3c7;background:#fffbeb'>"
                f"⚠️ <b>Central server not configured.</b> "
                f"Set <code>central.enabled: true</code>, <code>central.url</code>, and "
                f"<code>central.node_secret</code> in <code>config.yaml</code> to enable earnings tracking."
                f"</div>",
                unsafe_allow_html=True,
            )
        else:
            st.info(
                "Earnings data loading… The node may not yet be registered on the central server. "
                "Make sure the node is running and connected — data appears within 30 seconds."
            )

    st.divider()

    st.subheader("🔗 Link Web Account")
    linked_email = earnings.get("linked_email") or ""

    if linked_email:
        linked_at = (earnings.get("linked_at") or "")[:10]
        st.success(f"✅ Linked to **{linked_email}**" + (f" since {linked_at}" if linked_at else ""))
        st.markdown(
            f"[Open Web Dashboard ↗]({central_url}/dashboard/node-earnings.php) — "
            "view full earnings history, manage withdrawals, and top up credits."
        )
    else:
        st.markdown(
            f"Link this node to your ChainMind web account at "
            f"[{central_url}]({central_url}) to see earnings online and request withdrawals."
        )
        with st.form("link_form"):
            st.markdown(
                "**Steps:**\n"
                f"1. Open [{central_url}/dashboard/node-settings.php]"
                f"({central_url}/dashboard/node-settings.php)\n"
                "2. Copy the 10-minute pairing token shown on that page\n"
                "3. Paste it below and click **Link Account**"
            )
            link_token = st.text_input("Pairing Token", placeholder="Paste token from web dashboard…")
            submitted  = st.form_submit_button("🔗 Link Account", type="primary")
            if submitted and link_token.strip():
                with st.spinner("Linking…"):
                    result = post("/account/link", {"token": link_token.strip()})
                if result.get("ok"):
                    st.success(f"✅ Linked to **{result.get('user_email', 'your account')}**! Stats update within 30s.")
                    st.balloons()
                    st.cache_data.clear()
                else:
                    err = result.get("error", "Link failed — check the token and try again.")
                    st.error(f"❌ {err}")
            elif submitted:
                st.warning("Please paste a pairing token first.")

    st.divider()

    st.subheader("💸 Request Withdrawal")
    min_wd = 10.0

    if not central_ok:
        st.warning("Configure the central server in config.yaml to enable withdrawals.")
    elif not linked_email:
        st.info("Link your web account above to request withdrawals.")
    elif iq_avail < min_wd:
        st.info(
            f"You need at least **{min_wd} IQ** to withdraw. "
            f"You currently have **{iq_avail:.4f} IQ** available. "
            "Keep processing jobs to earn more!"
        )
    else:
        with st.form("withdraw_form"):
            wd_amount = st.number_input("IQ Amount to Withdraw", min_value=min_wd,
                                         max_value=float(iq_avail),
                                         value=float(min(iq_avail, min_wd)),
                                         step=1.0, format="%.4f")
            wd_method = st.radio("Payout Method", ["crypto", "fiat"], horizontal=True)
            wd_wallet = wd_bank = wd_account = ""
            if wd_method == "crypto":
                wd_wallet = st.text_input("Wallet Address", placeholder="USDT/ETH/BNB address")
                st.caption("Supports USDT (TRC-20), USDC, ETH, BNB — processed via NOWPayments")
            else:
                wd_bank    = st.text_input("Bank Name", placeholder="e.g. GTBank, Zenith")
                wd_account = st.text_input("Account Number", placeholder="10-digit NUBAN")
                st.caption("NGN bank transfer — processed manually within 2 business days")
            wd_submit = st.form_submit_button("📤 Submit Withdrawal Request", type="primary")
            if wd_submit:
                with st.spinner("Submitting…"):
                    r = post("/account/withdraw", {
                        "iq_amount": wd_amount,
                        "method":    wd_method,
                        "wallet":    wd_wallet,
                        "bank":      wd_bank,
                        "account":   wd_account,
                    })
                if r.get("requested"):
                    st.success(f"✅ {r.get('message', 'Withdrawal submitted!')}")
                else:
                    st.error(f"❌ {r.get('error', 'Withdrawal failed.')}")

    st.divider()

    if earnings and earnings.get("withdrawals"):
        st.subheader("📋 Withdrawal History")
        wds = earnings["withdrawals"]
        rows = [{
            "Date":       w.get("requested_at", "")[:10],
            "IQ Amount":  f"{float(w.get('iq_amount',0)):,.4f}",
            "USD Value":  f"${float(w.get('usd_value',0)):,.2f}",
            "Method":     w.get("method",""),
            "Status":     w.get("status",""),
        } for w in wds]
        st.dataframe(pd.DataFrame(rows), width='stretch', hide_index=True)

elif page == "⚙️ Settings":
    st.title("Settings")
    st.subheader("Node Configuration")

    _dash_cfg = CFG.get("dashboard", {})
    _dash_port = _dash_cfg.get("port", 8501) if _dash_cfg else 8501

    st.markdown(
        f"<div class='cm-card'>"
        f"<div style='display:grid;grid-template-columns:1fr 1fr;gap:12px;font-size:13px'>"
        f"<div><span style='color:#6d28d9;font-weight:600'>Node Name</span><br/>{CFG['node']['name']}</div>"
        f"<div><span style='color:#6d28d9;font-weight:600'>API Port</span><br/>{CFG['node']['port']}</div>"
        f"<div><span style='color:#6d28d9;font-weight:600'>Dashboard Port</span><br/>{_dash_port}</div>"
        f"<div><span style='color:#6d28d9;font-weight:600'>Ollama</span><br/>{CFG.get('ollama',{}).get('host','localhost')}:{CFG.get('ollama',{}).get('port',11434)}</div>"
        f"<div><span style='color:#6d28d9;font-weight:600'>Max Peers</span><br/>{CFG.get('network',{}).get('max_peers','?')}</div>"
        f"<div><span style='color:#6d28d9;font-weight:600'>Database</span><br/>{CFG.get('database',{}).get('path','?')}</div>"
        f"</div></div>",
        unsafe_allow_html=True,
    )

    central_cfg = CFG.get("central", {})
    central_enabled = (
        central_cfg.get("enabled", False)
        and bool(central_cfg.get("url", ""))
        and bool(central_cfg.get("node_secret", ""))
    )
    if central_enabled:
        central_status_badge = "<span class='cm-badge-ok'>Enabled</span>"
    else:
        central_status_badge = "<span class='cm-badge-warn'>Disabled</span>"
    st.subheader("Central Server")
    st.markdown(
        f"<div class='cm-card'>"
        f"<div style='display:grid;grid-template-columns:1fr 1fr;gap:12px;font-size:13px'>"
        f"<div><span style='color:#6d28d9;font-weight:600'>Status</span><br/>"
        f"{central_status_badge}"
        f"</div>"
        f"<div><span style='color:#6d28d9;font-weight:600'>URL</span><br/>"
        f"{central_cfg.get('url','—') or '—'}</div>"
        f"<div><span style='color:#6d28d9;font-weight:600'>Node Secret</span><br/>"
        f"{'••••••••' if central_cfg.get('node_secret') else '—'}</div>"
        f"<div><span style='color:#6d28d9;font-weight:600'>Discovery</span><br/>"
        f"Every {CFG.get('network',{}).get('discovery_interval',60)}s</div>"
        f"</div></div>",
        unsafe_allow_html=True,
    )

    st.caption("Edit `config.yaml` in the node folder to change these settings.")
    st.divider()
    st.subheader("IQ Token Economy")
    _tokens_cfg = CFG.get("tokens", {})
    _tier_mults = _tokens_cfg.get("tier_multipliers", {})
    st.markdown(
        f"<div class='cm-card'>"
        f"<div style='font-size:13px;color:#1e1b4b'>"
        f"Base rate: <b>{_tokens_cfg.get('base_rate', '?')} IQ per token</b><br/>"
        f"<div style='margin-top:8px;display:flex;gap:8px;flex-wrap:wrap'>"
        + "".join(
            f"<span style='background:{TIER_BG.get(t, PURPLE_LL)};color:{TIER_COLORS.get(t, PURPLE)};padding:4px 12px;"
            f"border-radius:12px;font-weight:700;font-size:12px'>{t.upper()} {v}×</span>"
            for t, v in _tier_mults.items()
        ) +
        f"</div></div></div>",
        unsafe_allow_html=True,
    )
    st.divider()
    st.caption("ChainMind Network — Modern AI inference, peer-to-peer.")
