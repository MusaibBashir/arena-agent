# Discovery log: driving Arena through COM

Everything learned about driving Rockwell Arena 16.2 (version 1620) through its COM automation interface: the
finding, how it was found, the evidence, and what changed in the tool because of it. The short, actionable version is
`gotchas.md`; this file is the evidence.

The first sessions come from building a large ride-hailing simulation (about 300 modules: drivers, riders, a
dispatcher, relocation strategies, output statistics) with the tool's predecessor, `arena_cli.py`. Commands named
there (`build`, `set`, `check`, `run --show`, `--outputs`) map onto today's `arena-agent` commands and MCP tools; file
names like `stageB.py` or `run_tests.py` were that project's own scripts.

**Contributing:** found something new? Add a dated session at the bottom (Finding · How found · Evidence · Change, or
*open*), and update the open items. Pull requests welcome at https://github.com/MusaibBashir/arena-agent.

---

## Session 2026-10-31: building Stage B (drivers) of the contracts model

### Discovery method

| Source | What it is good for |
|---|---|
| `pythoncom.LoadTypeLib("C:/Program Files/Rockwell Software/Arena/Arena.exe")` | Every COM interface and method. The interfaces are named `IModel`, `IModule`, `IModules`, `IConnections`, `IConnection`, `ISelection`, `IShape`, `IOperand`, `IView` ... (the coclasses `Model`, `Module` show no members) |
| `BasicProcess.txt`, `AdvancedProcess.txt` (etc.) in the Arena folder | Every operand of every module, **including hidden ones** (`(Hidden)`), which is where the exit and entry points are |
| A scratch model (`a.Models.Add()`, saved to `Documents\claude_probe*.doe`) | Trying values and connections without touching a real model |
| `inspect` on a model the user built in the GUI | Ground truth for how the GUI stores values (e.g. Decide `Type` = `If`) |
| `Template\*.tpo`, `Template\OldArenaTemplates\*.tpo` | Not useful: option values are not stored as plain strings |
| `Operand.PickList()` over COM | Not useful: returns labels shifted by one, or `ÿ` characters |

### 1. Reading a module's type and position

- **Finding:** `module.Name`, `module.Tag`, `module.Left`, `module.ModuleDefinition` do not exist. Use
  `module.Definition.Name`, `module.Definition.DataModule`, `module.shape.Left/Top/SerialNumber`, `module.Data("Name")`.
- **How found:** the first inspect returned only names; the `IModule` interface dump showed the real members.
- **CLI change:** `inspect` command.

### 2. Repeat groups are addressed as `Operand(i)`

- **Finding:** row *i* of a repeat group is `Operand(i)`; row 1 is also plain `Operand`. Works for get and put:
  `Var(22)`, `AName(11)`, `N Value(2)`, Expression `Value(17)` (2-D expressions are stored row-major, `Dim1` × `Dim2`).
  Reading past the last row raises `DISP_E_EXCEPTION`.
- **How found:** probing `Read_Scenario` (22 rows) and `Declare_Attrs` (11 rows) in the user's v1.
- **Finding:** setting row 3 on a fresh Assign creates rows 2 and 3, but row 2 gets defaults
  (`Attribute 2`, Type `Variable`). The count operand (`Assignments`) cannot be read or set.
- **CLI change:** spec `rows` / `cases` lists, always written 1..n in order.

### 3. Choice operands: labels in, internal values stored, no validation

- **Finding:** passing the dialog label stores the internal value; unknown text is stored **verbatim with no error**.

| Module, operand | Label → stored |
|---|---|
| Decide `Type` | `2-way by Chance`→`With`, `2-way by Condition`→`If`, `N-way by Chance`→`NWith`, `N-way by Condition`→`NIf` |
| Separate `Type` | `Split Existing Batch`→`Split`, `Duplicate Original`→`Duplicate` |
| Hold `Type` | `Wait for Signal`→`Wait`, `Scan for Condition`→`Scan`, `Infinite Hold`→`Infinite` |
| Search `Type` | `Search a Batch`→`Batch`, `Search a Queue`→`Queue`, `Search an Expression`→`Expression` |
| ReadWrite `Type` | `Read from File`→`ReadFile`, `Write to File`→`WriteFile` (also `ReadKeyboard`, `WriteScreen`) |
| Create `Interarrival Type` | `Random`, `Schedule`, `Constant`, `Expression` |
| Assign `Type` | `Variable`, `Variable Array (1D)`, `Variable Array (2D)`, `Attribute`, `Entity Type`, `Entity Picture`, `Other` |

- **How found:** set each candidate in a scratch model and read it back.
- **CLI change:** `apply_data` reads every value back; `CHOICES` lists valid internal values and flags anything else.

