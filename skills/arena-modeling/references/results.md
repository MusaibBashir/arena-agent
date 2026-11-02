# Results and output analysis

## What `run_model` returns

`statistics` maps each statistic to `{kind, source, average, half_width, min, max, n}`:

- `average`: mean over replications of the per-replication value.
- `half_width`: 95% confidence half-width, t distribution with n - 1 degrees of freedom (as Arena's own report).
  The interval is average +- half_width. `null` with one replication.
- `min` / `max`: smallest and largest replication value (not the smallest single observation).
- `n`: replications.

Kinds and typical names:

| kind | examples | meaning |
|---|---|---|
| tally | `Exam.Queue.Waiting Time`, `Patient.Total Time`, `Patient.Wait Time`, `<Record tally>.Interval` | average of observations within a replication |
| time-persistent | `Exam.Queue.Number Waiting`, `Doctor.Instantaneous Utilization`, `Doctor.Number Busy`, `Patient.WIP` | time-weighted average |
| counter | `<Record counter>` | count per replication |
| output | `Doctor.ScheduledUtilization`, `Patient.NumberOut`, `System.NumberOut`, Statistic outputs | value at the end of each replication |

`per_replication=true` adds every replication's value (for paired comparisons, plots, or checking outliers).
`measures=["Waiting", "Utilization"]` keeps only matching statistics. `get_results` reads the last run again without
running.

## Choosing run settings

- **Terminating systems** (a clinic day, a shift): replication length = the day; no warm-up; replications = days.
- **Steady-state questions** (long-run average of a system that never empties): long replications plus a warm-up
  period long enough for queues to stabilise (plot a queue length over time, or compare halves of a long run); report
  that warm-up was used.
- **Replications**: start with 10; if a half-width is wider than ~10% of its average, or wider than the differences you
  must detect, increase. Rough rule: n_needed ~ n * (half_width / target_half_width)^2.
- Always set `base_time_units` and the replication length units explicitly; say which units the results are in
  (times are in base time units).

## Comparing scenarios

`run_scenarios` with the same replications for each scenario. Two scenarios differ significantly at ~95% when their
intervals do not overlap; overlapping intervals do not prove they are equal. For a sharper comparison use
`per_replication=true` and compare paired differences (Arena uses the same random number streams per replication in
each run, so replication i of two scenarios is paired): mean difference +- t * sd / sqrt(n).

## Sanity checks before reporting

- Utilization ~ arrival rate x mean service time / number of servers (per resource).
- Flow: `NumberIn` ~ `NumberOut` + WIP at the end.
- Simple queue (M/M/c): compare waiting time with the Erlang C formula; a terminating run that starts empty will show
  less waiting than the steady-state value.
- Utilization near 1 with growing queues means the system is unstable: say so instead of reporting a waiting time.
- `edition_limit_exceeded` or a run that stops early (`end_time` short of the replication length) invalidates results.

## Reporting

State: the system and assumptions (distributions, parameters, run length, warm-up, replications), each requested
measure as average +- half-width with units, the comparison and recommendation if asked, and the model file path.
