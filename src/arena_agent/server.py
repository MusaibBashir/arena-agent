"""MCP server: Arena as tools for any MCP client (Claude Code, Claude Desktop, Codex, Cursor, ...).

    arena-agent mcp        # stdio transport; the client starts it
"""
import json
import os
from typing import Any

from mcp.server.mcpserver import Image, MCPServer

from . import __version__, core, edition, paths, worker

INSTRUCTIONS = """\
Tools to build, run and analyse Rockwell Arena simulation models on this Windows machine.

Before the first model in a session: call arena_status (Arena version and edition; if edition.status is "unknown",
ask the user whether they use the free Student edition or a full/lab license and record it with set_edition), then
read the workflow with arena_guide (topic "skill"), unless your client already loaded the arena-modeling skill.
Turning a problem statement into a model: ask for missing data, build from a JSON spec with build_model, fix every
check error, run with enough replications, and report results with their 95% half-widths. Give the user what they
asked for: numbers, the .doe model, a written summary, or any combination.
Never overwrite a user's model: extend it with base + save_as. Paths are Windows paths on this machine."""

mcp = MCPServer("arena-agent", title="Arena simulation", version=__version__, instructions=INSTRUCTIONS)


def _guard(fn, *args, retry=False, **kwargs):
    try:
        return worker.call(fn, *args, retry=retry, **kwargs)
    except core.ArenaError as e:
        return {"error": str(e)}
    except Exception as e:  # COM errors carry a tuple; keep the readable part
        return {"error": f"{type(e).__name__}: {e}"}


@mcp.tool()
def arena_status() -> dict:
    """Arena's version, install folder, edition (license type, whether it is size-limited) and open models. Starts
    Arena if it is not running (allow up to a minute). Call this first."""
    return _guard(core.info, retry=True)


@mcp.tool()
def set_edition(limited: bool | None) -> dict:
    """Record whether this Arena is a size-limited edition (Student/Evaluation: true) or a full/lab license (false);
    null forgets the answer. Use it once the user has told you, when arena_status reports edition status "unknown"."""
    p = edition.set_limited(limited)
    return {"saved_to": p, "edition": _guard(core.info, retry=True).get("edition")}


@mcp.tool()
def arena_guide(topic: str = "skill") -> dict:
    """The arena-modeling guide: how to go from a problem statement to a verified model, the build-spec format,
    module recipes and the Arena COM gotchas. topic "skill" is the overview; it lists the other topics."""
    topics = paths.guide_topics()
    p = topics.get(topic)
    if not p or not os.path.exists(p):
        return {"error": f"unknown topic {topic!r}", "topics": sorted(topics)}
    return {"topic": topic, "topics": sorted(topics), "text": open(p, encoding="utf-8").read()}


@mcp.tool()
def list_panels() -> dict:
    """Template panels attached in Arena (internal names such as BasicProcess, AdvancedProcess)."""
    return _guard(core.panels, retry=True)


@mcp.tool()
def list_module_types(panel: str = "BasicProcess") -> dict:
    """Module types on a template panel, e.g. Create, Process, Decide, Assign, Dispose on BasicProcess."""
    return _guard(core.defs, panel, retry=True)


@mcp.tool()
def module_operands(module_type: str, panel: str = "BasicProcess") -> dict:
    """Every operand of a module type with its default value (the names to use in a spec's "data")."""
    return _guard(core.operands, panel, module_type, retry=True)


@mcp.tool()
def template_reference(module_type: str, panel: str | None = None) -> dict:
    """Arena's own reference text for one module type, from the template .txt files in the Arena folder: every operand
    including hidden exit/entry points, which operands repeat, and the choice labels. Read it before guessing
    operand names for a module you have not used yet."""
    try:
        return core.template_reference(module_type, panel)
    except core.ArenaError as e:
        return {"error": str(e)}


@mcp.tool()
def inspect_model(model: str, full: bool = False, out_path: str | None = None) -> dict:
    """Every module of a .doe model (type, name, position, operand values incl. repeat rows), every connection and
    the run setup. full=true includes data modules' operands too. With out_path, writes the JSON there and returns a
    summary (use it for big models)."""
    return _guard(core.inspect, model, full, out_path, retry=True)


@mcp.tool()
def build_model(spec: dict[str, Any] | None = None, spec_path: str | None = None) -> dict:
    """Build a new model, or extend an existing one, from a build spec (pass the spec object, or spec_path to a JSON
    file). New model: "save_as" is required. Extending: "base" is opened and first saved as "save_as", so the base
    file is never changed. The spec lists modules (panel, type, x, y, data, rows/cases/resources), connections
    (from, to, exit), updates to existing modules, run_setup, declare, delete. Names used by Assign, ReadWrite,
    Process, Hold, Search and Create are declared automatically. Compiles at the end: read check_errors (each names
    the module at fault) and dropped_connections. Spec format: arena_guide topic "build-spec"."""
    if spec is None and spec_path is None:
        return {"error": "pass spec or spec_path"}
    if spec is None:
        spec = json.load(open(spec_path, encoding="utf-8"))
    return _guard(core.build, spec)


