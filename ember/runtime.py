"""Downloads the model + llama.cpp once, and keeps a local inference server alive."""
import os
import shutil
import signal
import subprocess
import tarfile
import tempfile
import time
import zipfile
from pathlib import Path

import httpx
from rich.progress import (BarColumn, DownloadColumn, Progress, TextColumn,
                           TimeRemainingColumn, TransferSpeedColumn)

from . import config

EXE = "llama-server.exe" if os.name == "nt" else "llama-server"


def model_path(cfg) -> Path:
    return config.data_dir() / "models" / config.preset(cfg)["file"]


def _progress():
    return Progress(TextColumn("[cyan]{task.description}"), BarColumn(), DownloadColumn(),
                    TransferSpeedColumn(), TimeRemainingColumn())


def _download(url, dest: Path, label, console, headers=None):
    """Resumable download with retries."""
    part = dest.with_suffix(dest.suffix + ".part")
    dest.parent.mkdir(parents=True, exist_ok=True)
    for attempt in range(40):
        have = part.stat().st_size if part.exists() else 0
        h = dict(headers or {})
        if have:
            h["Range"] = f"bytes={have}-"
        try:
            with httpx.stream("GET", url, headers=h, follow_redirects=True, timeout=30) as r:
                if r.status_code == 416:
                    break
                r.raise_for_status()
                if r.status_code != 206:
                    have = 0
                total = have + int(r.headers.get("content-length") or 0)
                with _progress() as prog, open(part, "ab" if have else "wb") as f:
                    t = prog.add_task(label, total=total or None, completed=have)
                    for chunk in r.iter_bytes(1 << 20):
                        f.write(chunk)
                        prog.update(t, advance=len(chunk))
            break
        except (httpx.TransportError, httpx.RemoteProtocolError) as e:
            console.print(f"[yellow]connection issue ({type(e).__name__}); resuming…[/]")
            time.sleep(min(2 + attempt, 15))
    else:
        raise RuntimeError("download failed repeatedly; run `ember setup` again to resume")
    os.replace(part, dest)


def ensure_model(cfg, console) -> Path:
    dest = model_path(cfg)
    if dest.exists():
        return dest
    p = config.preset(cfg)
    console.print(f"[bold]Downloading model[/] {p['label']} — one time only")
    _download(f"https://huggingface.co/{p['repo']}/resolve/main/{p['file']}", dest, "model", console)
    return dest


def find_server_bin():
    w = shutil.which("llama-server")
    if w:
        return Path(w)
    root = config.data_dir() / "llama.cpp"
    if root.exists():
        for p in root.rglob(EXE):
            return p
    return None


def _pick_asset(assets, cfg):
    plat = "win" if os.name == "nt" else "ubuntu"
    bad = ("cudart", "cuda", "rocm", "hip", "sycl", "openvino", "arm", "opencl", "kleidi", "s390x")

    def ok(a):
        n = a["name"].lower()
        return (n.endswith((".zip", ".tar.gz")) and f"bin-{plat}" in n and "x64" in n
                and not any(b in n for b in bad))

    cands = [a for a in assets if ok(a)]
    vul = [a for a in cands if "vulkan" in a["name"].lower()]
    non = [a for a in cands if a not in vul]
    pick = (vul or non) if cfg["backend"] != "cpu" else (non or vul)
    return pick[0] if pick else None


