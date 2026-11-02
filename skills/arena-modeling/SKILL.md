---
name: arena-modeling
description: Build, run, modify and analyse Rockwell Arena discrete-event simulation models (.doe) on Windows through the arena-agent tools (MCP server or CLI). Use when the user wants a problem statement (queues, clinics, banks, factories, call centres, supply chains, ride hailing, any process with arrivals, resources and waiting) modelled or simulated in Arena, an existing Arena model changed, tested or debugged, or Arena results, scenarios or what-if comparisons.
---

# Arena modeling with arena-agent

arena-agent drives Rockwell Arena through its COM automation interface. You build models from a JSON spec, compile
them, run them in batch mode and read every statistic back with 95% confidence half-widths, without the user dragging
a single module. Tools come from the `arena-agent` MCP server (`arena_status`, `build_model`, `run_model`, ...). If
your client has no MCP, use the same operations from a shell: `arena-agent <command>` (`arena-agent --help`); every
command prints JSON.

## First, every session

1. `arena_status`. It starts Arena if needed (up to a minute) and reports the version and the **edition**.
   - `edition.status == "unknown"`: ask the user once, "Are you on the free Arena Student edition, or a full / university
     lab license?", then `set_edition(limited=true|false)`.
   - `"limited"`: keep models small. Rockwell does not publish the exact cap; the Student edition is commonly reported
     to stop runs once more than 150 entities are in the system at once. Prefer designs with few entities alive at once
     (finite runs, no huge initial batches, no entities parked forever). `check_model` / `run_model` report
     `edition_limit_exceeded` when Arena says the model is over the limit: tell the user plainly and offer a smaller
     model.
   - `"view-only"` / `"run-only"`: you cannot build or edit; you can only run existing models.
2. If `arena_status` fails, run `arena-agent doctor` in a shell and follow its `fix` lines.

## From problem statement to answer

1. **Understand the system.** Identify entities (what flows), arrivals (rate, distribution, schedule), activities
   (durations, distributions), resources (how many, schedules), routing (probabilities, conditions), queue rules,
   run length / terminating condition, warm-up, and the **measures** the user cares about (waiting time, utilization,
   throughput, queue length, cost ...).
2. **Ask for what is missing, briefly.** If the user does not know a value, propose a standard assumption (e.g.
   exponential interarrival times, triangular service times) and say it is an assumption. Do not ask about anything
   you can default sensibly; list your assumptions in the final answer.
3. **Sketch the flow** in a sentence or two (Create -> Assign -> Decide -> Process ... -> Dispose) and the data
   modules (Resources, Variables). For a big system, plan stages and build/verify one stage at a time.
4. **Build** with `build_model` (spec: `arena_guide("build-spec")`, recipes: `arena_guide("modules")`). Put the model
   where the user wants it; default to their current project folder. Never overwrite the user's model: extend it with
   `base` + `save_as` (a new version file).
5. **Fix until clean.** `build_model` compiles at the end. Every `check_errors` entry names the module at fault; also
   act on `errors` (operands Arena rejected, invalid choices), `warnings` and `dropped_connections`. Re-run
   `check_model` after fixes. The common traps are in `arena_guide("gotchas")`; read it before your first model.
6. **Verify.** Run a few replications and sanity-check against theory or hand calculations: utilization ~ arrival
   rate x service time / servers; flow conservation (in = out + still inside); for simple queues compare with M/M/c
   formulas. Look at the flowchart with `screenshot_model` when layout or connections are in doubt.
7. **Run for the answer.** Choose replications so the half-widths are small relative to the differences that matter
   (start with 10-30; more if half-widths are wide). Set run length, warm-up (for steady-state questions) and base time
   units explicitly in `run_setup`. See `arena_guide("results")`.
8. **Compare alternatives** with `run_scenarios` (changes applied in memory, nothing saved; same replications for every
   scenario). Report whether differences are bigger than the half-widths.
9. **Deliver exactly what was asked**: numbers (with units and 95% half-widths), the `.doe` file path, a written
   summary (system, assumptions, results, recommendation), or any combination. The `.doe` opens in Arena; results
   also stay in `<model>.db` / `<model>.out`.

## Tools at a glance

| Tool | Use |
|---|---|
| `arena_status`, `set_edition` | Arena version, edition / license limits |
| `arena_guide(topic)` | this guide and its references: `skill`, `build-spec`, `modules`, `gotchas`, `results`, `discoveries` |
| `list_panels`, `list_module_types`, `module_operands`, `template_reference` | discover module types and exact operand names |
| `build_model` | create or extend a model from a spec; compiles |
| `inspect_model` | read an existing model: modules, operands, connections, run setup |
| `set_module`, `set_run_setup`, `delete_modules` | small edits (saved) |
| `check_model` | compile; errors mapped to modules |
| `run_model` | run; all statistics with half-widths; temporary `changes` / `run_setup` |
| `run_scenarios` | what-if comparisons in one session |
| `get_results` | statistics of the last run without re-running |
| `screenshot_model` | PNG of the flowchart |
| `close_models` | close before deleting / replacing files |

## Working with an existing model

`inspect_model` first (with `out_path` for big models), then plan changes. Many small edits: one `build_model` with
`base` = the model (and `save_as` = a new version) and an `updates` list, instead of many `set_module` calls (each one
opens and saves the model). Before trusting results of a model someone else built, check its data against the problem
statement: hand-entered tables are often wrong in one cell.

## Rules

- Do not save over a user's model without asking; keep versions (`model_v2.doe`, ...).
- Values in specs are strings exactly as typed in Arena's dialogs ("EXPO(5)", "Minutes", "Seize Delay Release").
- Names of attributes and variables must not be SIMAN reserved words (`Wait`, `Group`, `Queue`, `Delay`, `Count`, ...);
  the tools refuse them, rename (e.g. `RWait`).
- One Arena runs one model at a time; tool calls are serialised. A run of a large model can take minutes.
- When something new about Arena's COM behaviour is learned the hard way, tell the user; it may belong in the project's
  DISCOVERIES.md (https://github.com/MusaibBashir/arena-agent).
