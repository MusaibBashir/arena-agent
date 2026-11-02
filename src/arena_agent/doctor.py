"""arena-agent doctor: is everything in place? Each check says what is wrong and how to fix it."""
import os
import platform
import shutil
import sys

from . import __version__, core, edition, install, paths


def _check(name, ok, detail, fix=None):
    rec = {"check": name, "ok": bool(ok), "detail": detail}
    if not ok and fix:
        rec["fix"] = fix
    return rec


def run(start_arena=True):
    checks = []
    checks.append(_check("windows", platform.system() == "Windows", platform.platform(),
                         "Arena runs on Windows only; run arena-agent on the Windows machine that has Arena."))
    checks.append(_check("python", True, f"{sys.version.split()[0]} at {sys.executable}"))
    try:
        import pythoncom  # noqa: F401
        import win32com.client  # noqa: F401
        checks.append(_check("pywin32", True, "pythoncom and win32com import"))
    except ImportError as e:
        checks.append(_check("pywin32", False, str(e), "Reinstall: run the install command from the README again."))
        return {"version": __version__, "ok": False, "checks": checks}
    d = core.arena_dir()
    checks.append(_check("arena installed", d and os.path.exists(os.path.join(d, "Arena.exe")), d or "not registered",
                         "Install Arena (Rockwell Automation), or set ARENA_DIR to the folder holding Arena.exe."))
    refs = [f for f in ("BasicProcess.txt", "AdvancedProcess.txt", "Blocks.txt", "Elements.txt")
            if d and os.path.exists(os.path.join(d, f))]
    checks.append(_check("template references", len(refs) == 4, ", ".join(refs) or "none found",
                         "Some reference files are missing; operand lookups and the reserved-word check are weaker."))
    if start_arena and d:
        try:
            import pythoncom
            pythoncom.CoInitialize()
            inf = core.info(core.app())
            ed = inf["edition"]
            checks.append(_check("arena COM", True, f"Arena {inf['version']} responded"))
            checks.append(_check("edition", ed["status"] in ("full", "limited"),
                                 f"{ed['name']} license, status {ed['status']}" +
                                 (f" (report header: {ed['report_license']})" if ed.get("report_license") else ""),
                                 "Tell arena-agent which edition this is: arena-agent edition limited (Student / "
                                 "Evaluation) or arena-agent edition full (commercial or university lab license)."))
        except Exception as e:
            checks.append(_check("arena COM", False, f"{type(e).__name__}: {e}",
                                 "Start Arena once by hand (accept any license or first-run dialog), close it, and "
                                 "run arena-agent doctor again."))
    checks.append(_check("skill files", os.path.exists(os.path.join(paths.skill_dir(), "SKILL.md")), paths.skill_dir()))
    for client in install.detect():
        st = install.status(client)
        checks.append(_check(f"client {client}", st["mcp"] and st["skill"] is not False, st,
                             f"Run: arena-agent install --client {client}"))
    if not install.detect():
        checks.append(_check("AI clients", False, "no Claude Code, Claude Desktop or Codex configuration found",
                             "Install an AI client, then run arena-agent install. For other MCP clients, register "
                             f"the command: {install.server_command()}"))
    checks.append(_check("on PATH", shutil.which("arena-agent") is not None, shutil.which("arena-agent") or "not found",
                         "Open a new terminal, or run: uv tool update-shell"))
    return {"version": __version__, "ok": all(c["ok"] for c in checks), "checks": checks,
            "config": edition.config_path()}