def install_llama_cpp(cfg, console) -> Path:
    console.print("[bold]Fetching llama.cpp inference engine[/] (~30 MB) — one time only")
    hdr = {"User-Agent": "ember-agent", "Accept": "application/vnd.github+json"}
    r = httpx.get("https://api.github.com/repos/ggml-org/llama.cpp/releases?per_page=20",
                  headers=hdr, timeout=30, follow_redirects=True)
    r.raise_for_status()
    a = None
    for rel in r.json():
        if rel.get("draft"):
            continue
        a = _pick_asset(rel.get("assets", []), cfg)
        if a:  # newest release that actually has a usable build attached
            break
    if not a:
        raise RuntimeError(
            "Couldn't find a prebuilt llama.cpp for your system. Download a "
            "'bin-ubuntu-vulkan-x64' (Linux) or 'bin-win-vulkan-x64' (Windows) archive from "
            "https://github.com/ggml-org/llama.cpp/releases, extract it into "
            f"{config.data_dir() / 'llama.cpp'} and run `ember setup` again.")
    root = config.data_dir() / "llama.cpp"
    shutil.rmtree(root, ignore_errors=True)
    root.mkdir(parents=True)
    tmp = Path(tempfile.mkdtemp()) / a["name"]
    _download(a["browser_download_url"], tmp, a["name"], console)
    if a["name"].endswith(".zip"):
        zipfile.ZipFile(tmp).extractall(root)
    else:
        with tarfile.open(tmp) as t:
            try:
                t.extractall(root, filter="data")
            except TypeError:
                t.extractall(root)
    tmp.unlink(missing_ok=True)
    binp = next(root.rglob(EXE), None)
    if not binp:
        raise RuntimeError("llama-server not found in downloaded archive")
    if os.name != "nt":
        for f in binp.parent.iterdir():
            if f.is_file() and not f.suffix:
                f.chmod(0o755)
    return binp


def server_state(port):
    try:
        r = httpx.get(f"http://127.0.0.1:{port}/health", timeout=1.5)
    except httpx.HTTPError:
        return None
    return "ready" if r.status_code == 200 else "loading" if r.status_code == 503 else None


def ensure_server(cfg, console):
    port = cfg["port"]
    st = server_state(port)
    if st == "ready":
        return
    proc = None
    log = config.data_dir() / "server.log"
    if st is None:
        binp = find_server_bin() or install_llama_cpp(cfg, console)
        model = ensure_model(cfg, console)
        p = config.preset(cfg)
        cmd = [str(binp), "-m", str(model), "--host", "127.0.0.1", "--port", str(port),
               "-c", str(p["ctx"]), "-ngl", str(cfg["ngl"]), "-np", "1"]
        env = dict(os.environ)
        if os.name != "nt":
            env["LD_LIBRARY_PATH"] = str(binp.parent) + os.pathsep + env.get("LD_LIBRARY_PATH", "")
        kw = {}
        if os.name == "nt":
            kw["creationflags"] = 0x00000008 | 0x00000200 | 0x08000000  # detached, new group, no window
        else:
            kw["start_new_session"] = True
        with open(log, "ab") as lf:
            proc = subprocess.Popen(cmd, stdout=lf, stderr=lf, stdin=subprocess.DEVNULL,
                                    env=env, cwd=str(binp.parent), **kw)
        (config.data_dir() / "server.pid").write_text(str(proc.pid))
    with console.status("[dim]loading model into memory…[/]"):
        t0 = time.time()
        while time.time() - t0 < 900:
            if server_state(port) == "ready":
                return
            if proc and proc.poll() is not None:
                tail = "\n".join(log.read_text("utf-8", "replace").splitlines()[-15:])
                raise RuntimeError(f"llama-server exited ({proc.returncode}). Log: {log}\n{tail}\n"
                                   "Tip: set \"backend\": \"cpu\" or lower \"ngl\" in config.json, "
                                   "or use `ember setup --preset lite`.")
            time.sleep(0.5)
    raise RuntimeError("timed out waiting for model to load")


def stop_server() -> bool:
    pf = config.data_dir() / "server.pid"
    if not pf.exists():
        return False
    pid = int(pf.read_text().strip() or 0)
    try:
        if os.name == "nt":
            subprocess.run(["taskkill", "/PID", str(pid), "/F", "/T"], capture_output=True)
        else:
            os.kill(pid, signal.SIGTERM)
    except Exception:
        return False
    pf.unlink(missing_ok=True)
    return True