### 4. Exit and entry points are hidden operands

- **Finding:** `Connections.Create(src, dst, srcOperand, destOperand, srcRepeatIndex, destRepeatIndex)` needs the
  hidden operand names from the template text files:

| Module | Exit operands |
|---|---|
| most | `Next Label` |
| Decide 2-way | `Next Label Yes` (true), `Next Label No` (false) |
| Decide N-way | `N Next Label Yes` + repeat index *i* for case *i*; `Next Label No` for else |
| Separate | `Next Label Orig` (original), `Next Label` (duplicates) |
| Search | `Next Label Found`, `Next Label None` |
| Remove | `Next Label` (the remover, "Original"), `Next Label Removed` |

  Entry: `Label` for most modules; **Hold: `QLabel`** (see 6).
- **How found:** `Operand.Exit` is never true over COM; the names came from `BasicProcess.txt` / `AdvancedProcess.txt`,
  then tried in a scratch model.
- **CLI change:** `EXITS`, `ORIGINAL_EXIT`, `ENTRIES`; spec `exit` = `next|true|false|else|case:N|original|duplicate|found|notfound|removed`.

### 5. AutoConnect

- **Finding:** Arena auto-connects modules as they are placed; an explicit connection on top raises `E_INVALIDARG`.
  `m.ActiveView.AutoConnect = False` stops it. One exit can hold one connection: a second `Create` from the same exit
  replaces the first.
- **CLI change:** `build` turns AutoConnect off and connects explicitly.

### 6. Hold's entry is `QLabel`; `HoldLabel` connections vanish at Check  ⚠

- **Finding:** `Connections.Create(..., "HoldLabel")` succeeds and the connection is listed, but **`Check()` silently
  deletes it**, and then reports "Unconnected exit point" on the *source* module. `QLabel` connections survive. `Label`
  raises "The server threw an exception".
- **How found:** v2 kept losing the three `Which_Idle → Idle_*` connections (60 → 57). Reproduced: count before and
  after `Check()` in v2, then in a scratch model with four Hold variants (all dropped with `HoldLabel`, all kept with `QLabel`).
- **CLI change:** `ENTRIES = {"Hold": ("QLabel",)}`; `check()` compares the connection list before and after and
  reports `dropped_connections`; `build` runs it at the end.

### 7. Changing a Hold's queue settings drops its incoming connections

- **Finding:** after `set Idle_D QSGInfinite=Queue QName=...` the connections into that Hold were gone.
- **Status:** probably the same `HoldLabel` effect as 6 (those connections had been made with `HoldLabel`); not
  re-tested with `QLabel` connections. *Open:* if it recurs, set queue fields before connecting.

### 8. Names are not declared automatically through COM

- **Finding:** the GUI creates Attribute / Variable / Queue data modules as you type names in dialogs; COM does not.
  Check then fails with `Undefined identifier: Foo` / `Idle_D.Queue`.
- **Finding:** a Hold's `QName` defaults to ``"`Name`.Queue"`` and reads back as `Idle_D.Queue`, but the queue still
  needs a Queue data module (BasicProcess `Queue`) named `Idle_D.Queue`.
- **CLI change:** `used_names` + `declare`: attributes/variables from Assign rows and ReadWrite attribute rows, queues
  from Hold `QName` and Search/Remove `Queue Name`. `set` declares too.
- *Open:* names used only inside expressions (e.g. an attribute only read in a Decide) are not declared yet.

### 9. Arena adds data modules by itself

- **Finding:** creating a module also creates data modules: Create → `Entity 1` (if missing), ReadWrite → `File 1`,
  Hold → `Hold n.Queue`, Search → `Queue 1`. An unedited `File 1` fails Check with "This module has not been edited".
  The Hold/Search queues disappear by themselves once real queue names are set.
- **How found:** "This module has not been edited" with no module named; the error record's serial number pointed at `File 1`.
- **CLI change:** `build` reports these as `auto_created`; spec `delete` list removes them.

### 10. Deleting a module

- **Finding:** no `Module.Delete`/`Modules.Remove`. `ISelection` has `Delete`:
  `sel = m.ActiveView.Selection; sel.DeselectAll(); sel.Add(mod.shape); sel.Delete()`.
- **How found:** type-library search for delete/remove/cut/clear methods.
- **CLI change:** `delete` command and spec `delete`.

### 11. Errors: `<model>.err` and how to find the faulty module

