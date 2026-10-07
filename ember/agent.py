import difflib
import json
import os
import platform
import re

from rich.text import Text

from . import config, llm, tools

FENCE = re.compile(r"```tool\s*\n(.*?)\n?```", re.S)
MAX_STEPS = 30


def system_prompt():
    return f"""You are Ember, a fast, precise coding agent running locally on the user's own computer ({platform.system()}, working directory: {os.getcwd()}). You can read/write files, run commands, browse the web, and use GitHub through tools.

To use a tool, output EXACTLY one block like this and then stop (you will receive the result):
```tool
{{"name": "read_file", "args": {{"path": "main.py"}}}}
```
The block body must be valid JSON (escape newlines as \\n and quotes as \\"). One tool call per reply.

Tools:
{tools.DOCS}

Rules:
- Inspect before changing: list_dir / read_file first. Never invent file contents, paths, or URLs; verify with tools.
- For new projects, write complete, working, runnable files (with a short README and dependency file when relevant). Keep each file reasonably small; split big programs into modules.
- Prefer edit_file for small changes. After writing code, run it or its tests with run_shell when practical, and fix errors.
- Be concise. When the task is done, reply with a short summary and NO tool block."""


def est_tokens(msgs):
    return sum(len(m["content"]) for m in msgs) // 3


def compact(msgs, budget):
    while est_tokens(msgs) > budget:
        for m in msgs[1:-2]:
            if len(m["content"]) > 500:
                m["content"] = m["content"][:250] + "\n…[trimmed]…\n" + m["content"][-150:]
                break
        else:
            if len(msgs) > 4:
                del msgs[1:3]
            else:
                break


def parse_call(text):
    m = FENCE.search(text)
    if not m:
        return None, "Your tool block was incomplete or malformed. Emit one complete ```tool block with valid JSON (split large files into smaller ones)."
    try:
        c = json.loads(m.group(1), strict=False)
        if not isinstance(c, dict) or "name" not in c:
            raise ValueError("missing name")
        if not isinstance(c.get("args", {}), dict):
            raise ValueError("args must be an object")
        return c, None
    except Exception as e:
        return None, f"Invalid JSON in tool block ({e}). Re-send the call with valid JSON."


def summarize(args):
    parts = []
    for k, v in args.items():
        s = str(v).replace("\n", "⏎")
        parts.append(f"{k}={s[:60] + '…' if len(s) > 60 else s}")
    return "  ".join(parts)


class Agent:
    def __init__(self, cfg, console, auto=False):
        self.cfg, self.c, self.auto = cfg, console, auto
        tools.STATE["token"] = cfg.get("github_token") or os.environ.get("GITHUB_TOKEN", "")
        self.messages = [{"role": "system", "content": system_prompt()}]

    def reset(self):
        self.messages = [{"role": "system", "content": system_prompt()}]

    # ---- one user request -> loop of model/tool steps
    def turn(self, user_text):
        self.messages.append({"role": "user", "content": user_text})
        ctx = config.preset(self.cfg)["ctx"]
        for _ in range(MAX_STEPS):
            compact(self.messages, ctx - int(self.cfg.get("max_tokens", 3072)) - 200)
            text, interrupted = self._stream()
            self.messages.append({"role": "assistant", "content": text or "(no output)"})
            if interrupted:
                self.c.print("[dim]· interrupted[/]")
                return
            if "```tool" not in text:
                return
            call, err = parse_call(text)
            result = err if err else self._run(call)
            self.messages.append({"role": "user", "content": f"Tool result:\n{result}"})
        self.c.print("[yellow]step limit reached[/]")

    def _stream(self):
        acc, shown, started, interrupted = "", 0, False, False
        status = self.c.status("[dim]thinking[/]", spinner="dots")
        status.start()
        gen = llm.stream_chat(self.cfg, self.messages)
        try:
            for d in gen:
                if not started:
                    status.stop()
                    started = True
                acc += d
                i = acc.find("```tool")
                limit = i if i != -1 else max(shown, len(acc) - 6)
                if limit > shown:
                    self.c.print(acc[shown:limit], end="", markup=False, highlight=False)
                    shown = limit
                if i != -1 and FENCE.search(acc):
                    break
        except KeyboardInterrupt:
            interrupted = True
        finally:
            status.stop()
            gen.close()
        i = acc.find("```tool")
        if i == -1 and len(acc) > shown:
            self.c.print(acc[shown:], end="", markup=False, highlight=False)
        if shown or i == -1:
            self.c.print()
        m = FENCE.search(acc)
        if m:
            acc = acc[: m.end()]
        return acc, interrupted

    def _run(self, call):
        name, args = call["name"], call.get("args") or {}
        self.c.print(Text.assemble(("● ", "cyan"), (name, "bold"), ("  " + summarize(args), "dim")))
        if tools.needs_confirm(name, args) and not self.auto and not self._confirm(name, args):
            return "User denied this action. Ask what they'd prefer."
        out = tools.call(name, args)
        lines = out.splitlines() or [""]
        for l in lines[:4]:
            self.c.print(Text("  " + l[:140], style="dim"))
        if len(lines) > 4:
            self.c.print(Text(f"  … {len(lines) - 4} more lines", style="dim"))
        return out

    def _confirm(self, name, args):
        if name == "edit_file":
            d = difflib.unified_diff(str(args.get("old", "")).splitlines(), str(args.get("new", "")).splitlines(), lineterm="", n=0)
            for l in list(d)[2:22]:
                self.c.print(Text("  " + l[:140], style="red" if l.startswith("-") else "green" if l.startswith("+") else "dim"))
        elif name == "write_file":
            self.c.print(Text(f"  {len(str(args.get('content', '')).splitlines())} lines → {args.get('path')}", style="dim"))
        elif name == "run_shell":
            self.c.print(Text("  $ " + str(args.get("command")), style="yellow"))
        try:
            a = self.c.input("[yellow]  allow?[/] [dim](y / n / a = always this session)[/] ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            return False
        if a == "a":
            self.auto = True
        return a in ("y", "yes", "a", "")
