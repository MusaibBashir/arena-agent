# Build spec

`build_model(spec)` (MCP) or `arena-agent build spec.json` (CLI). One spec creates a new model or extends an existing
one, sets every module, declares the names they use, connects them, compiles and saves.

```json
{
  "base": "C:/work/clinic_v1.doe",       // optional: extend this model. It is saved as save_as FIRST; base is never changed
  "save_as": "C:/work/clinic_v2.doe",    // required for a new model; where to save
  "run_setup": {"replications": 10, "replication_length": 480, "replication_length_units": "minutes",
                "warm_up": 0, "warm_up_units": "minutes", "base_time_units": "minutes"},
  "updates": [{"name": "Doctor", "data": {"Capacity": "4"}}],          // change existing modules, by Name
  "modules": [
    {"id": "arrive", "panel": "BasicProcess", "type": "Create", "x": 0, "y": 0,
     "data": {"Name": "Patients Arrive", "Entity Type": "Patient", "Interarrival Type": "Random",
              "Value": "5", "Units": "Minutes"}},
    {"id": "init", "type": "Assign", "x": 2000, "y": 0, "data": {"Name": "Init"},
     "rows": [{"Type": "Attribute", "AName": "ArriveAt", "Value": "TNOW"},          // repeat-group rows, in order
              {"Type": "Variable",  "VName": "N",        "Value": "N + 1"}]},
    {"id": "route", "type": "Decide", "x": 4000, "y": 0,
     "data": {"Name": "Route", "Type": "N-way by Condition"},
     "cases": [{"N If": "Expression", "N Value": "Acuity == 1"},
               {"N If": "Expression", "N Value": "Acuity == 2"}]},
    {"id": "exam", "type": "Process", "x": 6000, "y": 0,
     "data": {"Name": "Exam", "Action": "Seize Delay Release", "DelayType": "Expression",
              "Expression": "EXPO(12)", "Units": "Minutes"},
     "resources": [{"Resource Type": "Resource", "Resource Name": "Doctor", "Quantity": "1"}]},
    {"id": "docs", "type": "Resource", "data": {"Name": "Doctor", "Capacity": "3"}}
  ],
  "connections": [
    {"from": "arrive", "to": "init"},                       // default exit
    {"from": "route", "to": "exam", "exit": "case:1"},
    {"from": "route", "to": "other", "exit": "else"}
  ],
  "declare": {"attributes": ["Acuity"], "variables": []},  // extra names only READ in expressions
  "declare_at": [0, -4000],                                // where auto-declared data modules are placed
  "delete": ["File 1"],                                    // stray modules to remove (see auto_created)
  "shapes": [{"text": "Triage", "x": 0, "y": -1500}],     // optional titles on the flowchart
  "check": true                                            // compile at the end (default)
}
```

(The `//` comments are for reading only; real JSON has none.)

## Fields

- `panel` defaults to `BasicProcess`. Hold, Search, Remove, Delay, Seize, Release, ReadWrite, Expression, File,
  Statistic, Signal ... are on `AdvancedProcess`. Panel names are internal names: `list_panels`.
- `type` is the module type name (`list_module_types`), `data` maps operand names (`module_operands`,
  `template_reference`) to string values.
- `rows`, `cases`, `resources` write repeat groups: row i becomes `Operand(i)`. Always give rows 1..n in order (rows
  in between would get defaults). You can also address one row directly in `data`/`updates`: `"Value(3)": "7"`.
- `id` is how connections refer to the module; connections can also name existing modules by their Name.
- `x`, `y`: model units. Keep every module inside -32,000..32,000 (Arena's view coordinates are 16-bit; modules
  outside can never be seen in the GUI). A spacing of ~2,000-2,500 between modules in a row reads well.
- Data modules (Resource, Variable, Queue, Entity, Attribute, Expression, Statistic, Schedule ...) need no x/y.

## Exits

`next` (default), `true` / `false` (2-way Decide), `case:N` and `else` (N-way Decide), `original` / `duplicate`
(Separate), `found` / `notfound` (Search), `removed` (Remove; `original` is the remover).

## Names declared automatically

Arena's GUI creates data modules when you type a new name in a dialog; COM does not, and Check then fails with
"Undefined identifier". build_model / set_module declare:

- attributes and variables assigned in Assign rows and ReadWrite rows,
- queues named in Hold `QName` and Search/Remove `Queue Name`,
- resources named in Process rows (`Resource Name(i)` with `Resource Type(i)` = Resource),
- entity types named in Create `Entity Type` (Arena's own auto-created `Entity 1` is renamed to it).

Names that are only *read* (an attribute used in a Decide condition before any Assign sets it, a variable used in an
expression) must go in `declare`, or be created as explicit data modules (e.g. `{"type": "Variable", "data":
{"Name": "Rate", "Initial Value": "5"}}`).

## Output

`ok`, `errors` (operands that could not be set, invalid choices), `warnings` (values that read back differently),
`declared`, `auto_created` (data modules Arena added on its own), `deleted`, `check_errors` (each with `message`,
`level`, and `module`/`type` when Arena names the faulty module; SIMAN compile errors carry the generated `code`),
`dropped_connections` (connections Arena's compiler deleted).
