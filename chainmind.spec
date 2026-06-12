# chainmind.spec
# PyInstaller build spec for ChainMind Node
#
# Build:  pyinstaller chainmind.spec --clean
#
# Bundles:
#   - chainmind_launcher.py       (entry point)
#   - All node/* Python source
#   - Streamlit static files
#   - Package dist-info (importlib.metadata)
#   - config.yaml                 (default template with models catalog)
#   - VERSION
#   - psutil                      (hardware detection — RAM/CPU/disk)
#   - pystray                     (system tray icon)

import sys
from pathlib import Path
import streamlit
from PyInstaller.utils.hooks import copy_metadata, collect_data_files, collect_all

def _icon():
    if sys.platform == "win32":
        p = Path("assets/icon.ico")
        return str(p) if p.exists() else None
    elif sys.platform == "darwin":
        p = Path("assets/icon.icns")
        return str(p) if p.exists() else None
    return None

STREAMLIT_DIR = Path(streamlit.__file__).parent

# ── Package metadata ───────────────────────────────────────────────────────
metadata_datas = []
for pkg in [
    "streamlit", "altair", "pydeck", "pyarrow", "pandas", "httpx",
    "fastapi", "uvicorn", "click", "rich", "packaging", "gitpython",
    "tenacity", "toml", "validators", "plotly", "numpy", "requests",
    "PIL", "attr", "attrs", "toolz", "jinja2", "psutil", "pystray",
]:
    try:
        metadata_datas += copy_metadata(pkg)
    except Exception:
        pass

# ── psutil — collect everything (binaries + data + hidden imports) ─────────
try:
    psutil_datas, psutil_binaries, psutil_hidden = collect_all("psutil")
except Exception:
    psutil_datas, psutil_binaries, psutil_hidden = [], [], []

# ── pystray ────────────────────────────────────────────────────────────────
try:
    pystray_datas, pystray_binaries, pystray_hidden = collect_all("pystray")
except Exception:
    pystray_datas, pystray_binaries, pystray_hidden = [], [], []

block_cipher = None

a = Analysis(
    ["chainmind_launcher.py"],
    pathex=["."],
    binaries=[] + psutil_binaries + pystray_binaries,
    datas=[
        (str(STREAMLIT_DIR / "static"),  "streamlit/static"),
        (str(STREAMLIT_DIR / "runtime"), "streamlit/runtime"),
        (str(STREAMLIT_DIR / "web"),     "streamlit/web"),
        ("node",                         "node"),
        # Brand assets: icon.ico, icon.png, tray.png, favicon.png
        ("assets",                       "assets"),
        # Default config with full models catalog — copied to install dir on first run
        ("config.yaml",                  "."),
        ("VERSION",                      "."),
    ] + metadata_datas + psutil_datas + pystray_datas,
    hiddenimports=[
        # ── psutil platform modules ───────────────────────────────────────
        "psutil",
        "psutil._common",
        "psutil._pswindows",
        "psutil._pslinux",
        "psutil._psosx",
        "psutil._psaix",
        "psutil._psbsd",
        "psutil._pssunos",
        # ── pystray ───────────────────────────────────────────────────────
        "pystray",
        "pystray._win32",
        "pystray._darwin",
        "pystray._xorg",
        "pystray._gtk",
        # ── Windows stdlib ────────────────────────────────────────────────
        "winreg",
        # ── PIL / Pillow ──────────────────────────────────────────────────
        "PIL", "PIL.Image", "PIL.ImageDraw", "PIL.ImageFont",
        # ── Streamlit ────────────────────────────────────────────────────
        "streamlit",
        "streamlit.web",
        "streamlit.web.cli",
        "streamlit.web.server",
        "streamlit.web.server.server",
        "streamlit.runtime",
        "streamlit.runtime.scriptrunner",
        "streamlit.runtime.scriptrunner.magic_funcs",
        "streamlit.runtime.state",
        "streamlit.runtime.uploaded_file_manager",
        "streamlit.components.v1",
        # ── Data / plotting ──────────────────────────────────────────────
        "altair", "pydeck", "pyarrow", "pandas", "numpy",
        "plotly", "plotly.graph_objects", "plotly.express",
        "plotly.subplots", "plotly.figure_factory", "plotly.io",
        # ── HTTP / API ───────────────────────────────────────────────────
        "httpx", "httpx._transports", "httpx._transports.default",
        "fastapi", "fastapi.middleware", "fastapi.middleware.cors",
        "uvicorn", "uvicorn.logging",
        "uvicorn.loops", "uvicorn.loops.auto", "uvicorn.loops.asyncio",
        "uvicorn.protocols", "uvicorn.protocols.http",
        "uvicorn.protocols.http.auto", "uvicorn.protocols.http.h11_impl",
        "uvicorn.protocols.websockets", "uvicorn.protocols.websockets.auto",
        "uvicorn.lifespan", "uvicorn.lifespan.on",
        # ── Misc ─────────────────────────────────────────────────────────
        "importlib.metadata", "importlib_metadata", "pkg_resources",
        "requests", "attr", "attrs", "toolz", "jinja2", "jinja2.ext",
    ] + psutil_hidden + pystray_hidden,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name="ChainMind-Node",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=_icon() or (str(Path('assets/icon.ico')) if Path('assets/icon.ico').exists() else None),
)

# ── macOS .app bundle ─────────────────────────────────────────────────────────
# Only active when building on macOS; on Windows/Linux this block is a no-op.
if sys.platform == "darwin":
    app = BUNDLE(
        exe,
        name="ChainMind Network.app",
        icon=_icon(),
        bundle_identifier="com.chainmind.network",
        info_plist={
            "CFBundleName":             "ChainMind Node",
            "CFBundleDisplayName":      "ChainMind Network",
            "CFBundleVersion":          Path("VERSION").read_text().strip() if Path("VERSION").exists() else "1.0.0",
            "CFBundleShortVersionString": Path("VERSION").read_text().strip() if Path("VERSION").exists() else "1.0.0",
            "CFBundleExecutable":       "ChainMind-Node",
            "CFBundleIdentifier":       "com.chainmind.network",
            "CFBundlePackageType":      "APPL",
            # LSUIElement=True → menu-bar-only app (no Dock icon by default)
            # Set to False if you want a Dock icon.
            "LSUIElement":              True,
            "NSHighResolutionCapable":  True,
            # Allow Hardened Runtime / notarisation later
            "com.apple.security.cs.allow-unsigned-executable-memory": True,
        },
    )
