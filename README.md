# Ember — local AI coding agent (one-time ~10 GB download)

Terminal agent that runs a coding LLM entirely on your PC. After the one-time download there is no
cloud, no API key, no per-token cost. It can read/write files, run commands, browse the web,
pull assets from GitHub, and create + push repos — like opencode.

## Install
**Arch Linux:** `unzip ember-master.zip && cd ember-master && ./install.sh`
**Windows (PowerShell):** `Expand-Archive ember-master.zip . ; cd ember-master ; .\install.ps1`

This installs the `ember` command, fetches the llama.cpp engine, and downloads the model
(Qwen2.5-Coder-14B-Instruct Q5_K_M, ~10.5 GB) into `~/.local/share/ember` (Windows: `%LOCALAPPDATA%\ember`).
The download resumes if interrupted. Needs Python 3.9+ (and git for GitHub features).

## Use
    ember                      # interactive chat in the current folder
    ember run "make a CLI todo app in python in ./todo"
    ember run -y "..."         # auto-approve writes/commands
    ember login                # save a GitHub token (for publishing / private repos)
    ember status | ember stop  # inspect / free the model from RAM-VRAM
    ember setup --preset lite  # 4.7 GB model for weaker machines

The model server stays alive in the background between sessions, so restarts are instant. `ember stop` frees memory.

## Speed / hardware
- Best: GPU with 12 GB+ VRAM (all layers offloaded). Windows works out of the box (Vulkan build). On Arch install `vulkan-icd-loader` + your GPU's Vulkan driver, or install `llama.cpp-cuda` / `llama.cpp-vulkan` from the AUR (Ember uses `llama-server` from PATH if present).
- CPU only: the 14B model will be slow (a few tokens/s). Use `--preset lite`, and set `"backend": "cpu"` in `config.json` if the GPU build fails.
- Less VRAM than 12 GB: lower `"ngl"` in `config.json` (partial offload) or use `lite`.
- Config: `~/.local/share/ember/config.json` (port, ngl, ctx, max_tokens, preset).

## Safety
File writes, shell commands, downloads and GitHub pushes ask for approval (y / n / a=always). `/auto` toggles.
The GitHub token is stored in config.json (chmod 600 on Linux).

## Notes
Models are pre-trained open weights; Ember does not train them. To swap models, edit `PRESETS` in `ember/config.py` (any chat GGUF).
