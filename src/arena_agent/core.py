"""Drive Rockwell Arena through its COM automation object (Arena.Application).

Every public function takes the Arena application object first and returns a JSON-serialisable dict. Nothing here
prints: the CLI prints the result, the MCP server returns it.
"""
import json
import os
import re
import time
import winreg

import pythoncom
import win32com.client as wc

from . import edition
from . import results as resultsmod

SEARCH_NAME = 2  # smFindName
CLSID_KEY = r"Arena.Application\CLSID"

# Friendly exit names -> exit operand. Arena's exit points are hidden operands (see BasicProcess.txt /
# AdvancedProcess.txt in the Arena folder).
EXITS = {
    "next": "Next Label", "true": "Next Label Yes", "false": "Next Label No", "else": "Next Label No",
    "found": "Next Label Found", "notfound": "Next Label None", "none": "Next Label None",
    "removed": "Next Label Removed", "duplicate": "Next Label",
}
ORIGINAL_EXIT = {"Separate": "Next Label Orig", "Clone": "Next Label Orig", "Remove": "Next Label"}
# Entry points: most modules use "Label"; Hold's is "QLabel". (A connection to Hold's "HoldLabel" is accepted but
# Check() silently deletes it, so it must not be tried.)
ENTRIES = {"Hold": ("QLabel",)}

# Operands whose display label Arena maps to an internal value; anything else is stored verbatim.
CHOICES = {
    ("Decide", "Type"): {"With", "If", "NWith", "NIf"},
    ("Separate", "Type"): {"Split", "Duplicate"},
    ("Hold", "Type"): {"Wait", "Scan", "Infinite"},
    ("Search", "Type"): {"Batch", "Queue", "Expression"},
    ("ReadWrite", "Type"): {"ReadFile", "WriteFile", "ReadKeyboard", "WriteScreen"},
    ("Create", "Interarrival Type"): {"Random", "Schedule", "Constant", "Expression"},
    ("Process", "Action"): {"D", "SD", "SDR", "DR"},
    ("Process", "Type"): {"Standard", "Submodel"},
    ("Process", "DelayType"): {"Triangular", "Normal", "Uniform", "Constant", "Expression"},
}
# Display labels Arena stores under another name (read back differently, but correct)
MAPPED = {("Record", "Type"): {"Time Interval": "Interval", "Time Between": "Between", "Entity Statistics": "Entity"},
          ("Resource", "Type"): {"Fixed Capacity": "Capacity", "Based on Schedule": "Schedule"}}
# Data-module types that declare a name, and the flowchart operands that use one.
DECLARERS = {"attribute": ("BasicProcess", "Attribute"), "variable": ("BasicProcess", "Variable"),
             "queue": ("BasicProcess", "Queue"), "resource": ("BasicProcess", "Resource"),
             "entity": ("BasicProcess", "Entity")}
TIME_UNITS = {"days": 0, "hours": 1, "minutes": 2, "seconds": 3}


class ArenaError(Exception):
    pass


def arena_dir():
    """Arena's install folder: ARENA_DIR if set, else the folder of the registered COM server (Arena.exe)."""
    if os.environ.get("ARENA_DIR"):
        return os.environ["ARENA_DIR"]
    try:
        clsid = winreg.QueryValue(winreg.HKEY_CLASSES_ROOT, CLSID_KEY)
        exe = winreg.QueryValue(winreg.HKEY_CLASSES_ROOT, rf"CLSID\{clsid}\LocalServer32")
        return os.path.dirname(exe.strip().strip('"').split('"')[0])
    except OSError:
        return None


_reserved = None


def reserved_words():
    """SIMAN block and element names (Blocks.txt, Elements.txt in the Arena folder). An attribute or variable with one
    of these names compiles with only a warning, but the run then stops at time 0. SIMAN is case-insensitive."""
    global _reserved
    if _reserved is None:
        _reserved = set()
        d = arena_dir() or ""
        for f in ("Blocks.txt", "Elements.txt"):
            p = os.path.join(d, f)
            if os.path.exists(p):
                _reserved |= {w.lower() for w in re.findall(r"^Module:\s*(\w+)", open(p, errors="replace").read(),
                                                            re.M)}
    return _reserved


def reserved_clashes(names):
    rw = reserved_words()
    return sorted(n for n in names if n.split(".")[0].lower() in rw and not n.lower().endswith(".queue"))