- **Finding:** `Check()` returns `None` and shows no dialog with `QuietMode = True`. Messages go to `<model>.err`, a
  binary file. A MODVAL record is: int32 4, int32 −1, int32 16, int32 ?, int32 ?, **int32 shape serial number**
  (offset 20 from the start, i.e. 20 bytes before the source tag), 16 zero bytes, `MODVAL` padded with zeros, message.
  The serial matches `module.shape.SerialNumber`.
- **Finding:** SIMAN compile messages use tag `GGTNAM` and arrive as fragments of the generated SIMAN code
  (`4$ ASSIGN:DType=1:`, `^^^^^^`, `WARNING: ...`).
- **How found:** hex dump of the `.err`, then matching 922 against every module's shape serial.
- **CLI change:** `read_err` returns `{source, message, module, type}`.
- *Open:* group GGTNAM fragments into one message per error and separate warnings from errors.

### 12. SIMAN reserved words stop the run  ⚠

- **Finding:** an attribute named `Group` compiles with only "WARNING: Symbol name Group is a reserved name", but
  `Go()` then returns at once with the clock at 0. Renaming to `ShiftGrp` fixed it.
- *Open:* add a reserved-word check to `build` (SIMAN block/element names: `Group`, `Queue`, `Station`, `Delay`,
  `Count`, `Tally`, `Batch`, `Split`, `Match`, `Search`, `Signal`, `Branch`, `Seize`, `Route` ...).

### 13. Running

- **Finding:** `m.BatchMode = True`, `m.QuietMode = True`, `m.NumberOfReplications = n`, `m.Go(1)` (smGoWait) blocks
  until the run ends; `m.SIMAN.RunCurrentTime` then gives the end time (1080 for a full replication). Call `m.End()`
  afterwards or the model stays in run mode. A one-day Stage B replication took 1.2 s.
- **Finding:** `end_time` 0.0 after a run means it did not run (see 12); always compare it with the replication length.
- **CLI change:** `run` command.

### 14. Changing a variable's initial value

- **Finding:** a Variable's scalar initial value is the operand `Initial Value`; array elements are
  `Initial Value(i)`. Rows/Columns are `Rows` / `Columns`. Expressions use `Value(i)`, `Dim1`, `Dim2`.
  File modules store the path in `OSFile`.
- **CLI change:** none needed: `set model.doe Scen "Initial Value=4"`.

### 15. Opening, saving, closing

- **Finding:** `Models.Open` on a file already open may give a second copy; match `FullName` against the open models
  first. `SaveAs` to a new path before editing keeps the base file untouched. Close a model before deleting its files:
  `<model>.db` stays locked while it is open. `Close()` on a saved model shows no dialog.
- **CLI change:** `_open` reuses open models; `build` with `base` SaveAs's first; `close` command.

### 16. Misc

- `Panel.Name` of a module's definition (`Definition.Parent.Name`) is not available; keep the panel in the spec.
- Panels needed so far: `BasicProcess` (Create, Assign, Decide, Separate, Dispose, Attribute, Variable, Queue,
  Entity) and `AdvancedProcess` (Hold, Search, Remove, Delay, ReadWrite, Expression, File, Statistic).
- Heredocs in Git Bash mangle `\x00`, `\s`, `\a` in Python source: write scripts with an editor/Write tool instead.

---

## Session 2026-10-31 (later): building Stage C (riders)

Stage C: 42 modules, 57 connections, extends v2 into v3 (`contracts\arena_specs\stageC.py`). Built clean on the
second attempt; passed Test C (640.7 riders/rep, abandoned mean wait 10.23 ± 0.32, morning Downtown destinations
47.7 / 29.7 / 22.6%).

### 17. The reserved-word trap hit again: `Wait`  ⚠ (closes open item from 12)

- **Finding:** the rider attribute `Wait` gave "WARNING: Symbol name Wait is a reserved name", exactly like `Group`.
  `Wait` is a SIMAN block. Renamed to `RWait`.
- **Finding:** the authoritative reserved list ships with Arena: module names in `Blocks.txt` (SIMAN blocks: `Assign`,
  `Count`, `Delay`, `Group`, `Queue`, `Route`, `Search`, `Seize`, `Signal`, `Split`, `Station`, `Tally`, `Wait`, ...)
  and `Elements.txt` (SIMAN elements: `Attributes`, `Queues`, `Variables`, `Resources`, ...). SIMAN is case-insensitive.
- **How found:** `grep "^Module:" Blocks.txt Elements.txt` after the second clash.
- **CLI change:** `reserved_words()` reads both files at run time (`ARENA_DIR` env var overrides the folder);
  `build` and `set` refuse reserved attribute/variable names **before opening the model**
  (`{"error": ..., "names": ["Wait"], "model_changed": false}`). Spec `"allow_reserved": true` overrides.
  Queue names (`X.Queue`) are exempt.

