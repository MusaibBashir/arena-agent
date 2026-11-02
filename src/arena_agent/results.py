"""Run results: every statistic of the last run, per replication and across replications.

Primary source: the report database Arena writes next to the model (<model>.db, SQLite, Arena 16 and later). Its
views DiscreteTimeStatsQuery (tallies: waiting times, times in system), ContinuousTimeStatsQuery (time-persistent:
queue lengths, WIP, number busy, utilization), CounterStatsQuery and OutputStatsQuery hold one row per statistic per
replication; warm-up rows are already excluded. Across replications this module reports the mean, the 95% confidence
half-width (t distribution, n - 1 degrees of freedom, as Arena's own report), the minimum and maximum of the
replication values, and n.

Fallback (no .db, e.g. older Arena with an Access database): the SIMAN summary report <model>.out, which has the
across-replication table for Outputs and Counters only.
"""
import math
import os
import sqlite3
import re
import statistics

VIEWS = (("DiscreteTimeStatsQuery", "Average", "tally"), ("ContinuousTimeStatsQuery", "Average", "time-persistent"),
         ("CounterStatsQuery", "RecordedValue", "counter"), ("OutputStatsQuery", "RecordedValue", "output"))
# t(0.975, df) for df = 1..30; beyond that the normal value is close enough
T975 = [12.706, 4.303, 3.182, 2.776, 2.571, 2.447, 2.365, 2.306, 2.262, 2.228, 2.201, 2.179, 2.160, 2.145, 2.131,
        2.120, 2.110, 2.101, 2.093, 2.086, 2.080, 2.074, 2.069, 2.064, 2.060, 2.056, 2.052, 2.048, 2.045, 2.042]


def t975(df):
    if df <= 0:
        return float("nan")
    if df <= 30:
        return T975[df - 1]
    return 1.960 + 2.4 / df  # within 0.002 of the exact value for df > 30


def summarize(values):
    vals = [v for v in values if v is not None and not (isinstance(v, float) and math.isnan(v))]
    n = len(vals)
    if not n:
        return {"average": None, "half_width": None, "min": None, "max": None, "n": 0}
    mean = sum(vals) / n
    hw = t975(n - 1) * statistics.stdev(vals) / math.sqrt(n) if n > 1 else None
    return {"average": mean, "half_width": hw, "min": min(vals), "max": max(vals), "n": n}


def read_db(path, per_replication=False):
    """{"Examination.Queue.Waiting Time": {"kind", "source", "average", "half_width", "min", "max", "n"}, ...}
    from the report database at path. Only the latest run in the database is used."""
    con = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    try:
        res = {}
        for view, col, k in VIEWS:
            try:
                rows = con.execute(f'SELECT [Project RunDateTime], Replication, Name, Type, Source, [{col}] '
                                   f'FROM {view}').fetchall()
            except sqlite3.Error:
                continue
            if not rows:
                continue
            latest = max(r[0] for r in rows)
            by = {}
            for when, rep, name, typ, src, val in rows:
                if when != latest:
                    continue
                key = name if k in ("output", "counter") else f"{name}.{typ}"  # outputs/counters have unique names
                by.setdefault((key, src), {})[rep] = val
            for (key, src), reps in by.items():
                rec = {"kind": k, "source": src, **summarize([reps[r] for r in sorted(reps)])}
                if per_replication:
                    rec["replications"] = [reps[r] for r in sorted(reps)]
                res[key] = rec
        return res
    finally:
        con.close()


def drop_empty(res):
    """Leave out statistics with no observations in any replication (unused entity types and the like)."""
    return {k: v for k, v in res.items() if not (v["n"] == 0 or (v["kind"] == "tally" and v["average"] is None))}


def read(model_path, since=0, per_replication=False, include_empty=False):
    base = os.path.splitext(model_path)[0]
    db = base + ".db"
    if os.path.exists(db) and os.path.getmtime(db) >= since:
        try:
            res = read_db(db, per_replication)
            if res:
                return {"source": db, "statistics": res if include_empty else drop_empty(res)}
        except sqlite3.DatabaseError:
            pass  # not SQLite (older Arena): fall back to the text report
    out = base + ".out"
    if os.path.exists(out) and os.path.getmtime(out) >= since:
        return {"source": out, "statistics": parse_out(open(out, errors="replace").read()),
                "note": "from the text report: only Outputs and Counters are summarised across replications"}
    return {"source": None, "statistics": {}, "note": "no results from this run (no .db or .out written)"}


def report_license(model_path):
    """The license line Arena prints in the text report header, e.g. "STUDENT"; None if there is no report."""
    out = os.path.splitext(model_path)[0] + ".out"
    if not os.path.exists(out):
        return None
    with open(out, errors="replace") as f:
        for _ in range(5):
            line = f.readline()
            if "License:" in line:
                return line.split("License:", 1)[1].strip() or None
    return None


NUM = r"(-?[\d.]+(?:E[-+]?\d+)?|\(Insuf\)|\(Correl\)|--)"


def _num(x):
    try:
        return float(x)
    except ValueError:
        return None if x == "--" else x


def parse_out(txt):
    """The SIMAN summary report (<model>.out). With several replications, the across-replication table after "Output
    Summary for N Replications": {identifier: {average, half_width, min, max, reps}} (every Tally, Dstat, Output and
    Counter). The per-replication sections come before it; parse only after that header, or the last replication's
    values get overwritten. With one replication, the single report's TALLY / DISCRETE-CHANGE / OUTPUTS / COUNTERS
    sections."""
    res = {}
    if "Output Summary for" in txt:
        tail = txt.split("Output Summary for", 1)[1]
        section = None
        for line in tail.splitlines():
            head = line.strip()
            if head.isupper() and head.replace(" ", "").replace("-", "").isalpha():
                section = head.title()
                continue
            mm = re.match(r"^(\S[^\n]*?)\s{2,}" + r"\s+".join([NUM] * 4) + r"\s+(\d+)\s*$", line)
            if mm:
                res[mm.group(1).strip()] = {"section": section, "average": _num(mm.group(2)),
                                            "half_width": _num(mm.group(3)), "min": _num(mm.group(4)),
                                            "max": _num(mm.group(5)), "reps": int(mm.group(6))}
        return res
    section, cols = None, None
    for line in txt.splitlines():
        head = line.strip()
        if head.startswith(("TALLY VARIABLES", "DISCRETE-CHANGE VARIABLES", "OUTPUTS", "COUNTERS")):
            section = head.title()
            continue
        if not section:
            continue
        if re.match(r"^Identifier\s", head):
            cols = [c.lower().replace(" ", "_").replace("#", "n") for c in re.split(r"\s{2,}", head)[1:]]
            continue
        mm = re.match(r"^(\S[^\n]*?)\s{2,}(\S.*)$", line)
        if mm and cols:
            vals = re.findall(NUM, mm.group(2))
            if len(vals) >= 1 and len(vals) <= len(cols):
                res[mm.group(1).strip()] = {"section": section, **{c: _num(v) for c, v in zip(cols, vals)}}
    return res