def app(visible=True):
    a = wc.Dispatch("Arena.Application")  # attaches to running Arena or launches it
    a.Visible = visible
    return a


def safe(f, default=None):
    try:
        return f()
    except Exception:
        return default


def mdef(panel, name):
    defs = panel.ModuleDefinitions
    i = defs.Find(SEARCH_NAME, name, 1)
    if not i:
        raise ArenaError(f"panel {panel.Name!r} has no module type {name!r} (list them with defs)")
    return defs.Item(i)


def setdata(mod, operand, value):
    o = mod._oleobj_
    o.Invoke(o.GetIDsOfNames("Data"), 0, pythoncom.DISPATCH_PROPERTYPUT, 0, operand, value)


def getdata(mod, operand):
    return safe(lambda: mod.Data(operand))


def open_model(a, path):
    path = os.path.abspath(path)
    for i in range(1, a.Models.Count + 1):
        m = a.Models.Item(i)
        if m.FullName.lower() == path.lower():
            return m
    if not os.path.exists(path):
        raise ArenaError(f"no such model file: {path}")
    return a.Models.Open(path)


def modules_by_name(m):
    res = {}
    for i in range(1, m.Modules.Count + 1):
        md = m.Modules.Item(i)
        n = getdata(md, "Name")
        if n:
            res.setdefault(n, md)
    return res


def kind(mod):
    return safe(lambda: mod.Definition.Name, "")


def expand(ms):
    """A module spec's data as an ordered list of (operand, value). "rows" lists repeat-group rows in order:
    {"rows": [{"Type": "Attribute", "AName": "x", "Value": "1"}, ...]} -> Type(1), AName(1), Value(1), Type(2) ...
    "cases" does the same for N-way Decide conditions (N If, N Value), "resources" for Process resources."""
    items = list(ms.get("data", {}).items())
    for key in ("rows", "cases", "resources"):
        for i, row in enumerate(ms.get(key, []), 1):
            items += [(f"{k}({i})", v) for k, v in row.items()]
    return [(k, str(v)) for k, v in items]


def apply_data(mod, items, report, label):
    """Set operands in order, read each back, and record anything Arena did not keep."""
    t = kind(mod)
    for k, v in items:
        try:
            setdata(mod, k, v)
        except pythoncom.com_error as e:
            report["errors"].append(f"{label}: cannot set {k}={v!r} ({e.args[1] if len(e.args) > 1 else e})")
            continue
        got = getdata(mod, k)
        base = re.sub(r"\(\d+\)$", "", k)
        allowed = CHOICES.get((t, base))
        if allowed is not None and got not in allowed:
            report["errors"].append(f"{label}: {k}={v!r} is not a valid choice (stored {got!r}; valid {sorted(allowed)})")
        elif allowed is None and got is not None and got != v and k != "Name" and                 MAPPED.get((t, base), {}).get(v) != got:
            report["warnings"].append(f"{label}: {k} set to {v!r} but reads back {got!r}")


def used_names(ms_items, t):
    """Attribute, variable, queue, resource and entity-type names a module defines, so they can be declared."""
    attrs, vars_, queues, res, ents = set(), set(), set(), set(), set()
    d = dict(ms_items)
    if t == "Create" and d.get("Entity Type"):
        ents.add(d["Entity Type"])
    if t == "Hold" and d.get("QName"):
        queues.add(d["QName"])
    if t in ("Search", "Remove", "Search and Remove") and d.get("Queue Name"):
        queues.add(d["Queue Name"])

    def rows(op):  # row numbers present for a repeat operand: "Type" -> 1 for plain "Type", n for "Type(n)"
        found = {1} if op in d else set()
        found |= {int(mm.group(1)) for k in d for mm in [re.fullmatch(re.escape(op) + r"\((\d+)\)", k)] if mm}
        return sorted(found)

    def val(op, i):
        return d.get(f"{op}({i})", d.get(op) if i == 1 else None)

    if t == "Assign":  # every row present, not only 1..n (an update may touch row 7 alone)
        for i in rows("Type"):
            typ = val("Type", i)
            if typ == "Attribute" and val("AName", i):
                attrs.add(val("AName", i))
            if typ == "Variable" and val("VName", i):
                vars_.add(val("VName", i))
    if t == "ReadWrite":
        for i in rows("Variable Type"):
            if val("Variable Type", i) == "Attribute" and val("Att", i):
                attrs.add(val("Att", i))
    if t == "Process":  # resources named in a Seize action are not declared through COM either
        for i in rows("Resource Name"):
            if (val("Resource Type", i) or "Resource") == "Resource" and val("Resource Name", i):
                res.add(val("Resource Name", i))
    return attrs, vars_, queues, res, ents


