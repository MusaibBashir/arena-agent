"""Register the MCP server and the arena-modeling skill with the AI clients on this machine.

    arena-agent install [--client claude-code|claude-desktop|codex ...]
    arena-agent uninstall [--client ...]

Claude Code: `claude mcp add --scope user` (or ~/.claude.json), skill in ~/.claude/skills/arena-modeling.
Claude Desktop: %APPDATA%\\Claude\\claude_desktop_config.json (its chat has no skill folder; the server's
  arena_guide tool serves the same text).
Codex: [mcp_servers.arena-agent] in ~/.codex/config.toml, skill in ~/.codex/skills/arena-modeling.
Any other MCP client: register the command printed by `arena-agent install --print`.
"""
import json
import os
import re
import shutil
import subprocess
import sys

from . import paths

NAME = "arena-agent"
SKILL = "arena-modeling"
HOME = os.path.expanduser("~")
CLIENTS = ("claude-code", "claude-desktop", "codex")


def server_command():
    """[exe, "mcp"]: the arena-agent executable next to this Python (uv tool / pip install), else on PATH, else
    python -m arena_agent."""
    here = os.path.join(os.path.dirname(sys.executable), "arena-agent.exe")
    if os.path.exists(here):
        return [here, "mcp"]
    found = shutil.which("arena-agent")
    if found:
        return [found, "mcp"]
    return [sys.executable, "-m", "arena_agent", "mcp"]


def codex_home():
    return os.environ.get("CODEX_HOME", os.path.join(HOME, ".codex"))


def desktop_config():
    return os.path.join(os.environ.get("APPDATA", HOME), "Claude", "claude_desktop_config.json")


def skill_target(client):
    return {"claude-code": os.path.join(HOME, ".claude", "skills", SKILL),
            "codex": os.path.join(codex_home(), "skills", SKILL)}.get(client)


def detect():
    found = []
    if shutil.which("claude") or os.path.isdir(os.path.join(HOME, ".claude")):
        found.append("claude-code")
    if os.path.isdir(os.path.dirname(desktop_config())):
        found.append("claude-desktop")
    if shutil.which("codex") or os.path.isdir(codex_home()):
        found.append("codex")
    return found


def _load_json(p):
    try:
        return json.load(open(p, encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _save_json(p, data):
    os.makedirs(os.path.dirname(p), exist_ok=True)
    if os.path.exists(p):
        shutil.copy2(p, p + ".bak-arena-agent")
    tmp = p + ".tmp"
    json.dump(data, open(tmp, "w", encoding="utf-8"), indent=2)
    os.replace(tmp, p)


def _copy_skill(client):
    dst = skill_target(client)
    if not dst:
        return None
    if os.path.isdir(dst):
        shutil.rmtree(dst)
    shutil.copytree(paths.skill_dir(), dst)
    return dst


TOML_BLOCK = re.compile(r"(?ms)^\[mcp_servers\.(?:\"arena-agent\"|arena-agent)(?:\.[^\]]*)?\]\n.*?(?=^\[(?!mcp_servers\.(?:\"arena-agent\"|arena-agent)[\].])|\Z)")


def _toml_str(s):
    return "'" + s + "'" if "'" not in s else json.dumps(s)


def _codex_mcp(cmd, remove=False):
    p = os.path.join(codex_home(), "config.toml")
    txt = open(p, encoding="utf-8").read() if os.path.exists(p) else ""
    new = TOML_BLOCK.sub("", txt).rstrip() + "\n"
    if not remove:
        args = ", ".join(_toml_str(a) for a in cmd[1:])
        new += (f"\n[mcp_servers.{NAME}]\ncommand = {_toml_str(cmd[0])}\nargs = [{args}]\n"
                "startup_timeout_sec = 120\ntool_timeout_sec = 3600\n")
    if new != txt:
        os.makedirs(os.path.dirname(p), exist_ok=True)
        if os.path.exists(p):
            shutil.copy2(p, p + ".bak-arena-agent")
        open(p, "w", encoding="utf-8").write(new.lstrip("\n"))
    return p


def _claude_code_mcp(cmd, remove=False):
    claude = shutil.which("claude")
    if claude:
        subprocess.run([claude, "mcp", "remove", "--scope", "user", NAME], capture_output=True, text=True)
        if remove:
            return "claude mcp remove"
        r = subprocess.run([claude, "mcp", "add", "--scope", "user", NAME, "--", *cmd], capture_output=True, text=True)
        if r.returncode == 0:
            return "claude mcp add --scope user"
    p = os.path.join(HOME, ".claude.json")  # no CLI (or it failed): edit the user config directly
    cfg = _load_json(p)
    cfg.setdefault("mcpServers", {}).pop(NAME, None)
    if not remove:
        cfg["mcpServers"][NAME] = {"type": "stdio", "command": cmd[0], "args": cmd[1:], "env": {}}
    _save_json(p, cfg)
    return p


def _desktop_mcp(cmd, remove=False):
    p = desktop_config()
    cfg = _load_json(p)
    cfg.setdefault("mcpServers", {}).pop(NAME, None)
    if not remove:
        cfg["mcpServers"][NAME] = {"command": cmd[0], "args": cmd[1:]}
    _save_json(p, cfg)
    return p


MCP = {"claude-code": _claude_code_mcp, "claude-desktop": _desktop_mcp, "codex": _codex_mcp}


def install(clients=None):
    cmd = server_command()
    done = []
    for c in clients or detect():
        rec = {"client": c, "mcp": MCP[c](cmd)}
        rec["skill"] = _copy_skill(c)
        if c == "claude-desktop":
            rec["note"] = "Restart Claude Desktop. Its chat has no skill folder; the arena_guide tool serves the guide."
        else:
            rec["note"] = f"Start a new {c} session to load the tools and the skill."
        done.append(rec)
    return {"command": cmd, "installed": done,
            "other_clients": {"mcpServers": {NAME: {"command": cmd[0], "args": cmd[1:]}}}}


def uninstall(clients=None):
    done = []
    for c in clients or detect():
        rec = {"client": c, "mcp": MCP[c](None, remove=True)}
        dst = skill_target(c)
        if dst and os.path.isdir(dst):
            shutil.rmtree(dst)
            rec["skill_removed"] = dst
        done.append(rec)
    return {"uninstalled": done}


def status(client):
    if client == "codex":
        p = os.path.join(codex_home(), "config.toml")
        mcp = os.path.exists(p) and bool(TOML_BLOCK.search(open(p, encoding="utf-8").read()))
    elif client == "claude-desktop":
        mcp = NAME in _load_json(desktop_config()).get("mcpServers", {})
    else:
        mcp = NAME in _load_json(os.path.join(HOME, ".claude.json")).get("mcpServers", {})
    dst = skill_target(client)
    return {"mcp": mcp, "skill": os.path.exists(os.path.join(dst, "SKILL.md")) if dst else None}
