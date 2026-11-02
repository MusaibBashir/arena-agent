# arena-agent installer for Windows.
#
#   powershell -ExecutionPolicy Bypass -c "irm https://raw.githubusercontent.com/MusaibBashir/arena-agent/main/install.ps1 | iex"
#
# Installs uv (if missing), then arena-agent with its own private Python (your Python, if any, is not touched),
# registers the MCP server and the arena-modeling skill with Claude Code, Claude Desktop and Codex (whichever are
# installed), and runs a health check. Run it again to update.
#
# Options (environment variables, set before running):
#   ARENA_AGENT_SOURCE   what to install (default: the latest code on GitHub; a local folder works for development)
#   ARENA_AGENT_CLIENTS  space-separated clients to register (default: all found): claude-code claude-desktop codex

$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'

function Say($msg) { Write-Host "==> $msg" -ForegroundColor Cyan }

if ($env:OS -ne 'Windows_NT') { throw 'arena-agent needs Windows (Rockwell Arena runs only on Windows).' }

$src = $env:ARENA_AGENT_SOURCE
if (-not $src) { $src = 'https://github.com/MusaibBashir/arena-agent/archive/refs/heads/main.zip' }

# 1. uv: a small tool that installs Python apps in their own environment
$uv = Get-Command uv -ErrorAction SilentlyContinue
if (-not $uv) {
    Say 'Installing uv (Python app installer from astral.sh)'
    Invoke-RestMethod https://astral.sh/uv/install.ps1 | Invoke-Expression
    $env:Path = "$env:USERPROFILE\.local\bin;$env:Path"
    $uv = Get-Command uv -ErrorAction Stop
}

# 2. arena-agent itself, with a private Python 3.12
Say "Installing arena-agent from $src"
& $uv.Source tool install --force --python 3.12 $src
if ($LASTEXITCODE -ne 0) { throw 'uv could not install arena-agent (see the messages above).' }
& $uv.Source tool update-shell 2>$null | Out-Null

$exe = Join-Path $env:USERPROFILE '.local\bin\arena-agent.exe'
if (-not (Test-Path $exe)) {
    $bin = (& $uv.Source tool dir --bin).Trim()
    $exe = Join-Path $bin 'arena-agent.exe'
}

# 3. register with the AI clients on this machine
Say 'Connecting arena-agent to your AI tools'
if ($env:ARENA_AGENT_CLIENTS) {
    & $exe install --client $env:ARENA_AGENT_CLIENTS.Split(' ')
} else {
    & $exe install
}

# 4. health check (starts Arena once; allow up to a minute)
Say 'Checking Arena (this starts Arena once; allow up to a minute)'
& $exe doctor
if ($LASTEXITCODE -eq 0) {
    Say 'Done. Start a new Claude / Codex session and ask it to model something in Arena.'
} else {
    Write-Host ''
    Write-Host 'arena-agent is installed, but some checks failed: follow the "fix" lines above, then run: arena-agent doctor' -ForegroundColor Yellow
}