def declare(a, m, existing, names, what, x, y, report):
    """Create Attribute / Variable / Queue / Resource / Entity data modules for names the model does not define yet."""
    pn, tn = DECLARERS[what]
    panel = a.Panels.Attach(pn)
    d = mdef(panel, tn)
    for n in sorted(names):
        if n in existing:
            continue
        mod = m.Modules.Create(panel, d, x, y)
        setdata(mod, "Name", n)
        existing[n] = mod
        report["declared"].append(f"{what} {n}")


def connect(m, made, c, report):
    src, dst = made[c["from"]], made[c["to"]]
    ex = c.get("exit", "next").lower()
    idx = None
    if ex.startswith("case"):
        operand, idx = "N Next Label Yes", int(ex.split(":")[1])
    elif ex == "original":
        operand = ORIGINAL_EXIT.get(kind(src), "Next Label")
    elif ex in EXITS:
        operand = EXITS[ex]
    else:
        report["errors"].append(f"connect {c['from']} -> {c['to']}: unknown exit {ex!r} (valid: {sorted(EXITS)}, "
                                f"case:N, original)")
        return
    last = None
    for entry in ENTRIES.get(kind(dst), ("Label",)):
        try:
            if idx is None:
                m.Connections.Create(src, dst, operand, entry)
            else:
                m.Connections.Create(src, dst, operand, entry, idx, 1)
            return
        except pythoncom.com_error as e:
            last = e
    report["errors"].append(f"connect {c['from']} -[{ex}]-> {c['to']}: {last}")


# ---------------------------------------------------------------------------------------------------- information

def info(a):
    lic = safe(lambda: a.LicenseType)
    return {"name": safe(lambda: a.Name), "version": safe(lambda: a.Version), "arena_dir": arena_dir(),
            "edition": edition.describe(lic), "models_open": [a.Models.Item(i).FullName
                                                             for i in range(1, a.Models.Count + 1)]}


def panels(a):
    return {"panels": [a.Panels.Item(i).Name for i in range(1, a.Panels.Count + 1)]}


def defs(a, panel):
    d = a.Panels.Attach(panel).ModuleDefinitions
    return {"panel": panel, "modules": [d.Item(i).Name for i in range(1, d.Count + 1)]}


def operands(a, panel, module_type):
    ops = mdef(a.Panels.Attach(panel), module_type).Operands
    return {"panel": panel, "type": module_type,
            "operands": [{"name": ops.Item(i).Name, "default": safe(lambda: ops.Item(i).DefaultValue)}
                         for i in range(1, ops.Count + 1)]}


def template_reference(module_type, panel=None):
    """The section of Arena's own template reference (<Panel>.txt in the Arena folder) for one module type: every
    operand, including the hidden exit/entry points, and the choice labels."""
    d = arena_dir()
    if not d:
        raise ArenaError("Arena folder not found; set ARENA_DIR")
    files = [f"{panel}.txt"] if panel else sorted(f for f in os.listdir(d) if f.endswith(".txt"))
    for f in files:
        p = os.path.join(d, f)
        if not os.path.exists(p):
            continue
        txt = open(p, errors="replace").read()
        mm = re.search(rf"^Module:\s*{re.escape(module_type)}\s*$(.*?)(?=^Module:|\Z)", txt, re.M | re.S)
        if mm:
            return {"file": p, "module": module_type, "text": ("Module: " + module_type + mm.group(1)).rstrip()}
    raise ArenaError(f"no module {module_type!r} in the template references in {d}")