@mcp.tool()
def set_module(model: str, module: str, data: dict[str, Any], save: bool = True) -> dict:
    """Change operands of one module by name, e.g. data={"Capacity": "4"} on Resource "Doctor", then save. Values
    are strings as typed in Arena's dialogs; repeat rows are "Operand(i)". Reads every value back and reports
    invalid choices. For several modules at once use build_model with base and updates (one open, one save)."""
    return _guard(core.set_data, model, module, data, save)


@mcp.tool()
def delete_modules(model: str, names: list[str]) -> dict:
    """Delete modules by name and save."""
    return _guard(core.delete, model, names)


@mcp.tool()
def set_run_setup(model: str, run_setup: dict[str, Any], save: bool = True) -> dict:
    """Change Run Setup: replications, replication_length, replication_length_units, warm_up, warm_up_units,
    base_time_units (units: days|hours|minutes|seconds), hours_per_day, terminating_condition."""
    return _guard(core.setup, model, run_setup, save)


@mcp.tool()
def check_model(model: str) -> dict:
    """Compile the model. errors name the module at fault; dropped_connections lists connections Arena deleted;
    edition_limit_exceeded is set when the model is too big for a limited edition."""
    return _guard(core.check, model)


@mcp.tool()
def run_model(model: str, replications: int | None = None, run_setup: dict[str, Any] | None = None,
              changes: dict[str, dict[str, Any]] | None = None, show: list[str] | None = None,
              measures: list[str] | None = None, per_replication: bool = False) -> dict:
    """Run the model in batch mode and return every statistic across replications: average, 95% half_width, min,
    max over replications and n. Keys look like "Process.Queue.Waiting Time", "Resource.Instantaneous Utilization",
    "Entity.Total Time", "Entity.WIP", output names. run_setup and changes ({module: {operand: value}}) apply to this
    run only and are restored afterwards, without saving. show evaluates Arena expressions at the end of the last
    replication. measures keeps only statistics whose names contain one of these strings."""
    res = _guard(core.run, model, replications, run_setup, changes, show, True, per_replication)
    if measures and "statistics" in res:
        res["statistics"] = {k: v for k, v in res["statistics"].items()
                             if any(q.lower() in k.lower() for q in measures)}
    return res


@mcp.tool()
def run_scenarios(model: str, scenarios: list[dict[str, Any]], replications: int | None = None,
                  run_setup: dict[str, Any] | None = None, measures: list[str] | None = None,
                  show: list[str] | None = None) -> dict:
    """Run several what-if scenarios in one Arena session without saving. Each scenario is {"name", "changes":
    {module: {operand: value}}, "replications", "run_setup"}; e.g. [{"name": "3 doctors", "changes": {"Doctor":
    {"Capacity": "3"}}}, {"name": "4 doctors", "changes": {"Doctor": {"Capacity": "4"}}}]. Use the same number of
    replications in every scenario you compare. measures keeps only statistics whose names contain these strings."""
    return _guard(core.scenarios, model, scenarios, replications, run_setup, show, measures)


@mcp.tool()
def get_results(model: str, per_replication: bool = False, include_empty: bool = False) -> dict:
    """Statistics of the model's last run, read from its report database (.db) or text report (.out), without running
    again. per_replication adds every replication's value."""
    try:
        return core.last_results(model, per_replication, include_empty)
    except Exception as e:
        return {"error": f"{type(e).__name__}: {e}"}


@mcp.tool()
def screenshot_model(model: str, out_path: str | None = None, region: list[float] | None = None,
                     pixels_per_unit: float | None = None) -> Any:
    """Picture of the model's flowchart (Arena must be visible on screen). Default: the whole flowchart fitted to one
    screen; region [x0, y0, x1, y1] in model units and pixels_per_unit zoom in. Saves a PNG next to the model unless
    out_path is given, and returns the image."""
    from .snapshot import snapshot
    out_path = out_path or os.path.splitext(os.path.abspath(model))[0] + "_flowchart.png"
    res = _guard(snapshot, model, out_path, region, pixels_per_unit)
    if "error" in res:
        return res
    return [json.dumps(res), Image(path=res["out"])]


@mcp.tool()
def close_models(models: list[str] | None = None) -> dict:
    """Close models without saving (all open models when none are given). Close a model before deleting or
    replacing its files; Arena keeps them locked while the model is open."""
    return _guard(core.close, models, retry=False)


def main():
    mcp.run("stdio")
