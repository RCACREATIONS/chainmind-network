# chainmind.spec
# PyInstaller build spec for ChainMind Node
#
# Build:  pyinstaller chainmind.spec --clean
#
# The spec bundles:
#   - chainmind_launcher.py  (entry point)
#   - All node/* Python source
#   - Streamlit static files (frozen quirk)
#   - Streamlit + other package dist-info (so importlib.metadata works)
#   - VERSION file

import sys
from pathlib import Path
import streamlit
from PyInstaller.utils.hooks import copy_metadata, collect_data_files

def _icon():
    """Return icon path only if the file actually exists — avoids build crash."""
    if sys.platform == "win32":
        p = Path("assets/icon.ico")
        return str(p) if p.exists() else None
    elif sys.platform == "darwin":
        p = Path("assets/icon.icns")
        return str(p) if p.exists() else None
    return None

STREAMLIT_DIR = Path(streamlit.__file__).parent

# ── Package metadata (dist-info) that must survive into the frozen bundle ──
# Streamlit reads its own version via importlib.metadata at import time.
# Without these, you get: PackageNotFoundError: No package metadata for streamlit
metadata_datas = []
for pkg in [
    "streamlit",
    "altair",
    "pydeck",
    "pyarrow",
    "pandas",
    "httpx",
    "fastapi",
    "uvicorn",
    "click",
    "rich",
    "packaging",
    "gitpython",
    "tenacity",
    "toml",
    "validators",
    "plotly",
    "numpy",
    "requests",
    "PIL",
    "attr",
    "attrs",
    "toolz",
    "jinja2",
]:
    try:
        metadata_datas += copy_metadata(pkg)
    except Exception:
        pass   # package not installed — skip silently

block_cipher = None

a = Analysis(
    ["chainmind_launcher.py"],
    pathex=["."],
    binaries=[],
    datas=[
        # Streamlit static assets — required for frozen builds
        (str(STREAMLIT_DIR / "static"),       "streamlit/static"),
        (str(STREAMLIT_DIR / "runtime"),      "streamlit/runtime"),
        (str(STREAMLIT_DIR / "web"),          "streamlit/web"),
        # Your node package
        ("node",                              "node"),
        # Version marker
        ("VERSION",                           "."),
    ] + metadata_datas,
    hiddenimports=[
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
        "altair",
        "pydeck",
        "pyarrow",
        "pandas",
        "numpy",
        "plotly",
        "plotly.graph_objects",
        "plotly.express",
        "plotly.subplots",
        "plotly.figure_factory",
        "plotly.io",
        "httpx",
        "httpx._transports",
        "httpx._transports.default",
        "fastapi",
        "fastapi.middleware",
        "fastapi.middleware.cors",
        "uvicorn",
        "uvicorn.logging",
        "uvicorn.loops",
        "uvicorn.loops.auto",
        "uvicorn.loops.asyncio",
        "uvicorn.protocols",
        "uvicorn.protocols.http",
        "uvicorn.protocols.http.auto",
        "uvicorn.protocols.http.h11_impl",
        "uvicorn.protocols.websockets",
        "uvicorn.protocols.websockets.auto",
        "uvicorn.lifespan",
        "uvicorn.lifespan.on",
        "importlib.metadata",
        "importlib_metadata",
        "pkg_resources",
        "requests",
        "PIL",
        "PIL.Image",
        "attr",
        "attrs",
        "toolz",
        "jinja2",
        "jinja2.ext",
    ],
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
    console=True,          # keep console so users see logs
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=_icon(),
)
