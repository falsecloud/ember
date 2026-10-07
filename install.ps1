# Ember installer for Windows (PowerShell). Usage: .\install.ps1   (or: .\install.ps1 -Preset lite)
param([string]$Preset = "")
$ErrorActionPreference = "Stop"
$here = Split-Path -Parent $MyInvocation.MyCommand.Path
$data = Join-Path $env:LOCALAPPDATA "ember"
$bin  = Join-Path $data "bin"
New-Item -ItemType Directory -Force $data, $bin | Out-Null
$py = if (Get-Command python -ErrorAction SilentlyContinue) { "python" } elseif (Get-Command py -ErrorAction SilentlyContinue) { "py" } else { throw "Python 3.9+ not found. Run: winget install Python.Python.3.12" }
if (-not (Get-Command git -ErrorAction SilentlyContinue)) { Write-Host "note: git not found (winget install Git.Git) - needed for GitHub features" }
& $py -m venv "$data\venv"
& "$data\venv\Scripts\python.exe" -m pip install --upgrade pip -q
& "$data\venv\Scripts\python.exe" -m pip install $here -q
Set-Content -Path "$bin\ember.cmd" -Value "@echo off`r`n`"$data\venv\Scripts\ember.exe`" %*" -Encoding ASCII
$userPath = [Environment]::GetEnvironmentVariable("Path", "User")
if ($userPath -notlike "*$bin*") { [Environment]::SetEnvironmentVariable("Path", "$userPath;$bin", "User"); Write-Host "Added $bin to PATH (open a new terminal)." }
$extra = @(); if ($Preset) { $extra = @("--preset", $Preset) }
& "$data\venv\Scripts\ember.exe" setup @extra