def inspect(a, model, full=False, out_path=None):
    """Every module (type, name, position, operands incl. repeat rows), every connection, run setup. Operands still at
    their default value are left out unless full (full also includes data modules' operands)."""
    m = open_model(a, model)
    opcache, mods = {}, []
    for i in range(1, m.Modules.Count + 1):
        md = m.Modules.Item(i)
        d = md.Definition
        t = safe(lambda: d.Name)
        is_data = bool(safe(lambda: d.DataModule, False))
        sh = safe(lambda: md.shape)
        rec = {"type": t, "name": getdata(md, "Name"), "data_module": is_data,
               "x": safe(lambda: sh.Left), "y": safe(lambda: sh.Top)}
        if full or not is_data:
            if t not in opcache:
                ops = d.Operands
                opcache[t] = [(ops.Item(j).Name, safe(lambda: ops.Item(j).DefaultValue))
                              for j in range(1, ops.Count + 1)]
            vals = {}
            for on, default in opcache[t]:
                v = getdata(md, on)
                if v in (None, ""):
                    continue
                if full or v != default or on == "Name":
                    vals[on] = v
                r = 2
                while True:  # repeat-group rows
                    v2 = getdata(md, f"{on}({r})")
                    if v2 is None:
                        break
                    if full or v2 != default:
                        vals[f"{on}({r})"] = v2
                    r += 1
            rec["ops"] = vals
        mods.append(rec)
    res = {"model": m.FullName, "modules": mods, "connections": [{"from": s, "to": d} for s, d in connection_list(m)],
           "run_setup": run_setup(m)}
    if out_path:
        json.dump(res, open(out_path, "w", encoding="utf-8"), indent=1, default=str)
        return {"wrote": os.path.abspath(out_path), "modules": len(mods), "connections": len(res["connections"])}
    return res


def run_setup(m):
    units = {v: k for k, v in TIME_UNITS.items()}
    g = lambda k: safe(lambda: getattr(m, k))  # noqa: E731
    return {"replications": g("NumberOfReplications"), "replication_length": g("ReplicationLength"),
            "replication_length_units": units.get(g("ReplicationLengthTimeUnits"), g("ReplicationLengthTimeUnits")),
            "warm_up": g("WarmUpPeriod"), "warm_up_units": units.get(g("WarmUpPeriodTimeUnits"),
                                                                     g("WarmUpPeriodTimeUnits")),
            "base_time_units": units.get(g("BaseTimeUnits"), g("BaseTimeUnits")),
            "hours_per_day": g("HoursPerDay"), "terminating_condition": g("TerminatingCondition")}


def apply_run_setup(m, setup, report):
    """setup: {"replications", "replication_length", "replication_length_units", "warm_up", "warm_up_units",
    "base_time_units", "hours_per_day", "terminating_condition"}; units are days|hours|minutes|seconds."""
    props = {"replications": "NumberOfReplications", "replication_length": "ReplicationLength",
             "replication_length_units": "ReplicationLengthTimeUnits", "warm_up": "WarmUpPeriod",
             "warm_up_units": "WarmUpPeriodTimeUnits", "base_time_units": "BaseTimeUnits",
             "hours_per_day": "HoursPerDay", "terminating_condition": "TerminatingCondition"}
    for k, v in (setup or {}).items():
        if k not in props:
            report["errors"].append(f"run setup: unknown field {k!r} (valid: {sorted(props)})")
            continue
        if k.endswith("units"):
            if str(v).lower() not in TIME_UNITS:
                report["errors"].append(f"run setup: {k}={v!r}; use one of {sorted(TIME_UNITS)}")
                continue
            v = TIME_UNITS[str(v).lower()]
        try:
            setattr(m, props[k], v)
        except pythoncom.com_error as e:
            report["errors"].append(f"run setup: cannot set {k}={v!r} ({e})")


# ---------------------------------------------------------------------------------------------------- editing

