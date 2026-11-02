# Gotchas: Arena through COM

All verified on Arena 16.20. Most are handled by arena-agent already; they are listed so you recognise the symptoms.
Background and evidence for each: `arena_guide("discoveries")`.

## Building

1. **Unknown choice labels are stored without error.** Choice operands take the dialog label ("N-way by Condition") and
   Arena stores an internal value (NIf). A typo is stored verbatim and only fails at check. build/set read every value
   back: act on `errors` ("not a valid choice") and on `warnings` that show an unexpected readback.
2. **Names are not declared through COM.** Typing a new name in an Arena dialog creates its data module; COM does not,
   and check fails with `Undefined identifier: X`. arena-agent declares names *assigned* in Assign/ReadWrite, queues of
   Hold/Search/Remove, Process resources and Create entity types. Names only *read* in expressions go in the spec's
   `declare` or as explicit data modules.
3. **SIMAN reserved words** (`Wait`, `Group`, `Queue`, `Station`, `Delay`, `Count`, `Batch`, ... every block and
   element name) as attribute/variable names compile with only a warning, then the run stops at time 0. The tools
   refuse them; rename (`RWait`, `ShiftGrp`).
4. **Repeat rows are `Operand(i)`**, and writing row i creates missing rows in between with defaults: write rows 1..n
   in order (the spec's `rows` / `cases` / `resources` do).
5. **Exit and entry points are hidden operands.** Hold's entry is `QLabel`; a connection to its `HoldLabel` is accepted
   and then silently deleted by check (reported as `dropped_connections`). Use the spec's `exit` names.
6. **Arena adds data modules by itself**: Create -> Entity (renamed to the spec's entity type), ReadWrite -> `File 1`
   (fails check until edited; delete it with the spec's `delete`), Hold/Search -> a queue, Batch -> `<name>.Queue`.
7. **Changing a Hold's queue settings can drop its incoming connections.** Re-check after editing a Hold.
8. **View coordinates are 16-bit.** Modules can be placed anywhere through COM, but the GUI only shows -32,768..32,767.
   Keep layouts inside +-32,000; compress spacing for big models.
9. **Functions taking an attribute number** (`AQUE`, `SAQUE`, `AG`, `SAG`, `ATTR`, `ED`, `EXPR`) need `NSYM(name)`.
   A bare name compiles but is evaluated as the attribute's *value*; the run stops with "Attribute number 0 is not in
   valid range".
10. **2-D Expression tables are stored column by column**: cell (r, c) is `Value((c-1)*Dim1 + r)`. A grid may hold
    fewer values than Dim1 x Dim2 and still compile: count them.
11. **Never write a non-number into a numeric operand** (e.g. a mis-parsed argument into `Initial Value`): Arena stores
    it and the next check fails with "Invalid Real Number".

## Running

12. **One model runs at a time.** A model left in run mode blocks `Go` on every other model for ~2 minutes and then
    returns without running. `run_model` ends stale runs first (`ended_first`) and reports "the run did not start".
13. **Simultaneous events are ordered by Arena's tie rules.** Two processes or entities scheduled at the same instant
    can swap order when an unrelated module is added, changing results. Give clocks distinct offsets (first creation
    0.505 instead of 0.5) and simultaneous entities an explicit order (`+ 0.000001 * ID`). Adding a module that "does
    nothing" must leave results identical: compare per-replication results between versions.
14. **`show` expressions are evaluated at the end of the last replication only.** For a property over all
    replications, keep it in a variable with Clear Option `None`, or use output statistics / Record.
15. **A statistic's name evaluates to its number**, not its value, in `show`: use `OVALUE(Name)` for outputs,
    `TAVG(Name)` for tallies, `DAVG(Name)` for time-persistent statistics.
16. **Scenario runs need no save.** Set values in memory and run again (`run_scenarios`); saving a large model after
    every change costs about a minute each.

## Files and Arena itself

17. **Close a model before deleting or replacing its files**; Arena keeps them locked while the model is open.
18. **`Model.Close()` can crash Arena** ("The remote procedure call failed"). Saved files are intact; the next call
    starts a fresh Arena. arena-agent reconnects on its own.
19. **Two edits must never run into the same model at once.** The MCP server serialises calls; do not also run CLI
    builds on the same file from a background shell at the same time.
20. **Screenshots read the screen.** Anything covering Arena's window spoils `screenshot_model`.
21. Arena's report database is `<model>.db` (SQLite in Arena 16+), the text report `<model>.out`, errors `<model>.err`
    (binary; arena-agent decodes it and maps each record to its module).
