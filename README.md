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
- Less VRAM than 12 GB: lower `"gpu_layers"` in `config.json` (partial offload) or use `lite`.
- Config: `~/.local/share/ember/config.json` (port, gpu_layers, ctx, max_tokens, preset).

## Safety
File writes, shell commands, downloads and GitHub pushes ask for approval (y / n / a=always). `/auto` toggles.
The GitHub token is stored in config.json (chmod 600 on Linux).

## Notes
Models are pre-trained open weights; Ember does not train them. To swap models, edit `PRESETS` in `ember/config.py` (any chat GGUF).

## Running Ember
Open a terminal, go to the folder you want it to work in, and run `ember`:

    cd ~/some-project
    ember

Type what you want at the prompt, for example `make a snake game in python in ./snake`.
Ctrl+C stops an answer, Ctrl+D (or `/exit`) quits. The first launch after boot takes a moment
while the model loads; after that it stays loaded in the background, so later launches are instant.
Run `ember stop` to free the memory (for example before gaming).

Other commands: `ember run "prompt"` (one task, then exit), `ember status`, `ember login`, and `/help` inside the chat.

## Troubleshooting

### `ember: command not found`
The installer puts the command in `~/.local/bin`, which may not be on your PATH.

    echo "export PATH=\"\$HOME/.local/bin:\$PATH\"" >> ~/.zshrc   # use ~/.bashrc for bash
    source ~/.zshrc

For fish: `fish_add_path ~/.local/bin`. On Windows, close the terminal and open a new one
(the installer adds the folder to PATH, which only applies to new windows).

### `llama-server exited (1)` / `ErrorOutOfDeviceMemory`
Your GPU ran out of memory loading the model. Fixes, in order:

1. Make sure you have the latest version (older versions forced every layer onto the GPU).
   Reinstall from the repo: `./install.sh` (the model is not downloaded again).
2. Close GPU-hungry apps (browser, games) and try again. Ember lets llama.cpp split the model
   between GPU and RAM automatically, so more free VRAM means faster answers.
3. Set the GPU layer count by hand in `~/.local/share/ember/config.json` (Windows: `%LOCALAPPDATA%\ember\config.json`),
   for example `"gpu_layers": 30`. Lower numbers use less VRAM.
4. Switch to the smaller 4.7 GB model: `ember setup --preset lite`.
5. No usable GPU or Vulkan driver? Set `"backend": "cpu"` in the same file (slow with the 14B model; use `lite`).
   On Arch, GPU support needs `vulkan-icd-loader` plus `vulkan-radeon`, `nvidia-utils` or `vulkan-intel`.

The full log is in `~/.local/share/ember/server.log`.