def build(a, spec):
    """Build a new model from a spec, or extend "base" and save it as "save_as". See the skill's spec reference."""
    if isinstance(spec, str):
        spec = json.load(open(spec, encoding="utf-8"))
    report = {"errors": [], "warnings": [], "declared": []}
    # refuse SIMAN reserved words before touching any model (they compile with a warning, then the run stops at 0)
    names = set(spec.get("declare", {}).get("attributes", [])) | set(spec.get("declare", {}).get("variables", []))
    for ms in spec.get("modules", []) + [dict(u, type=t) for u in spec.get("updates", []) for t in ("Assign", "ReadWrite")]:
        at, va = used_names(expand(ms), ms.get("type", ""))[:2]
        names |= at | va
    clash = reserved_clashes(names)
    if clash and not spec.get("allow_reserved"):
        return {"error": "SIMAN reserved words used as attribute/variable names; rename them", "names": clash,
                "model_changed": False}
    if "base" in spec:
        m = open_model(a, spec["base"])
        if "save_as" in spec:
            m.SaveAs(os.path.abspath(spec["save_as"]))  # never touch the base file
    else:
        if "save_as" not in spec:
            return {"error": "a new model needs save_as (where to save the .doe)", "model_changed": False}
        m = a.Models.Add()
        m.SaveAs(os.path.abspath(spec["save_as"]))
    safe(lambda: setattr(m.ActiveView, "AutoConnect", False))
    apply_run_setup(m, spec.get("run_setup"), report)
    existing = modules_by_name(m)
    for u in spec.get("updates", []):
        mod = existing.get(u["name"])
        if mod is None:
            report["errors"].append(f"update: no module named {u['name']!r}")
            continue
        apply_data(mod, expand(u), report, u["name"])
    auto = []
    made, n_added = {}, 0
    found = {"attribute": set(spec.get("declare", {}).get("attributes", [])),
             "variable": set(spec.get("declare", {}).get("variables", [])), "queue": set(), "resource": set(),
             "entity": set()}

    def collect(items, t):
        for what, ns in zip(DECLARERS, used_names(items, t)):
            found[what] |= ns

    for ms in spec.get("modules", []):
        name = ms.get("data", {}).get("Name")
        if name and name in existing:
            report["errors"].append(f"module {name!r} already exists; use 'updates' to change it")
            continue
        try:
            panel = a.Panels.Attach(ms.get("panel", "BasicProcess"))
            d = mdef(panel, ms["type"])
        except (pythoncom.com_error, ArenaError) as e:
            report["errors"].append(f"module {name or ms.get('id')}: {e}")
            continue
        n_before = m.Modules.Count
        mod = m.Modules.Create(panel, d, ms.get("x", 1000), ms.get("y", 1000))
        own = safe(lambda: mod.shape.SerialNumber)
        sides = []
        for j in range(n_before + 1, m.Modules.Count + 1):  # data modules Arena adds by itself (Entity, File, Queue ...)
            side = m.Modules.Item(j)
            if safe(lambda: side.shape.SerialNumber) == own:  # the module just created (itself a data module)
                continue
            if safe(lambda: side.Definition.DataModule, False):
                sides.append(side)
        items = expand(ms)
        apply_data(mod, items, report, name or ms.get("id"))
        etype = dict(items).get("Entity Type") if ms["type"] == "Create" else None
        for side in sides:
            # a Create adds "Entity 1"; when the spec names its own entity type, rename that one instead of leaving
            # an unused entity type that shows up in every report
            if etype and kind(side) == "Entity" and etype not in existing:
                old_name = getdata(side, "Name")
                setdata(side, "Name", etype)
                existing[etype] = side
                auto.append(f"Entity {old_name!r} renamed to {etype!r} (added with {name or ms.get('id')})")
            elif etype and kind(side) == "Entity" and getdata(side, "Name") != etype:
                stray = getdata(side, "Name")  # the entity type already exists: drop the unused default one
                sel = m.ActiveView.Selection
                sel.DeselectAll()
                sel.Add(side.shape)
                sel.Delete()
                auto.append(f"Entity {stray!r} removed, unused (added with {name or ms.get('id')})")
            else:
                auto.append(f"{kind(side)} {getdata(side, 'Name')!r} (added with {name or ms.get('id')})")
        made[ms.get("id", name)] = mod
        n_added += 1
        if name:
            existing[name] = mod
        collect(items, ms["type"])
    for u in spec.get("updates", []):
        collect(expand(u), kind(existing[u["name"]]) if u["name"] in existing else "")
    dx, dy = spec.get("declare_at", [0, -4000])
    for what in DECLARERS:
        declare(a, m, existing, found[what], what, dx, dy, report)
    for k, mod in existing.items():  # connections may name existing modules too
        made.setdefault(k, mod)
    for c in spec.get("connections", []):
        if c["from"] not in made or c["to"] not in made:
            report["errors"].append(f"connect: unknown module {c['from']!r} or {c['to']!r}")
            continue
        connect(m, made, c, report)
    for sh in spec.get("shapes", []):  # drawing only: titles over groups of modules
        try:
            m.Shapes.CreateText(sh["x"], sh["y"], sh["text"], sh.get("font", "Arial"), sh.get("height", 300), 0,
                                bool(sh.get("bold", True)), False, False)
        except (pythoncom.com_error, KeyError) as e:
            report["errors"].append(f"shape {sh}: {e}")
    if spec.get("delete"):
        report["deleted"] = []
        delete_modules(m, spec["delete"], report)
    if spec.get("check", True):  # compile after deletes, so dropped connections and errors show up now, not later
        report["check_errors"], report["dropped_connections"] = check_model(m)
        report["ok"] = not report["errors"] and not report["dropped_connections"] and not any(
            e.get("level") != "warning" for e in report["check_errors"])
    m.Save()
    return {"model": m.FullName, "modules_added": n_added, "connections": m.Connections.Count, "auto_created": auto,
            **report}


