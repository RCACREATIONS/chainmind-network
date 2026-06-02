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

    # ── RAM ──────────────────────────────────────────────────────────────────
    try:
        import psutil
        vm = psutil.virtual_memory()
        info["ram_gb"] = round(vm.total / (1024 ** 3), 1)
        info["ram_available_gb"] = round(vm.available / (1024 ** 3), 1)
        info["cpu_cores"] = psutil.cpu_count(logical=False) or 1
        info["cpu_threads"] = psutil.cpu_count(logical=True) or 1

        # Disk space (where we're running from)
        du = psutil.disk_usage(".")
        info["disk_free_gb"] = round(du.free / (1024 ** 3), 1)
    except ImportError:
        pass

    # ── GPU — NVIDIA ──────────────────────────────────────────────────────────
    try:
        result = subprocess.run(
            ["nvidia-smi", "--query-gpu=name,memory.total", "--format=csv,noheader,nounits"],
            capture_output=True, text=True, timeout=5,
        )
        if result.returncode == 0 and result.stdout.strip():
            lines = result.stdout.strip().splitlines()
            parts = lines[0].split(",")
            info["has_gpu"] = True
            info["gpu_name"] = parts[0].strip()
            info["gpu_vram_gb"] = round(int(parts[1].strip()) / 1024, 1)
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
                info["has_gpu"] = True
                info["gpu_name"] = "AMD GPU (ROCm)"
        except Exception:
            pass

    return info


def get_tier_for_system(info: dict[str, Any]) -> str:
    """Determine IntelliChain node tier from hardware."""
    ram = info.get("ram_gb", 0)
    gpu_vram = info.get("gpu_vram_gb", 0)
    cores = info.get("cpu_cores", 1)

    if gpu_vram >= 24 or (ram >= 64 and cores >= 16):
        return "enterprise"
    if gpu_vram >= 8 or (ram >= 32 and cores >= 8):
        return "pro"
    if gpu_vram >= 4 or (ram >= 16 and cores >= 4):
        return "standard"
    if ram >= 8 or cores >= 4:
        return "micro"
    return "nano"


def filter_models_for_system(catalog: dict, info: dict) -> dict:
    """Return only models that fit in the system's available RAM."""
    ram = info.get("ram_gb", 4.0)
    gpu_vram = info.get("gpu_vram_gb", 0.0)
    # Effective memory = GPU VRAM if present, else 60% of RAM (leave headroom)
    effective_gb = gpu_vram if gpu_vram > 0 else ram * 0.6
    disk_free = info.get("disk_free_gb", 10.0)

    compatible: dict = {}
    for size_tier, models in catalog.items():
        good = []
        for m in models:
            model_ram = m.get("ram_gb", 2.0)
            model_disk = m.get("disk_gb", model_ram * 1.2)
            if model_ram <= effective_gb and model_disk <= disk_free:
                good.append({**m, "fits": True})
            else:
                # Still show it but mark as incompatible
                good.append({**m, "fits": False,
                             "reason": f"Needs {model_ram}GB RAM, you have {effective_gb:.1f}GB available"})
        if good:
            compatible[size_tier] = good
    return compatible


def system_summary(info: dict) -> str:
    """Human-readable system summary."""
    gpu = f"GPU: {info['gpu_name']} {info['gpu_vram_gb']}GB VRAM" if info.get("has_gpu") else "No GPU (CPU-only)"
    return (
        f"OS: {info['os']} {info['arch']} | "
        f"RAM: {info.get('ram_gb','?')}GB | "
        f"CPU: {info.get('cpu_cores','?')} cores | "
        f"{gpu} | "
        f"Disk free: {info.get('disk_free_gb','?')}GB"
    )
