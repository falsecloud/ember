import json
import os
from pathlib import Path


def data_dir() -> Path:
    if os.name == "nt":
        base = Path(os.environ.get("LOCALAPPDATA") or Path.home() / "AppData" / "Local")
    else:
        base = Path(os.environ.get("XDG_DATA_HOME") or Path.home() / ".local" / "share")
    d = base / "ember"
    d.mkdir(parents=True, exist_ok=True)
    return d


# Pre-trained open-weights models (GGUF). "max" is sized to use ~10 GB.
PRESETS = {
    "max": {
        "repo": "bartowski/Qwen2.5-Coder-14B-Instruct-GGUF",
        "file": "Qwen2.5-Coder-14B-Instruct-Q5_K_M.gguf",
        "ctx": 12288,
        "label": "Qwen2.5-Coder 14B Q5_K_M (~10.5 GB)",
    },
    "lite": {
        "repo": "bartowski/Qwen2.5-Coder-7B-Instruct-GGUF",
        "file": "Qwen2.5-Coder-7B-Instruct-Q4_K_M.gguf",
        "ctx": 16384,
        "label": "Qwen2.5-Coder 7B Q4_K_M (~4.7 GB)",
    },
}

DEFAULTS = {
    "preset": "max",
    "port": 8484,
    "backend": "auto",   # auto/vulkan = GPU build, cpu = CPU-only build
    "gpu_layers": "auto",  # "auto" fits the model to free VRAM; or a number
    "ctx": 0,            # 0 = preset default
    "github_token": "",
    "max_tokens": 3072,
}


def _path() -> Path:
    return data_dir() / "config.json"


def load() -> dict:
    cfg = dict(DEFAULTS)
    try:
        cfg.update(json.loads(_path().read_text("utf-8")))
    except Exception:
        pass
    return cfg


def save(cfg: dict) -> None:
    p = _path()
    p.write_text(json.dumps(cfg, indent=2), "utf-8")
    if os.name != "nt":
        os.chmod(p, 0o600)


def preset(cfg: dict) -> dict:
    p = dict(PRESETS[cfg["preset"]])
    if cfg.get("ctx"):
        p["ctx"] = int(cfg["ctx"])
    return p