def delete_modules(m, names, report):
    """Arena's object model has no Module.Delete; select the module's shape in the view and delete the selection."""
    byname = modules_by_name(m)
    sel = m.ActiveView.Selection
    for n in names:
        mod = byname.get(n)
        if mod is None:
            report["errors"].append(f"delete: no module named {n!r}")
            continue
        sel.DeselectAll()
        sel.Add(mod.shape)
        sel.Delete()
        report["deleted"].append(n)


def delete(a, model, names):
    m = open_model(a, model)
    report = {"errors": [], "deleted": []}
    delete_modules(m, names, report)
    m.Save()
    return {"model": m.FullName, **report}


def close(a, models=None):
    """Close open models (saving nothing). With no paths, closes every model this Arena has open. Arena can crash
    on Close(); a crash is reported, and the next call starts a fresh Arena."""
    closed, failed = [], []
    want = [os.path.abspath(p).lower() for p in models or []]
    for i in range(a.Models.Count, 0, -1):
        m = a.Models.Item(i)
        if not want or m.FullName.lower() in want:
            name = m.FullName
            try:
                m.Close()
                closed.append(name)
            except pythoncom.com_error as e:
                failed.append({"model": name, "error": str(e)})
                break
    return {"closed": closed, "failed": failed}


def set_data(a, model, module, data, save=True):
    """Change operands of one module ({operand: value}), declare any names it now needs, and save."""
    m = open_model(a, model)
    mod = modules_by_name(m).get(module)
    if mod is None:
        return {"error": f"no module named {module!r}", "model_changed": False}
    report = {"errors": [], "warnings": [], "declared": []}
    items = [(k, str(v)) for k, v in data.items()]
    used = used_names(items, kind(mod))
    at, va = used[:2]
    clash = reserved_clashes(at | va)
    if clash:
        return {"error": "SIMAN reserved words used as attribute/variable names; rename them", "names": clash,
                "model_changed": False}
    apply_data(mod, items, report, module)
    existing = modules_by_name(m)
    for names, what in zip(used, DECLARERS):
        declare(a, m, existing, names, what, 0, -4000, report)
    if save:
        m.Save()
    return {"model": m.FullName, "module": module, "saved": save, **report}


def setup(a, model, run_setup_fields, save=True):
    m = open_model(a, model)
    report = {"errors": []}
    apply_run_setup(m, run_setup_fields, report)
    if save:
        m.Save()
    return {"model": m.FullName, "run_setup": run_setup(m), "saved": save, **report}


# ---------------------------------------------------------------------------------------------------- check and run

def read_err(m):
    """Arena writes check/run errors to <model>.err as binary records: a 4-byte shape serial number 20 bytes before
    the source tag (MODVAL, ...), then the message. Returns [{"module", "type", "message"}]."""
    p = os.path.splitext(m.FullName)[0] + ".err"
    if not os.path.exists(p):
        return []
    return parse_err(open(p, "rb").read(), module_serials(m))


def module_serials(m):
    serials = {}
    for i in range(1, m.Modules.Count + 1):
        md = m.Modules.Item(i)
        s = safe(lambda: md.shape.SerialNumber)
        if s is not None:
            serials[int(s)] = (getdata(md, "Name"), kind(md))
    return serials


def parse_err(raw, serials):
    tags = list(re.finditer(rb"\x00{8}([A-Z][A-Z0-9]{2,11})\x00", raw))
    res, seen = [], {}
    for k, tag in enumerate(tags):
        pos = tag.start(1)
        seg = raw[tag.end():tags[k + 1].start() if k + 1 < len(tags) else len(raw)]
        texts = [t.decode().strip() for t in re.findall(rb"[ -~\n\t]{4,}", seg)]
        text = max(texts, key=len) if texts else ""
        lines = [ln.rstrip() for ln in text.splitlines() if ln.strip()]
        msg = lines[-1].strip() if lines else ""
        rec = {"source": tag.group(1).decode(), "level": "warning" if msg.upper().startswith("WARNING") else "error",
               "message": msg}
        code = [ln for ln in lines[:-1] if set(ln.strip()) != {"^"}]
        if code:  # SIMAN compile records (GGTNAM) quote the generated SIMAN code the message refers to
            rec["code"] = code
        if rec["source"] == "MODVAL" and pos >= 20:  # shape serial of the faulty module, 20 bytes before the tag
            # (other record types have unrelated numbers there)
            s = int.from_bytes(raw[pos - 20:pos - 16], "little", signed=True)
            if s in serials:
                rec["module"], rec["type"] = serials[s]
        key = (rec["message"], rec.get("module"))
        if key in seen:  # the same message repeats once per use of the symbol: count it instead
            seen[key]["count"] = seen[key].get("count", 1) + 1
            continue
        seen[key] = rec
        res.append(rec)
    if not res and raw:  # unknown layout: fall back to the printable text
        txt = raw.decode("latin-1")
        res = [{"level": "error", "message": re.sub(r"\s+", " ", s).strip()} for s in re.findall(r"[ -~]{6,}", txt)]
    return res


