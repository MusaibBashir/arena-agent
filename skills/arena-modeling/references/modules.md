# Module recipes

Operand names and values that work through COM. **Verified** recipes were built, compiled and run with arena-agent on
Arena 16.20. For anything else, read `template_reference(<type>)` first: it lists every operand, which ones repeat, and
the hidden exit/entry points. Choice operands take the display label; Arena stores an internal value (shown after ->).
An unknown label is stored verbatim **without error** and only fails at check, so build/set flag values that read back
wrong.

## Basic Process panel (`BasicProcess`)

**Create** (verified)
```json
{"type": "Create", "data": {"Name": "Arrivals", "Entity Type": "Patient", "Interarrival Type": "Random",
 "Value": "5", "Units": "Minutes", "Batch Size": "1", "First Creation": "0.0", "Max Batches": "Infinite"}}
```
Interarrival Type (all verified): `Random` (exponential with mean Value), `Constant`, `Expression` (operand
`Expression`, e.g. `"UNIF(3,7)"`), `Schedule` (operand `Schedule`; needs a Schedule data module of Type `Arrival`). Units: Seconds, Minutes, Hours, Days.

**Process** (verified)
```json
{"type": "Process", "data": {"Name": "Exam", "Action": "Seize Delay Release", "DelayType": "Triangular",
 "Min": "5", "Value": "10", "Max": "20", "Units": "Minutes", "Priority": "Medium(2)"},
 "resources": [{"Resource Type": "Resource", "Resource Name": "Doctor", "Quantity": "1"}]}
```
Action: `Delay` -> D, `Seize Delay` -> SD, `Seize Delay Release` -> SDR, `Delay Release` -> DR.
DelayType (Triangular, Normal, Expression verified): `Triangular` (Min, Value = mode, Max), `Normal` (Value = mean, StDev), `Uniform` (Min, Max), `Constant`
(Value), `Expression` (Expression, e.g. `"EXPO(12)"`, `"LOGN(10, 3)"`, `"ERLA(4, 2)"`). The queue is named
`<Process name>.Queue` and its statistics appear as `<Process name>.Queue.Waiting Time` / `.Number Waiting`.

**Resource** (data module; verified)
```json
{"type": "Resource", "data": {"Name": "Doctor", "Capacity": "3"}}
```
Capacity varying over time (verified): `{"Name": "Clerk", "Type": "Based on Schedule", "Schedule": "ClerkSched",
"ScheduleRule": "Wait"}` -> Schedule, with a Schedule data module of Type `Capacity` (below).

**Decide** (all four verified)
- 2-way by chance: `{"Type": "2-way by Chance", "Percent True": "20"}` -> With; exits `true`, `false`.
- 2-way by condition: `{"Type": "2-way by Condition", "If": "Expression", "Value": "Age > 65"}` -> If.
- N-way by chance: `{"Type": "N-way by Chance"}` with `cases: [{"N Percent True": "30"}, {"N Percent True": "50"}]`;
  exits `case:1`, `case:2`, `else`.
- N-way by condition: `{"Type": "N-way by Condition"}` with
  `cases: [{"N If": "Expression", "N Value": "Zone == 1"}, ...]` -> NIf; exits `case:N`, `else`.
  `If` / `N If` can also be `Attribute`, `Variable`, `Entity Type` with their own operands (`ANamed`, `VNamed`, `Is`,
  `Value`); `Expression` is the simplest.

**Assign** (verified)
```json
{"type": "Assign", "data": {"Name": "Init"},
 "rows": [{"Type": "Attribute", "AName": "ArriveAt", "Value": "TNOW"},
          {"Type": "Variable", "VName": "Count", "Value": "Count + 1"},
          {"Type": "Variable Array (1D)", "VName": "Inbound", "Row": "Zone", "Value": "Inbound(Zone) + 1"},
          {"Type": "Other", "OtherName": "Cnt(Group)", "Value": "Cnt(Group) + 1"},
          {"Type": "Entity Type", "TypeName": "Served", "Value": ""}]}
```
Attributes and variables assigned here are declared automatically. Arrays need a Variable data module with rows
(`{"type": "Variable", "data": {"Name": "Inbound", "Rows": "4"}}`) - check the readback.