### 18. SIMAN compile records in `.err` (closes open item from 11)

- **Finding:** a record starts after ≥ 8 zero bytes with its source tag (`MODVAL` = module validation, `GGTNAM` =
  SIMAN compile) and a zero byte. A GGTNAM record's text is one block with newlines: the generated SIMAN code line(s),
  a caret line (`^^^^`) under the offending symbol, then the message (`WARNING: ...`). The int32 20 bytes before a
  GGTNAM tag is **not** a shape serial (mapping it named unrelated modules like `NNeg`, `Hr`); only MODVAL has one.
- **CLI change:** `read_err` returns one entry per record with `level` (warning/error), `message`, `code` (SIMAN lines),
  `module` (MODVAL only), and collapses repeats into `count`. A Stage C error list went from ~50 fragments to 4 entries.

### 19. Modules with no incoming connection are fine

- **Finding:** `Rider_Served` and `Rider_Cancelled_On` have no entry connection until Stage D; Check accepts that
  (only unconnected *exits* are errors).

### 20. Run output files

- **Finding:** a `Write to File` file with Initialize Option `Hold` is rewritten at the start of a run and appended
  across replications within it (riders.csv held all 10 replications; the next run replaced it).
- **Finding:** `run --reps 10` for Stages A-C: 1.7 s.

### 21. Model data the GUI build got wrong

- **Finding:** `DayMult` had initial value 0 in the user's v1 (the guide says 1). Harmless once Stage C redraws it at
  0.005 min, but in Stage B alone the driver log wrote `DayMult = 0`. Found with `inspect --full`.
- **Lesson:** after each stage, compare key initial values against the guide's tables with `inspect --full`.

---

## Session 2026-11-01: building Stage D (dispatcher and trip)

Stage D: 66 modules, 97 connections (three 17-module zone blocks from one generator function, plus the trip chain),
extends v3 into v4 (`contracts\arena_specs\stageD.py`). Built and compiled clean on the first attempt; failed at run
time (22); passed Test D after the fix (30 reps of Scen 71: service 0.748 ± 0.013 vs key 0.731 ± 0.02, suburb
0.728 vs 0.707, FT gross 2,571 vs 2,521, PT 1,411 vs 1,394, revenue 39,316 vs ~38,600).

### 22. `AQUE(queue, rank, Attr)` needs `NSYM(Attr)`  ⚠

- **Finding:** `AQUE(Wait_S.Queue, RR, Dest)` compiles, but at run time a bare attribute name is *evaluated* (the
  active entity's own `Dest`, here the dispatcher's 0), so AQUE gets attribute number 0 and the run stops:
  "Number is invalid or no ATTRIBUTES element was specified ... Attribute number 0 is not in valid range 1-39".
  Correct form: `AQUE(Wait_S.Queue, RR, NSYM(Dest))`. The same holds for every function taking an
  *Attribute Number* (`AG`, `SAG`, `SAQUE`, `ATTR`, `A`), *Expression Number* (`ED`, `EXPR`) or *Variable number*.
- **How found:** the run's `.err` (see 23), then Arena's *Variables and Functions Guide* PDF.
- **New discovery source:** `C:\Program Files\Rockwell Software\Arena\Online Books\Variables and Functions Guide.pdf`
  (searchable with `pypdf`): the reference for every SIMAN function's argument types. The `.chm` help files could
  not be extracted here (no 7z; `hh.exe -decompile` produced nothing).
- **CLI change:** none yet. *Open:* a lint in `build` that flags `AQUE`/`SAQUE`/`AG`/`SAG`/`ATTR(` whose attribute
  argument is a bare name.

### 23. Run-time errors land in `.err` too, and `run` already reports them

- **Finding:** a run-time error stops the run (`end_time` = the time of the error, here 0.5) and writes a record whose
  source tag is the failing function (`AQUE`), with the entity number, time, the failing SIMAN block (`ASSIGN` with
  all its assignments) and the reason. `read_err` parsed it as one entry with no change needed.
- **Lesson:** a clean `check` does not mean a clean run; always compare `end_time` with the replication length.

### 24. Throughput and locks

- **Finding:** Stages A-D, 30 replications of a full day: 3.6 s in batch mode.
- **Finding:** after `close`, `<model>.db` (the report database) can stay locked by the Arena process; the `.doe` can
  still be deleted and rebuilt, and the `.db` is overwritten by the next run.

### 25. Checking a stage against the answer key

- **Finding:** `drivers.csv`/`riders.csv` are free-format, space separated, no header; read with
  `pd.read_csv(path, sep=r"\s+", header=None, names=...)`. Per-replication means with a 95% half-width
  (1.96·sd/√reps) are what to compare with the key; differences within the combined half-widths are noise.

