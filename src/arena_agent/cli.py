"""arena-agent: drive Rockwell Arena from the command line or from an AI agent. Every command prints JSON.

  arena-agent doctor                            # is everything in place? (Arena, COM, edition, AI clients)
  arena-agent install [--client NAME ...]       # register the MCP server and skill with Claude Code / Desktop / Codex
  arena-agent uninstall [--client NAME ...]
  arena-agent mcp                               # MCP server on stdio (AI clients start this themselves)
  arena-agent edition limited|full|auto         # record whether this Arena is a size-limited edition
  arena-agent guide [TOPIC]                     # print the arena-modeling guide (topics: skill, build-spec, ...)

  arena-agent info
  arena-agent panels
  arena-agent defs BasicProcess
  arena-agent operands BasicProcess Create
  arena-agent reference Process [--panel BasicProcess]      # Arena's own operand reference for a module type
  arena-agent inspect model.doe [out.json] [--full]
  arena-agent build  spec.json                  # new model, or extend "base" and save as "save_as"
  arena-agent set    model.doe Module "Operand=Value" ["Operand=Value" ...] [--no-save]
  arena-agent setup  model.doe "replications=10" "replication_length=480" ...   # Run Setup
  arena-agent delete model.doe Module [Module ...]
  arena-agent check  model.doe
  arena-agent run    model.doe [--reps N] [--set Module:Operand=Value ...] [--show EXPR ...] [--measures S ...]
                                [--per-rep]
  arena-agent scenarios model.doe cases.json [--reps N] [--measures S ...]
  arena-agent results model.doe [--per-rep] [--all]   # statistics of the last run (no new run)
  arena-agent screenshot model.doe out.png [--region X0 Y0 X1 Y1] [--ppu P]
  arena-agent close  [model.doe ...]
"""
import json
import sys

from . import __version__


def out(obj):
    print(json.dumps(obj, indent=2, default=str))


def opt_list(args, flag):
    """Values after --flag up to the next --option."""
    if flag not in args:
        return []
    vals = []
    for x in args[args.index(flag) + 1:]:
        if x.startswith("--"):
            break
        vals.append(x)
    return vals


def positional(args):
    res, skip = [], False
    for x in args:
        if x.startswith("--"):
            skip = True
            continue
        if not skip:
            res.append(x)
    return res


def kv(items):
    return dict(x.split("=", 1) for x in items)


def parse_changes(items):
    """["Doctor:Capacity=4", ...] -> {"Doctor": {"Capacity": "4"}}"""
    ch = {}
    for x in items:
        mod, rest = x.split(":", 1)
        k, v = rest.split("=", 1)
        ch.setdefault(mod, {})[k] = v
    return ch


def num(s):
    try:
        return int(s)
    except ValueError:
        try:
            return float(s)
        except ValueError:
            return s


def com(fn, *args, **kwargs):
    import pythoncom
    from . import core
    pythoncom.CoInitialize()
    try:
        return fn(core.app(), *args, **kwargs)
    except core.ArenaError as e:
        return {"error": str(e)}


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    if not argv or argv[0] in ("-h", "--help", "help"):
        print(__doc__)
        return 0
    cmd, args = argv[0], argv[1:]
    pos = positional(args)
    if cmd in ("--version", "version"):
        out({"arena-agent": __version__})
        return 0
    if cmd == "mcp":
        from .server import main as serve
        serve()
        return 0
    if cmd == "doctor":
        from . import doctor
        res = doctor.run(start_arena="--no-arena" not in args)
        out(res)
        return 0 if res["ok"] else 1
    if cmd in ("install", "uninstall"):
        from . import install
        if "--print" in args:
            out({"mcpServers": {install.NAME: dict(zip(("command", "args"), (install.server_command()[0],
                                                                            install.server_command()[1:])))}})
            return 0
        clients = opt_list(args, "--client") or None
        bad = [c for c in clients or [] if c not in install.CLIENTS]
        if bad:
            out({"error": f"unknown client(s) {bad}; use {list(install.CLIENTS)}"})
            return 2
        out(install.install(clients) if cmd == "install" else install.uninstall(clients))
        return 0
    if cmd == "edition":
        from . import edition
        val = {"limited": True, "full": False, "auto": None}.get(pos[0] if pos else "")
        if not pos or pos[0] not in ("limited", "full", "auto"):
            out({"error": "use: arena-agent edition limited|full|auto"})
            return 2
        out({"saved_to": edition.set_limited(val), "limited": val})
        return 0
    if cmd == "guide":
        from . import paths
        topics = paths.guide_topics()
        t = pos[0] if pos else "skill"
        if t not in topics:
            out({"error": f"unknown topic {t!r}", "topics": sorted(topics)})
            return 2
        print(open(topics[t], encoding="utf-8").read())
        return 0
    if cmd == "results":
        from . import core
        out(core.last_results(pos[0], "--per-rep" in args, "--all" in args))
        return 0
    from . import core
    if cmd == "info":
        res = com(core.info)
    elif cmd == "panels":
        res = com(core.panels)
    elif cmd == "defs":
        res = com(core.defs, pos[0])
    elif cmd == "operands":
        res = com(core.operands, pos[0], pos[1])
    elif cmd == "reference":
        panel = opt_list(args, "--panel")
        try:
            res = core.template_reference(pos[0], panel[0] if panel else None)
        except core.ArenaError as e:
            res = {"error": str(e)}
        if "text" in res:
            print(res["text"])
            return 0
    elif cmd == "inspect":
        res = com(core.inspect, pos[0], "--full" in args, pos[1] if len(pos) > 1 else None)
    elif cmd == "build":
        res = com(core.build, pos[0])
    elif cmd == "set":
        res = com(core.set_data, pos[0], pos[1], kv(pos[2:]), "--no-save" not in args)
    elif cmd == "setup":
        res = com(core.setup, pos[0], {k: num(v) for k, v in kv(pos[1:]).items()}, "--no-save" not in args)
    elif cmd == "delete":
        res = com(core.delete, pos[0], pos[1:])
    elif cmd == "check":
        res = com(core.check, pos[0])
    elif cmd == "run":
        reps = opt_list(args, "--reps")
        res = com(core.run, pos[0], int(reps[0]) if reps else None, None, parse_changes(opt_list(args, "--set")),
                  opt_list(args, "--show"), True, "--per-rep" in args)
        ms = opt_list(args, "--measures")
        if ms and "statistics" in res:
            res["statistics"] = {k: v for k, v in res["statistics"].items() if any(q.lower() in k.lower() for q in ms)}
    elif cmd == "scenarios":
        reps = opt_list(args, "--reps")
        cases = json.load(open(pos[1], encoding="utf-8"))
        res = com(core.scenarios, pos[0], cases, int(reps[0]) if reps else None, None, None,
                  opt_list(args, "--measures") or None)
    elif cmd == "screenshot":
        from .snapshot import snapshot
        region = [float(x) for x in opt_list(args, "--region")] or None
        ppu = opt_list(args, "--ppu")
        res = com(snapshot, pos[0], pos[1], region, float(ppu[0]) if ppu else None)
    elif cmd == "close":
        res = com(core.close, pos or None)
    else:
        print(__doc__)
        return 2
    out(res)
    return 1 if isinstance(res, dict) and res.get("error") else 0


if __name__ == "__main__":
    sys.exit(main())