def connection_list(m):
    res = []
    for i in range(1, m.Connections.Count + 1):
        c = m.Connections.Item(i)
        res.append((safe(lambda: c.Source().Data("Name")), safe(lambda: c.Destination().Data("Name"))))
    return res


def check_model(m):
    """Compile the model. Returns errors, plus any connections Check() deleted (it silently drops connections made to
    an invalid entry point)."""
    m.QuietMode = True
    p = os.path.splitext(m.FullName)[0] + ".err"
    before = os.path.getmtime(p) if os.path.exists(p) else 0
    conns = connection_list(m)
    m.Check()
    after = connection_list(m)
    fresh = os.path.exists(p) and os.path.getmtime(p) > before
    errs = read_err(m) if fresh else []
    dropped = [f"{s} -> {d}" for s, d in conns if (s, d) not in after]
    return errs, dropped


def check(a, model):
    m = open_model(a, model)
    errs, dropped = check_model(m)
    res = {"model": m.FullName, "ok": not dropped and not any(e.get("level") != "warning" for e in errs),
           "errors": errs, "dropped_connections": dropped}
    if safe(lambda: m.AreDemoLimitsExceeded):
        res["edition_limit_exceeded"] = True
        res["ok"] = False
    return res


def evaluate(m, expr):
    """Value of an Arena expression in the current (ended) run: SIMAN.StringEvaluateFormula, falling back to
    SymbolNumber + VariableValue for a plain variable `Name` or `Name(i[, j])`."""
    s = m.SIMAN
    try:
        return float(s.StringEvaluateFormula(expr))
    except Exception:
        pass
    mt = re.fullmatch(r"\s*(\w+)\s*(?:\(\s*(\d+)\s*(?:,\s*(\d+)\s*)?\))?\s*", expr)
    if mt:
        i1, i2 = int(mt.group(2) or 0), int(mt.group(3) or 0)
        try:
            return float(s.VariableValue(s.SymbolNumber(mt.group(1), 0, 0), i1, i2))
        except Exception as e:
            return f"ERR {e}"
    return "ERR cannot evaluate"


def end_other_runs(a):
    """Arena runs one model at a time: a model left in run mode (State != 0, e.g. 12 after an ended run whose End()
    failed) makes Go() on any other model wait ~2 min and return without running. End them all first."""
    ended = []
    for i in range(1, a.Models.Count + 1):
        other = a.Models.Item(i)
        if safe(lambda: other.State, 0) != 0:
            safe(lambda: other.End())
            ended.append(other.Name)
    return ended


