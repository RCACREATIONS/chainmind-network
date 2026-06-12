"""
ChainMind — hardware detection + compatible model catalog.
Used by the /system API endpoint.
"""

from __future__ import annotations

import os
import platform
import sys

MODEL_CATALOG = {
    "tiny": [
        {"name": "tinyllama:latest",     "label": "TinyLlama 1.1B",     "ram_gb": 1.0,  "disk_gb": 0.7,  "tags": ["chat"]},
        {"name": "gemma:2b",             "label": "Gemma 2B",            "ram_gb": 2.0,  "disk_gb": 1.5,  "tags": ["chat"]},
        {"name": "phi:latest",           "label": "Phi-2 2.7B",          "ram_gb": 2.5,  "disk_gb": 1.7,  "tags": ["code","chat"]},
        {"name": "orca-mini:3b",         "label": "Orca Mini 3B",        "ram_gb": 2.5,  "disk_gb": 1.9,  "tags": ["chat"]},
        {"name": "qwen:1.8b",            "label": "Qwen 1.8B",           "ram_gb": 2.0,  "disk_gb": 1.1,  "tags": ["chat"]},
    ],
    "small": [
        {"name": "llama3.2:3b",          "label": "Llama 3.2 3B",        "ram_gb": 3.5,  "disk_gb": 2.0,  "tags": ["chat"]},
        {"name": "mistral:7b",           "label": "Mistral 7B",          "ram_gb": 5.0,  "disk_gb": 4.1,  "tags": ["chat","code"]},
        {"name": "llama3:8b",            "label": "Llama 3 8B",          "ram_gb": 6.0,  "disk_gb": 4.7,  "tags": ["chat"]},
        {"name": "gemma2:9b",            "label": "Gemma 2 9B",          "ram_gb": 6.0,  "disk_gb": 5.5,  "tags": ["chat"]},
        {"name": "phi3:mini",            "label": "Phi-3 Mini 3.8B",     "ram_gb": 3.5,  "disk_gb": 2.3,  "tags": ["code","chat"]},
        {"name": "codellama:7b",         "label": "CodeLlama 7B",        "ram_gb": 5.0,  "disk_gb": 3.8,  "tags": ["code"]},
        {"name": "deepseek-coder:6.7b",  "label": "DeepSeek Coder 6.7B", "ram_gb": 5.0,  "disk_gb": 3.8,  "tags": ["code"]},
    ],
    "medium": [
        {"name": "llama3:70b-q4",        "label": "Llama 3 70B (Q4)",    "ram_gb": 16.0, "disk_gb": 40.0, "tags": ["chat"]},
        {"name": "mixtral:8x7b",         "label": "Mixtral 8×7B",        "ram_gb": 26.0, "disk_gb": 26.0, "tags": ["chat","code"]},
        {"name": "codellama:34b",        "label": "CodeLlama 34B",       "ram_gb": 20.0, "disk_gb": 19.0, "tags": ["code"]},
        {"name": "gemma2:27b",           "label": "Gemma 2 27B",         "ram_gb": 18.0, "disk_gb": 16.0, "tags": ["chat"]},
    ],
    "large": [
        {"name": "llama3:70b",           "label": "Llama 3 70B",         "ram_gb": 48.0, "disk_gb": 40.0, "tags": ["chat"]},
        {"name": "mixtral:8x22b",        "label": "Mixtral 8×22B",       "ram_gb": 96.0, "disk_gb": 87.0, "tags": ["chat","code"]},
        {"name": "llama3.1:405b-q4",     "label": "Llama 3.1 405B (Q4)", "ram_gb": 128.0,"disk_gb": 230.0,"tags": ["chat"]},
    ],
}

TIER_THRESHOLDS = [
    ("nano",       0),
    ("micro",      4),
    ("standard",   16),
    ("pro",        64),
    ("enterprise", 128),
]


def get_hardware() -> dict:
    """Detect hardware specs. Returns safe defaults on failure."""
    hw: dict = {
        "os":               platform.system(),
        "arch":             platform.machine(),
        "python":           platform.python_version(),
        "cpu_cores":        os.cpu_count() or 1,
        "has_gpu":          False,
        "gpu_name":         "",
        "gpu_vram_gb":      0.0,
        "ram_gb":           4.0,
        "ram_available_gb": None,
        "disk_free_gb":     10.0,
    }

    # RAM
    try:
        import psutil
        vm = psutil.virtual_memory()
        hw["ram_gb"]           = round(vm.total / 1024**3, 1)
        hw["ram_available_gb"] = round(vm.available / 1024**3, 1)
        disk = psutil.disk_usage(os.path.expanduser("~"))
        hw["disk_free_gb"] = round(disk.free / 1024**3, 1)
    except Exception:
        pass

    # GPU (optional — don't crash if unavailable)
    try:
        import subprocess
        result = subprocess.run(
            ["nvidia-smi", "--query-gpu=name,memory.total",
             "--format=csv,noheader,nounits"],
            capture_output=True, text=True, timeout=5
        )
        if result.returncode == 0 and result.stdout.strip():
            parts = result.stdout.strip().split(",")
            hw["has_gpu"]    = True
            hw["gpu_name"]   = parts[0].strip()
            hw["gpu_vram_gb"]= round(float(parts[1].strip()) / 1024, 1)
    except Exception:
        pass

    return hw


def get_compatible_models(hw: dict) -> dict:
    """
    Return the model catalog annotated with fits/reason for each model
    based on available RAM and free disk space.
    """
    ram_gb   = hw.get("ram_gb", 4.0)
    disk_gb  = hw.get("disk_free_gb", 10.0)
    vram_gb  = hw.get("gpu_vram_gb", 0.0)
    has_gpu  = hw.get("has_gpu", False)

    result: dict[str, list] = {}
    for group, models in MODEL_CATALOG.items():
        annotated = []
        for m in models:
            need_ram  = m["ram_gb"]
            need_disk = m["disk_gb"]

            # GPU-enabled: use VRAM as effective RAM for inference
            effective_ram = max(ram_gb, vram_gb) if has_gpu else ram_gb

            if effective_ram < need_ram:
                reason = f"Needs {need_ram}GB RAM (you have {ram_gb}GB)"
                fits   = False
            elif disk_gb < need_disk:
                reason = f"Needs {need_disk}GB disk (you have {disk_gb}GB free)"
                fits   = False
            else:
                reason = ""
                fits   = True

            annotated.append({**m, "fits": fits, "reason": reason})
        result[group] = annotated
    return result


def get_recommended_tier(hw: dict) -> str:
    """Return the tier name that best matches this machine's RAM."""
    ram = hw.get("ram_gb", 0)
    has_gpu = hw.get("has_gpu", False)
    vram    = hw.get("gpu_vram_gb", 0)
    effective = max(ram, vram) if has_gpu else ram

    tier = "nano"
    for name, threshold in TIER_THRESHOLDS:
        if effective >= threshold:
            tier = name
    return tier


def get_system_info() -> dict:
    """Full system snapshot — call this from the /system endpoint."""
    hw    = get_hardware()
    compat = get_compatible_models(hw)
    tier   = get_recommended_tier(hw)
    return {
        "hardware":          hw,
        "compatible_models": compat,
        "recommended_tier":  tier,
    }