**Record** (all types verified)
```json
{"type": "Record", "data": {"Name": "Record Time In System"},
 "rows": [{"Type": "Time Interval", "Attribute": "ArriveAt", "Tally Name": "Time In System"}]}
```
`Time Interval` -> Interval (records TNOW - attribute; statistic `Time In System.Interval`). Other types: `Count`
(`Counter Name`, `Value`; statistic `<Counter Name>`), `Expression` (`Value`, `Tally Name`; statistic
`<Tally>.Expression`), `Time Between` -> Between (`Tally Name`; `<Tally>.Between`), `Entity Statistics` -> Entity.

**Dispose** (verified): `{"type": "Dispose", "data": {"Name": "Exit"}}`.

**Batch / Separate** (verified): Batch `{"Type": "Permanent"|"Temporary", "Batch Size": "3", "Rule": "Any Entity"|
"By Attribute", "Attribute": ...}` (Arena adds its queue `<Name>.Queue`); Separate `{"Type": "Duplicate Original",
"Number": "1"}` -> Duplicate (exits `original`, `duplicate`) or `"Split Existing Batch"` -> Split.

**Variable** (data; verified): `{"Name": "Rate", "Initial Value": "5"}`; arrays: `"Rows"`, `"Columns"`, initial
values `"Initial Value(i)"` (a 1-D array `{"Name": "Tot", "Rows": "2"}` is assigned with Assign type
`Variable Array (1D)`, `Row`). Changing a variable's Initial Value is how scenarios are usually switched. Clear Option
`None` keeps a value across replications (useful for a min/max over all replications).

**Schedule** (data; verified): durations are repeat rows `Capacity(i)` (the value) and `Duration(i)`:
```json
{"type": "Schedule", "data": {"Name": "ClerkSched", "Type": "Capacity", "Units": "Hours"},
 "rows": [{"Capacity": "1", "Duration": "4"}, {"Capacity": "2", "Duration": "4"}]}
```
Type `Capacity` for a resource (`Based on Schedule`), `Arrival` for a Create with Interarrival Type `Schedule`
(`"Schedule": "ArrSched"`; values are arrivals per hour, the Create's Units).

## Advanced Process panel (`AdvancedProcess`)

Used in larger models (verified in a 300-module ride-hailing model):
- **Hold**: `{"Type": "Scan for Condition", "Condition": "NQ(Idle.Queue) > 0", "QName": "Wait_Q"}` or
  `"Infinite Hold"` -> Infinite (released by Remove/Search) or `"Wait for Signal"`. **Hold's entry point is `QLabel`**,
  handled automatically.
- **Search**: `{"Type": "Search a Queue", "Queue Name": "Idle.Queue", "Starting Value": "1", "Ending Value": "NQ",
  "Search Condition": "Zone == myZone"}` -> Queue; exits `found`, `notfound`. Sets `J` to the rank found.
- **Remove**: `{"Queue Name": "Idle.Queue", "Rank of Entity": "J"}`; exits `original` (the remover) and `removed`.
- **Delay**: `{"Delay Time": "EXPO(5)", "Units": "Minutes"}`.
- **Seize / Release**: separate seize and release around several steps.
- **Expression** (data): `{"Name": "Fare", "Dim1": "4", "Dim2": "3"}` with `"Value(k)"`; 2-D tables are stored
  **column by column**: cell (r, c) is `Value((c-1)*Dim1 + r)`.
- **Statistic** (data), output statistics: `{"Name": "O_Service", "Type": "Output", "DExp": "Served / Arrived",
  "DLabel": "O_Service"}`; read with `OVALUE(O_Service)` and reported across replications.
- **ReadWrite**: write logs, `{"Type": "Write to File", ...}` -> WriteFile; it adds a `File 1` data module that
  fails check until edited or deleted.

## Built-in expressions worth knowing

`TNOW` (current time), `NQ(<queue>)` (number in queue), `NR(<resource>)` (number busy), `MR(<resource>)`
(capacity), `NREP` (replication number), `EXPO`, `NORM`, `TRIA`, `UNIF`, `LOGN`, `ERLA`, `GAMM`, `WEIB`, `DISC`
(discrete empirical: `DISC(0.3, 1, 0.8, 2, 1.0, 3)`), `MN` / `MX` (min / max). Functions that take an attribute
*number* (`AQUE`, `SAQUE`, `AG`, `ATTR`) need `NSYM(name)`. Reference: `Variables and Functions Guide.pdf` in Arena's
`Online Books` folder.