def _run_once(a, m, show, outputs, per_replication=False):
    m.QuietMode = True
    ended_first = end_other_runs(a)
    m.BatchMode = True
    t0 = time.time()
    m.Go(1)  # smGoWait: returns when the run ends
    res = {"seconds": round(time.time() - t0, 1), "end_time": safe(lambda: m.SIMAN.RunCurrentTime),
           "replications": safe(lambda: int(m.NumberOfReplications)), "errors": []}
    if ended_first:
        res["ended_first"] = ended_first
    if res["end_time"] is None:
        res["errors"].append({"level": "error", "message": "the run did not start (no SIMAN run state after Go)"})
    p = os.path.splitext(m.FullName)[0] + ".err"
    fresh = lambda: os.path.exists(p) and os.path.getmtime(p) > t0  # noqa: E731
    if fresh():
        res["errors"] = read_err(m)
    if show:  # read before End(), which resets the run; a bad expression writes its own record to .err
        n_before = len(res["errors"])
        res["values"] = {e: evaluate(m, e) for e in show}
        after = read_err(m) if fresh() else []
        if len(after) > n_before:
            res["show_errors"] = after[n_before:]
    if safe(lambda: m.AreDemoLimitsExceeded):
        res["edition_limit_exceeded"] = True
        res["errors"].append({"level": "error", "message": edition.LIMIT_MESSAGE})
    safe(lambda: m.End())
    if safe(lambda: m.State, 0) != 0:  # still in run mode: the next run of any model would stall
        res["errors"].append({"level": "error", "message": f"model still in run mode after End() (State {m.State})"})
    if outputs:
        r = resultsmod.read(m.FullName, t0, per_replication)
        res["results_source"] = r["source"]
        res["statistics"] = r["statistics"]
        if r.get("note"):
            res["results_note"] = r["note"]
    lic = resultsmod.report_license(m.FullName)
    if lic:  # the text report names the license ("STUDENT"); remember it, it tells Student from lab licenses apart
        res["report_license"] = lic
        edition.remember_report_license(lic)
    if any(edition.is_limit_message(e.get("message", "")) for e in res["errors"]):
        res["edition_limit_exceeded"] = True
    res["ok"] = not any(e.get("level") != "warning" for e in res["errors"])
    return res


def _apply_in_memory(m, changes, report):
    """changes: {module: {operand: value}}. Returns the previous values, to restore after the run."""
    byname = modules_by_name(m)
    old = {}
    for module, data in (changes or {}).items():
        mod = byname.get(module)
        if mod is None:
            report["errors"].append({"level": "error", "message": f"set: no module named {module!r}"})
            continue
        for k, v in data.items():
            old[(module, k)] = getdata(mod, k)
        apply_data(mod, [(k, str(v)) for k, v in data.items()], report, module)
    return old


def _restore(m, old):
    byname = modules_by_name(m)
    for (module, k), v in old.items():
        if v is not None:
            safe(lambda: setdata(byname[module], k, v))


def run(a, model, reps=None, setup_fields=None, changes=None, show=None, outputs=True, per_replication=False):
    """Run a model in batch mode and return the across-replication results.
    setup_fields: run setup to use for this run ({"replications", "replication_length", ...}).
    changes: {module: {operand: value}} applied in memory for this run only and restored afterwards (no save).
    show: Arena expressions evaluated at the end of the LAST replication (e.g. "NQ(Queue1.Queue)", "OVALUE(Stat)").
    per_replication: also return each statistic's value in every replication."""
    m = open_model(a, model)
    report = {"errors": [], "warnings": []}
    if reps:
        setup_fields = dict(setup_fields or {}, replications=reps)
    old_setup = run_setup(m)
    apply_run_setup(m, setup_fields, report)
    old = _apply_in_memory(m, changes, report)
    try:
        res = _run_once(a, m, show, outputs, per_replication)
    finally:
        _restore(m, old)
        if setup_fields:
            apply_run_setup(m, {k: old_setup[k] for k in setup_fields if old_setup.get(k) is not None}, {"errors": []})
    res["errors"] = [{"level": "error", "message": e} if isinstance(e, str) else e for e in report["errors"]] + res[
        "errors"]
    res["ok"] = res["ok"] and not report["errors"]
    return {"model": m.FullName, **({"warnings": report["warnings"]} if report["warnings"] else {}), **res}


def scenarios(a, model, cases, reps=None, setup_fields=None, show=None, measures=None):
    """Run several scenarios in one Arena session without saving: each case is {"name", "changes": {module:
    {operand: value}}, "reps", "run_setup"}. Returns one result per case; measures limits outputs to those
    statistics (substring match, case-insensitive)."""
    out = []
    for c in cases:
        r = run(a, model, reps=c.get("reps", reps), setup_fields={**(setup_fields or {}), **c.get("run_setup", {})},
                changes=c.get("changes"), show=c.get("show", show))
        if measures:
            r["statistics"] = {k: v for k, v in r.get("statistics", {}).items()
                               if any(q.lower() in k.lower() for q in measures)}
        out.append({"name": c.get("name", f"case {len(out) + 1}"), **r})
    return {"model": os.path.abspath(model), "scenarios": out}


def last_results(model, per_replication=False, include_empty=False):
    """Results of the model's last run, from its report database or text report (no new run, no Arena needed)."""
    path = os.path.abspath(model)
    return {"model": path, **resultsmod.read(path, 0, per_replication, include_empty)}
