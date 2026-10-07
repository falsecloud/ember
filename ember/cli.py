import argparse
import getpass
import os
import sys

import httpx
from rich.console import Console

from . import __version__, config, runtime, tools
from .agent import Agent

HELP = """[bold]/help[/]  this help      [bold]/clear[/]  new conversation     [bold]/auto[/]  toggle auto-approve
[bold]/cd PATH[/]  change folder      [bold]/login[/]  save GitHub token    [bold]/exit[/]  quit
Just describe what you want. Examples:
  [dim]make a flask todo app in ./todo and run it[/]
  [dim]read ~/notes/ideas.txt and summarize it[/]
  [dim]clone someuser/somerepo and copy its logo.png into ./assets[/]
  [dim]publish this folder to GitHub as my-project (private)[/]"""


def login(cfg, console):
    tok = getpass.getpass("GitHub token (classic PAT with `repo` scope, or fine-grained with Contents+Administration): ").strip()
    if not tok:
        return
    tools.STATE["token"] = tok
    r = httpx.get("https://api.github.com/user", headers=tools._gh(), timeout=20)
    if r.status_code != 200:
        console.print(f"[red]GitHub rejected that token ({r.status_code})[/]")
        tools.STATE["token"] = cfg.get("github_token", "")
        return
    cfg["github_token"] = tok
    config.save(cfg)
    console.print(f"[green]logged in as {r.json()['login']}[/]")


def chat(cfg, console, auto):
    from prompt_toolkit import PromptSession
    from prompt_toolkit.history import FileHistory
    runtime.ensure_server(cfg, console)
    agent = Agent(cfg, console, auto)
    console.print(f"[bold cyan]ember[/] [dim]· {config.preset(cfg)['label']} · {os.getcwd()}[/]")
    console.print("[dim]/help · ctrl+c stops generation · ctrl+d exits[/]\n")
    session = PromptSession(history=FileHistory(str(config.data_dir() / "history")),
                            message=[("ansicyan bold", "❯ ")])
    while True:
        try:
            line = session.prompt().strip()
        except EOFError:
            break
        except KeyboardInterrupt:
            continue
        if not line:
            continue
        if line.startswith("/"):
            cmd, _, arg = line[1:].partition(" ")
            if cmd in ("exit", "quit", "q"):
                break
            elif cmd == "help":
                console.print(HELP)
            elif cmd == "clear":
                agent.reset()
                console.print("[dim]cleared[/]")
            elif cmd == "auto":
                agent.auto = not agent.auto
                console.print(f"[dim]auto-approve {'ON' if agent.auto else 'off'}[/]")
            elif cmd == "cd":
                try:
                    os.chdir(os.path.expanduser(arg.strip() or "~"))
                    agent.reset()
                    console.print(f"[dim]{os.getcwd()}[/]")
                except OSError as e:
                    console.print(f"[red]{e}[/]")
            elif cmd == "login":
                login(cfg, console)
                agent.cfg = cfg
            else:
                console.print("[dim]unknown command; /help[/]")
            continue
        try:
            agent.turn(line)
        except httpx.HTTPError as e:
            console.print(f"[red]model server error:[/] {e}")
        except KeyboardInterrupt:
            console.print("[dim]· interrupted[/]")
        console.print()


def main(argv=None):
    for s in (sys.stdout, sys.stderr):
        try:
            s.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass
    ap = argparse.ArgumentParser(prog="ember", description="Local AI coding agent")
    ap.add_argument("cmd", nargs="?", default="chat", choices=["chat", "setup", "run", "stop", "login", "status"])
    ap.add_argument("prompt", nargs="*")
    ap.add_argument("--preset", choices=list(config.PRESETS), help="max (~10GB) or lite (~5GB); remembered")
    ap.add_argument("-C", "--cwd", help="working folder")
    ap.add_argument("-y", "--yes", action="store_true", help="auto-approve file writes / commands")
    ap.add_argument("--version", action="version", version=__version__)
    a = ap.parse_intermixed_args(argv)
    console = Console()
    cfg = config.load()
    if a.preset:
        cfg["preset"] = a.preset
        config.save(cfg)
    if a.cwd:
        os.chdir(os.path.expanduser(a.cwd))
    try:
        if a.cmd == "setup":
            runtime.find_server_bin() or runtime.install_llama_cpp(cfg, console)
            runtime.ensure_model(cfg, console)
            console.print("[green]✓ ready.[/] Run [bold]ember[/] in any folder.")
        elif a.cmd == "stop":
            console.print("stopped" if runtime.stop_server() else "no server running")
        elif a.cmd == "login":
            login(cfg, console)
        elif a.cmd == "status":
            mp = runtime.model_path(cfg)
            console.print(f"preset: {config.preset(cfg)['label']}\nmodel:  {mp} ({'present' if mp.exists() else 'missing'})\n"
                          f"engine: {runtime.find_server_bin() or 'not installed'}\nserver: {runtime.server_state(cfg['port']) or 'stopped'}\n"
                          f"github: {'token saved' if cfg.get('github_token') else 'not logged in'}\ndata:   {config.data_dir()}")
        elif a.cmd == "run":
            if not a.prompt:
                ap.error("usage: ember run \"your prompt\"")
            runtime.ensure_server(cfg, console)
            Agent(cfg, console, a.yes).turn(" ".join(a.prompt))
        else:
            chat(cfg, console, a.yes)
    except KeyboardInterrupt:
        pass
    except Exception as e:
        console.print(f"[red]error:[/] {e}")
        sys.exit(1)
