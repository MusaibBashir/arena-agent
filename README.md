# arena-agent

Let an AI agent (Claude, Codex, or any MCP client) build, run and analyse **Rockwell Arena** simulation models for
you. Describe the problem in plain words; the agent turns it into an Arena model, compiles it, fixes its own errors,
runs replications and reports the results with confidence intervals. Then ask "what if we add a fourth doctor?" and it
changes the model and runs it again.

> "Patients arrive at a clinic every 5 minutes on average. Three doctors each take about 12 minutes per patient.
> How long do patients wait, and would a fourth doctor be worth it?"

The agent builds `clinic.doe` (Create -> Process with 3 doctors -> Dispose), runs it, and answers with average waits,
utilization and their 95% half-widths for 3 and 4 doctors. The `.doe` file opens in Arena like any model you built
by hand.

## Install (one command)

You need Windows and Arena (any edition: Student, Academic, Standard, Professional). In **PowerShell**:

```powershell
powershell -ExecutionPolicy Bypass -c "irm https://raw.githubusercontent.com/MusaibBashir/arena-agent/main/install.ps1 | iex"
```

That's all. It installs everything it needs in its own folder (no Python or git required; an existing Python is not
touched), connects arena-agent to **Claude Code, Claude Desktop and Codex** (whichever you have), and checks that
Arena responds. Start a new Claude or Codex session afterwards. Run the same command again to update.

If something is off, run `arena-agent doctor`: every failed check says how to fix it.

### Other ways

- **Claude Code plugin:** `/plugin marketplace add MusaibBashir/arena-agent`, then `/plugin install arena-agent`
  (needs [uv](https://docs.astral.sh/uv/) on PATH).
- **Any other MCP client** (Cursor, Windsurf, ...): install with the command above, then add the server printed by
  `arena-agent install --print` to the client's MCP settings.
- **pip / uv:** `uv tool install https://github.com/MusaibBashir/arena-agent/archive/refs/heads/main.zip` then
  `arena-agent install`.

## What the agent can do

| Tool | What it does |
|---|---|
| `arena_status` | Arena version and edition; tells the agent whether model size is limited |
| `build_model` | create a model, or a new version of an existing one, from a JSON spec; compiles it |
| `inspect_model` | read any `.doe`: modules, settings, connections |
| `set_module`, `set_run_setup`, `delete_modules` | change a model |
| `check_model` | compile; every error names the module that caused it |
| `run_model` | run replications; every statistic with average, 95% half-width, min, max |
| `run_scenarios` | compare what-if scenarios without touching the saved model |
| `get_results` | read the last run's statistics again |
| `screenshot_model` | a picture of the flowchart |
| `arena_guide`, `template_reference`, `module_operands` | the modeling guide and Arena's own module reference |

The **arena-modeling skill** (installed alongside) teaches the agent the workflow: ask for missing data, build in
stages, verify against theory, choose replications and warm-up, compare scenarios properly, and hand back exactly
what you asked for: numbers, the model file, a written summary, or all three.

## Arena editions

arena-agent reads the license type from Arena. The free **Student** edition limits model size (Rockwell does not
publish the exact cap; it is commonly reported as 150 entities in the system at once). The agent keeps models small on
limited editions and tells you plainly if Arena reports a model is over the limit. If arena-agent cannot tell which
edition you have, the agent asks you once; you can also set it yourself:

```powershell
arena-agent edition limited   # Student / Evaluation
arena-agent edition full      # commercial or university lab license
```

## Command line

Everything is also available without an AI client; every command prints JSON:

```powershell
arena-agent build examples\clinic.json
arena-agent run clinic.doe --reps 20 --measures "Waiting Time" Utilization
arena-agent run clinic.doe --set Doctor:Capacity=4
arena-agent inspect clinic.doe
arena-agent --help
```

## How it works

Arena exposes a COM automation interface (`Arena.Application`). arena-agent drives it from Python (pywin32): it creates
modules, sets their operands, connects them, compiles, runs in batch mode, decodes Arena's binary error file to find
the module at fault, and reads results from Arena's report database. Arena's COM interface has many undocumented
traps (hidden entry points, names that are never declared, reserved words that stop runs at time 0); the ones found
so far are handled by the tool and written up in
[`skills/arena-modeling/references/discoveries.md`](skills/arena-modeling/references/discoveries.md).

Tested with Arena 16.20 (version 1620). Other versions should work; please open an issue with `arena-agent doctor`
output if yours does not.

## Contributing

Found a new Arena quirk? Add it to the discovery log (finding, how found, evidence, change) and open a pull request.
Development setup:

```powershell
git clone https://github.com/MusaibBashir/arena-agent; cd arena-agent
uv venv --python 3.12; uv pip install -e ".[dev]"
.venv\Scripts\pytest              # unit tests (no Arena needed)
.venv\Scripts\pytest -m arena     # end-to-end tests against a local Arena
```

## License

MIT. Arena is a product of Rockwell Automation; this project is not affiliated with or endorsed by Rockwell
Automation, and it does not include any Arena files. You need your own Arena installation and license.
