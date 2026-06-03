"""System hardware detection — RAM, CPU, GPU, model compatibility."""

from __future__ import annotations

import platform
import subprocess
import sys
from typing import Any


def get_system_info() -> dict[str, Any]:
    """Detect RAM, CPU, GPU and return hardware profile."""
    info: dict[str, Any] = {
        "os": platform.system(),
        "arch": platform.machine(),
        "python": sys.version.split()[0],
        "cpu_cores": 1,
        "ram_gb": 4.0,
        "has_gpu": False,
        "gpu_vram_gb": 0.0,
        "gpu_name": "",
        "disk_free_gb": 10.0,
    }

    # ── RAM / CPU / Disk via psutil ───────────────────────────────────────────
    # Catch ALL exceptions — in a PyInstaller frozen bundle psutil can fail
    # in ways other than ImportError (missing .pyd, permission errors, etc).
    try:
        import psutil

        # RAM
        vm = psutil.virtual_memory()
        info["ram_gb"]           = round(vm.total    / (1024 ** 3), 1)
        info["ram_available_gb"] = round(vm.available / (1024 ** 3), 1)

        # CPU
        info["cpu_cores"]   = psutil.cpu_count(logical=False) or 1
        info["cpu_threads"] = psutil.cpu_count(logical=True)  or 1
        info["cpu_freq_mhz"] = (
            round(psutil.cpu_freq().current) if psutil.cpu_freq() else None
        )

        # Disk — try the install dir first, fall back to home, then root
        import os as _os
        for _path in [".", _os.path.expanduser("~"), "/"]:
            try:
                du = psutil.disk_usage(_path)
                info["disk_free_gb"] = round(du.free / (1024 ** 3), 1)
                break
            except Exception:
                continue

    except Exception:
        # psutil unavailable or failed — defaults stay in place
        pass

    # ── GPU — NVIDIA ──────────────────────────────────────────────────────────
    try:
        result = subprocess.run(
            ["nvidia-smi", "--query-gpu=name,memory.total",
             "--format=csv,noheader,nounits"],
            capture_output=True, text=True, timeout=5,
        )
        if result.returncode == 0 and result.stdout.strip():
            lines = result.stdout.strip().splitlines()
            parts = lines[0].split(",")
            info["has_gpu"]      = True
            info["gpu_name"]     = parts[0].strip()
            info["gpu_vram_gb"]  = round(int(parts[1].strip()) / 1024, 1)
    except Exception:
        pass

    # ── GPU — AMD (ROCm) ──────────────────────────────────────────────────────
    if not info["has_gpu"]:
        try:
            result = subprocess.run(
                ["rocm-smi", "--showmeminfo", "vram", "--csv"],
                capture_output=True, text=True, timeout=5,
            )
            if result.returncode == 0:
                info["has_gpu"]  = True
                info["gpu_name"] = "AMD GPU (ROCm)"
        except Exception:
            pass

    return info


def get_tier_for_system(info: dict[str, Any]) -> str:
    """Determine IntelliChain node tier from hardware."""
    ram      = info.get("ram_gb", 0)
    gpu_vram = info.get("gpu_vram_gb", 0)
    cores    = info.get("cpu_cores", 1)

    if gpu_vram >= 24 or (ram >= 64 and cores >= 16):
        return "enterprise"
    if gpu_vram >= 8  or (ram >= 32 and cores >= 8):
        return "pro"
    if gpu_vram >= 4  or (ram >= 16 and cores >= 4):
        return "standard"
    if ram >= 8 or cores >= 4:
        return "micro"
    return "nano"


def filter_models_for_system(catalog: dict, info: dict) -> dict:
    """Return models from the catalog annotated with fits/reason for this system."""
    ram       = info.get("ram_gb", 4.0)
    gpu_vram  = info.get("gpu_vram_gb", 0.0)
    # Use VRAM if a GPU is present, otherwise full system RAM.
    # (The old 60 % headroom was far too aggressive.)
    effective = gpu_vram if gpu_vram > 0 else ram
    disk_free = info.get("disk_free_gb", 10.0)

    compatible: dict = {}
    for tier, models in catalog.items():
        annotated = []
        for m in models:
            need_ram  = m.get("ram_gb",  2.0)
            need_disk = m.get("disk_gb", need_ram * 1.2)
            if need_ram <= effective and need_disk <= disk_free:
                annotated.append({**m, "fits": True})
            else:
                if need_ram > effective:
                    reason = f"Needs {need_ram}GB RAM (you have {effective:.1f}GB)"
                else:
                    reason = f"Needs {need_disk}GB disk (you have {disk_free:.1f}GB free)"
                annotated.append({**m, "fits": False, "reason": reason})
        if annotated:
            compatible[tier] = annotated
    return compatible


def system_summary(info: dict) -> str:
    """Human-readable system summary."""
    gpu = (
        f"GPU: {info['gpu_name']} {info['gpu_vram_gb']}GB VRAM"
        if info.get("has_gpu") else "No GPU (CPU-only)"
    )
    return (
        f"OS: {info['os']} {info['arch']} | "
        f"RAM: {info.get('ram_gb','?')}GB | "
        f"CPU: {info.get('cpu_cores','?')} cores | "
        f"{gpu} | "
        f"Disk free: {info.get('disk_free_gb','?')}GB"
    )