---

## Session 2026-11-01 (later): building Stage E (relocation R1, empty move)

Stage E: 31 modules, 44 connections, extends v4 into v5 (`contracts\arena_specs\stageE.py`). Built, compiled and ran
clean on the first attempt. Passing Test E needed a model fix found by docking (26).

### 26. Event order inside a tick matters: dock against the reference with many replications  ⚠

- **Finding:** with 30 replications Arena's service was ~1.3 points above the answer key in all five scenarios
  tested, each gap only ~1 standard error. 300 replications of Arena vs the C++ reference (`driver_sim_fast.run()`,
  called directly so the project's `sim_out` is not overwritten) showed the gap was real (0.800 vs 0.791, CI ±0.0045),
  with the signature: equal requests, fewer lost riders, lost riders waiting 0.37 min longer.
- **Cause:** the reference does abandonment *then* matching at each 0.5-min tick. The guide's rider clock scanned at
  x.25/x.75 (offset 0.245), between dispatcher ticks, so a rider whose patience ran out in (x.25, x.5) could still be
  matched at x.5.
- **Fix:** `First_Offset` = 0.49 (scans at x.495, just before each dispatch). After it, 13 of 14 measures agree
  within the 95% CI at 300 replications; only driver-hours differ (+0.84 h of 920, the shift clock's 0.2-min lag).
- **Lessons:** (a) when one model mirrors a time-stepped reference, match the *order* of events within a step, not
  only their period; (b) a borderline gap that repeats across scenarios run with common random numbers is not
  independent evidence; rerun one scenario with ~10× the replications in both engines before accepting or chasing it;
  (c) compare decomposed measures (lost share, wait of lost riders, by zone), they point at the mechanism.

### 27. Test runner for stages

- **New tool:** `contracts\arena_specs\run_tests.py model.doe 1 4 5 6 --reps 30`: per scenario sets `Scen` with the
  CLI, runs, checks `end_time` and that the logs belong to the run, copies the logs to `arena_out\test_logs\`, prints
  each answer-key measure with its 95% half-width, and sets `Scen` back to 1. Five scenarios × 30 reps ≈ 16 s.
- **Finding:** 300 replications of Stages A-E take ~28 s in batch mode.

---

## Session 2026-11-01 (later): building Stage F (repositioning R2-R4)

Stage F: 31 modules, 49 connections, extends v5 into v6 (`contracts\arena_specs\stageF.py`). Passed Test F
(service to suburb R0-R4: 0.719 / 0.784 / 0.775 / 0.827 / 0.837 vs key 0.707 / 0.776 / 0.776 / 0.818 / 0.834;
DirMoves 0 under R0/R1, Relocs 0 except R1, Inbound never negative).

### 28. Reading results after a run (closes an open item)

- **Finding:** `m.SIMAN.StringEvaluateFormula("expr")` evaluates any Arena expression against the ended run, *before*
  `m.End()` resets it: variables, arrays (`Inbound(1)`), expressions (`PlanRate(4, 8)`), built-ins (`NREP`,
  `NQ(...)`), formulas (`MN(...)`). Fallback: `SIMAN.VariableValue(SIMAN.SymbolNumber(name, 0, 0), i1, i2)`.
  `ISIMAN` also has `OutputStatisticValue(n)`, `DStatAverage/Minimum/Maximum(n)`, `ExpressionValue(n)`.
- **Limit:** values are those at the end of the **last** replication. For a property over all replications, keep it in
  a variable with Clear Option **None** (e.g. `InbMin = MN(InbMin, ...)`), which survives between replications.
- **CLI change:** `run model.doe --reps N --show EXPR ...` returns `"values"`; `run_tests.py ... --show EXPR` prints
  them per scenario.

### 29. 2-D expressions are stored column by column

- **Finding:** an Expression with `Dim1` rows and `Dim2` columns stores cell (r, c) as `Value(k)` with
  k = (c − 1)·Dim1 + r. (The GUI grid shows rows × columns; only the COM index order is column-major.) Comparing
  row-major made a correct table look wrong.
- **Finding:** a grid can hold fewer values than Dim1 × Dim2 (the user's `PlanRate` had 94 of 96) and still compile.
  Count the values when verifying.

### 30. Verify hand-entered tables against the data before relying on them  ⚠

- **Finding:** the user-typed `PlanRate` (strategy R2's LP plan) had one cell 10× too small (pair 4, hour 8: 0.0062
  for 0.062) and two cells missing. All 8 other tables and 32 parameters matched the data CSVs exactly. Check with
  `inspect --full` plus a script against `data\arena\*.csv` and the guide's tables.

### 31. Updates that touch only one repeat row

- **Bug fixed:** `used_names` scanned repeat rows 1, 2, ... and stopped at the first gap, so an update writing only
  row 7 (`Type(7)`, `VName(7)`) declared nothing ("Undefined identifier: InbMin"). It now collects every row number
  present.

### 32. `Model.Close()` can crash Arena

- **Finding:** closing a just-built model raised "The remote procedure call failed": the Arena process died. The next
  CLI call started a fresh Arena and worked; saved files were intact.

### 33. Never let a script write a non-number into a numeric operand

- **Finding:** a mis-parsed argument list made the test runner `set Scen "Initial Value=--show"`; Arena stored it
  (no validation, see 3), and the next run failed at Check with "Invalid Real Number" on `Scen`. The runner's
  `finally` restored `Scen = 1`.
- **Change:** `run_tests.py` rejects non-numeric scenario arguments before touching the model.

---

## Session 2026-11-01 (later): building Stage G (output statistics)

Stage G: 22 Output statistics (Statistic data modules), deletes the Stage A test statistic `T_DayFee`, extends v6 into
v7 (`contracts\arena_specs\stageG.py`). All 13 log-checkable statistics equal the logs in every replication to the
report's printed precision.

### 34. Output statistics: operands and where the values go

- **Finding:** a Statistic of Type Output is `{"Type": "Output", "DExp": <expression>, "DLabel": <report label>}`
  (AdvancedProcess panel). Each row is its own data module.
- **Finding:** the run writes `<model>.out`, the SIMAN summary report: per replication an OUTPUTS block, then
  "Output Summary for N Replications" with Average, Half-width, Minimum, Maximum, # Replications for every Output
  statistic and counter. **Parse the per-replication blocks only up to that header**: the last replication's block
  otherwise runs on into the summary, and its values get overwritten by the averages (this made rep 30 look 2% off).
- **Finding:** in `StringEvaluateFormula`, a statistic's *name* evaluates to its construct number (`O_Service` → 20),
  not its value; use `OVALUE(O_Service)`. An undefined name in a `--show` expression writes an EELINK record to
  `.err` ("Undefined symbol"), which looked like a run error.
- **CLI change:** `run --outputs` returns the summary table; probe errors from `--show` are reported separately as
  `show_errors`. The Statistic data module the build just created is no longer listed as `auto_created`.

### 35. Simultaneous events: never schedule two processes at the same instant  ⚠

- **Finding:** v5, v6 and v7 should give identical Scen 1 results (Stages F and G do nothing under R1). Over 10
  replications they did; over 30, rep 1 already differed: two riders served at 240.0 in v5 were served at 240.5 in v7.
  At t = 240 the FT-B shift logs on (`Wait_To_Log_On` ends) **and** the dispatcher ticks (first creation 0.5, every
  0.5). Arena processes simultaneous events in an order that changed when Stage F's repositioning clock was added. The
  same tie occurs at every shift start (0, 60, 240, 660).
- **Fix:** dispatcher first creation 0.505, so it always runs just after anything scheduled on the half-minute
  (and still after the abandonment scan at x.495), as in the reference (log-ons before matching).
- **Lessons:** (a) give each clock a distinct offset from every other scheduled time, not only from other clocks;
  (b) adding a module that "does nothing" must leave results bit-identical: compare logs replication by replication
  between versions (first differing row) as a regression test; (c) a 10-replication spot check can miss it.

### 36. A model left in run mode blocks every other run  ⚠

- **Finding:** Arena runs one model at a time. A model left in run mode (`Model.State` 12 at time 1080 after a run
  whose `End()` failed inside `safe()`) made `Go()` on another model block for ~2 minutes and return with no run
  (`SIMAN` unavailable, `end_time` null). A test batch looked like an endless simulation loop; the second Arena process
  in Task Manager was a red herring.
- **How found:** `GetActiveObject("Arena.Application")`, then each model's `State` and `SIMAN.RunCurrentTime`;
  `End()` on the stuck model returned it to State 0 and the next run took 0.9 s.
- **CLI change:** `run` ends any model with State ≠ 0 before `Go` (reported as `ended_first`), reports
  "the run did not start" when no run state exists afterwards, and flags a model still in run mode after `End()`.

### 37. Ties among entities, not only among processes

- **Finding:** after 35 the rider logs of v5 and v7 were byte-identical but the driver logs were not: per-group trip
  totals moved between drivers. Remaining ties: (a) the four driver-group Creates all fired at 0.01, so which group got
  IDs 1-30 (and the matching `Home` draws) depended on the tie order; (b) all drivers of a shift group log on at the same
  instant (`Wait_To_Log_On` ending at 0, 60, 240; evening at 660), so their order in the idle queue, which decides who
  gets the first offer, was Arena's tie order.
- **Fix:** Creates at 0.010 / 0.011 / 0.012 / 0.013; log-on delays `+ 0.000001 * DriverID` (B14 and B28). Drivers then
  enter the idle queue in ID order, which is also the reference's tie-break (a stable sort by idle time).
- **Lesson:** byte-compare logs between versions; when only some logs differ, look for entities that become
  simultaneous (batches released together), and give them an explicit, deterministic order.

### 38. Many small edits: one `build` with `updates`, not many `set` calls

- **Finding:** each `set` opens, edits and saves the model; 36 calls over 6 models took over 10 minutes. A spec with
  `"base": model` (no `save_as`) and an `updates` list makes all the edits with one open and one save.
- *Open:* let `set` take several `Module:Operand=Value` edits, and a `--models` list.

---

## Session 2026-11-01 (night): final model, Stage H runs, figures for the report

### 39. Arena's view coordinates are 16-bit  ⚠

- **Finding:** modules can be created at any (x, y) through COM and are stored there, but the flowchart view can only
  show and scroll to -32,768..32,767. `ZoomRegion` asked for y = 52,300 returned `Top = 32767`. The first final layout
  (stages stacked to y = 82,000) had 120 modules a user could never see in the GUI.
- **Change:** `build_final.py` compresses stage spacing (0.8) and lays panels out in two rows around the origin, and
  asserts every module is inside +-32,000.

### 40. Screenshots of Arena: `snap.py`

- **Finding:** the flowchart pane is the model window's child of class `Afx:<module>:8:...`; `AfxFrameOrView140` is
  the spreadsheet. `IView.SplitScreen = False` collapses the *flowchart* to zero height; keep it True and set
  `SplitScreenPercent = 99`. `IView.ZoomRegion(x0, y0, x1, y1)` zooms exactly and `IView.Left/Top/Right/Bottom` read
  back the visible world rectangle, so tiles are placed exactly (no image matching). y grows downwards.
- **Finding:** `CreateText` works for titles; `CreatePolyline` (frames) drew nothing visible.
- A capture reads the screen: anything over Arena's window spoils the tiles (one 44-tile capture came out blank).

### 41. Vensim figures: export SVG, do not screen-stitch

- **Finding:** Vensim PLE ignores `SB_THUMBPOSITION` and line scrolls, its page scrolls have erratic sizes and its
  canvas grows as it scrolls; scroll units are not proportional to pixels; and identical repeated blocks make overlap
  matching ambiguous. Screen-stitching Vensim views was not reliable.
- **Finding:** `View > Export as SVG` writes the whole view as vectors. Automate it with pywinauto
  (`menu_select("View->Export as SVG")` on the main window, matched by title; a transient window has no menu), and wait
  until the file stops growing and ends with `</svg>` before closing Vensim (an early kill left truncated SVGs).
  Render with headless Edge (`--screenshot`, `--window-size`); Edge renders blank above about 25 megapixels.
- **Tool:** `vensim_svg.py model.mdl out_dir [--views ...]`; one temporary single-view copy of the model per view.

### 42. Running many scenarios: one Arena session, no saves

- **Finding:** set `Scen` (`Initial Value`) and `NumberOfReplications` in memory and `Go` again; no save is needed
  between runs. 61 scenarios, 3,020 replications: 473 s. Saving the model after every `set` costs about a minute each
  for a 2.5 MB model.
- **Tool:** `contracts\arena_specs\run_all.py` (also checks end time, conservation of riders and `InbMin`).

### 43. Two builds must never run into the same model at once

- **Finding:** a background build that had not finished, plus a foreground rebuild of the same file, produced a model
  with stages mixed together. A task notification arriving late is the only sure sign a background job ended.

### 44. Recalibrating a built model: write the data in place, then read it back

- **Finding:** new data (Bengaluru recalibration) needs no rebuild. `setdata(module, "Value(k)", v)` on Expressions
  (column-major, see 29) and `"Initial Value(i)"` on Variables, on the open model, then one `Save()`; reading every
  operand back with `getdata` and comparing caught nothing this time, but costs seconds (347 values in 20 modules).
- **Finding:** the data a model depends on is not only its tables. Constants derived from other models' results also
  live in Variables (`IdleRef`, `GrossRate`, income targets) and inside Assign expressions (the part-time log-on minute
  `60` in `Driver_Init`); a threshold can silently change meaning when fares change (`HighFare` 400 separated
  cross-zone trips at the old fares, not at the new). Search the `inspect --full` dump for every number the old data
  produced before trusting a recalibrated model.
- **Tool:** `contracts\arena_specs\push_data.py` (writes all of them from the data files, verifies, reports mismatches).
- **Check:** after the push, 30 replications of Scen 1, 4, 5 against the Python/C++ simulation: Arena service 0.822 vs
  0.812, the same ~1-point offset as in 27, so the push changed data only.

---

---

## Session 2026-11-02: arena-agent (packaging the CLI for any AI agent)

### 45. License type and edition limits
- **Finding:** `Application.LicenseType` returns the `smLicenseType` enum from Arena.exe's type library: 1 Evaluation,
  2 Viewer, 3 Standard, 4 Professional, 5 Education, 6 Template Runner, 7 SIMAN, 8 Runtime, 9 Academic.
- **Finding:** the same value 5 (Education) covers the free Student download, so the type alone cannot say whether a
  model is size-limited. The text report header does: `<user> - License: STUDENT`.
- **Finding:** `IModel.AreDemoLimitsExceeded` exists; arena-agent reads it after every check and run.
- **Open:** Rockwell does not publish the Student cap. Web sources report 150 entities in the system at once, but a
  ~300-module model with well over 150 concurrent entities ran on this STUDENT license; confirm what the property and
  the limit actually are on a fresh Student install.
- **Change:** `edition.py` (status full / limited / unknown, user override `arena-agent edition`), `doctor`.

### 46. Results: the report database has everything
- **Finding:** `<model>.out`'s "Output Summary for N Replications" lists only Outputs and Counters. Tallies (waiting
  times) and time-persistent statistics (queue lengths, utilization) appear only per replication.
- **Finding:** the report database `<model>.db` is SQLite (Arena 16.2) with views `DiscreteTimeStatsQuery` (tallies),
  `ContinuousTimeStatsQuery` (time-persistent), `CounterStatsQuery`, `OutputStatsQuery`: one row per statistic per
  replication, warm-up rows already excluded (`Rep.IsWarmingUp = 0`). Its `BatchMeansHalfWidth` is 2e+20 when
  insufficient (one replication); across-replication intervals are computed from the per-replication values.
- **Change:** `results.py` (mean, t-based 95% half-width, min, max, n), `.out` parsing kept as a fallback.

### 47. More names COM does not declare
- **Finding:** a Create's `Entity Type` ("Undefined identifier: Patient") and Process resources (`Resource Name(i)`)
  are not declared either. A Create also adds a data module `Entity 1`; when the spec names an entity type, renaming
  that module avoids an unused entity type in every report.
- **Change:** both are declared automatically; `Entity 1` is renamed, or removed when the type already exists.

### 48. Choice labels and their stored values (more)
- Process `Action`: Delay -> D, Seize Delay -> SD, Seize Delay Release -> SDR, Delay Release -> DR.
- Record `Type`: Time Interval -> Interval, Time Between -> Between, Entity Statistics -> Entity (Count, Expression
  unchanged). Resource `Type`: Based on Schedule -> Schedule.
- Schedule durations are the repeat rows `Capacity(i)` (the value) and `Duration(i)`; Type `Capacity` or `Arrival`.

### 49. Run Setup through IModel
- **Finding:** `NumberOfReplications`, `ReplicationLength`, `ReplicationLengthTimeUnits`, `WarmUpPeriod`,
  `WarmUpPeriodTimeUnits`, `BaseTimeUnits`, `HoursPerDay`, `TerminatingCondition` are read/write properties; time units
  use `smTimeUnits` (0 days, 1 hours, 2 minutes, 3 seconds). Values read back as strings. (Closes the Run Setup open
  item.)

### 50. Arena's COM server location
- **Finding:** `HKCR\Arena.Application\CLSID` -> `HKCR\CLSID\{...}\LocalServer32` gives Arena.exe's path, so the
  install folder (template references, Blocks.txt, Elements.txt) needs no hard-coded path.

## Open items (to try next)

- Lint `AQUE`/`SAQUE`/`AG`/`SAG`/`ATTR` calls for a bare attribute name (22).
- `verify` command: compare a model's tables/parameters with CSV data (30; `push_data.py` does it for one model, 44).
- `set` could validate numeric operands (Initial Value, Value(k)) before writing (33).
- Declare names that are only read in expressions (8).
- Confirm whether editing a Hold's queue fields drops `QLabel` connections too (7).
- Confirm the Student edition's real limit and what `AreDemoLimitsExceeded` reports (45).
- Test on Arena versions other than 16.20 (COM names, report database format).
