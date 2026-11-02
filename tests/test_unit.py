"""Tests that need no Arena: spec expansion, name declaration, report parsing, statistics, edition, install config."""
import json
import math
import os

import pytest

from arena_agent import cli, core, edition, install, paths, results

DATA = os.path.join(os.path.dirname(__file__), "data")


def test_expand_rows_cases_resources():
    ms = {"data": {"Name": "A"}, "rows": [{"Type": "Attribute", "AName": "x", "Value": 1}],
          "cases": [{"N If": "Expression"}], "resources": [{"Resource Name": "R"}, {"Resource Name": "S"}]}
    assert core.expand(ms) == [("Name", "A"), ("Type(1)", "Attribute"), ("AName(1)", "x"), ("Value(1)", "1"),
                               ("N If(1)", "Expression"), ("Resource Name(1)", "R"), ("Resource Name(2)", "S")]


def test_used_names_assign_rows_any_order():
    items = [("Type(7)", "Variable"), ("VName(7)", "Late"), ("Type(1)", "Attribute"), ("AName(1)", "T0")]
    at, va, qu, rs, en = core.used_names(items, "Assign")
    assert at == {"T0"} and va == {"Late"} and not qu and not rs and not en


def test_used_names_process_and_create():
    items = [("Resource Type(1)", "Resource"), ("Resource Name(1)", "Doctor"), ("Resource Name(2)", "Nurse")]
    assert core.used_names(items, "Process")[3] == {"Doctor", "Nurse"}
    assert core.used_names([("Entity Type", "Patient")], "Create")[4] == {"Patient"}
    assert core.used_names([("QName", "Q1")], "Hold")[2] == {"Q1"}


def test_reserved_clashes_without_arena(monkeypatch):
    monkeypatch.setattr(core, "_reserved", {"wait", "group"})
    assert core.reserved_clashes({"Wait", "RWait", "Group.Queue", "group"}) == ["Wait", "group"]


def test_parse_out_summary():
    txt = open(os.path.join(DATA, "clinic.out"), errors="replace").read()
    res = results.parse_out(txt)
    assert res["Doctor.ScheduledUtilization"]["average"] == pytest.approx(0.79324)
    assert res["Patient.NumberOut"]["half_width"] == pytest.approx(6.6629)
    assert res["Patient.NumberOut"]["reps"] == 10


def test_parse_out_single_replication():
    txt = open(os.path.join(DATA, "clinic.out"), errors="replace").read()
    first = txt.split("Beginning replication 2")[0]
    res = results.parse_out(first)
    assert res["Patient.WaitTime"]["average"] == pytest.approx(5.9959)
    assert res["Patient.WaitTime"]["half_width"] == "(Insuf)"
    assert res["Examination.Queue.NumberInQueue"]["section"] == "Discrete-Change Variables"
    assert res["Patient.NumberIn"]["value"] == pytest.approx(82)


def test_read_db_matches_out_summary():
    res = results.read_db(os.path.join(DATA, "clinic.db"))
    out = results.parse_out(open(os.path.join(DATA, "clinic.out"), errors="replace").read())
    u = res["Doctor.ScheduledUtilization"]
    assert u["n"] == 10 and u["kind"] == "output"
    assert u["average"] == pytest.approx(out["Doctor.ScheduledUtilization"]["average"], abs=1e-4)
    assert u["half_width"] == pytest.approx(out["Doctor.ScheduledUtilization"]["half_width"], abs=1e-4)
    assert res["Examination.Queue.Waiting Time"]["kind"] == "tally"
    assert res["Doctor.Instantaneous Utilization"]["kind"] == "time-persistent"


def test_drop_empty():
    res = results.read_db(os.path.join(DATA, "clinic.db"))
    kept = results.drop_empty(res)
    assert all(v["n"] > 0 for v in kept.values())


def test_summarize_and_t():
    s = results.summarize([1.0, 2.0, 3.0, 4.0])
    assert s["average"] == 2.5 and s["n"] == 4
    assert s["half_width"] == pytest.approx(3.182 * math.sqrt(5 / 3) / 2)
    assert results.summarize([5.0])["half_width"] is None
    assert results.t975(100) == pytest.approx(1.984, abs=0.003)


@pytest.fixture
def cfg(tmp_path, monkeypatch):
    monkeypatch.setenv("APPDATA", str(tmp_path))
    return tmp_path


def test_edition_education_unknown_then_student_report(cfg):
    assert edition.describe(5)["status"] == "unknown"
    edition.remember_report_license("STUDENT")
    d = edition.describe(5)
    assert d["status"] == "limited" and d["limited"] is True


def test_edition_user_override(cfg):
    edition.set_limited(False)
    assert edition.describe(5)["limited"] is False
    edition.set_limited(None)
    assert edition.describe(4)["status"] == "full"
    assert edition.describe(2)["status"] == "view-only"


def test_limit_message():
    assert edition.is_limit_message("You have exceeded 150 entities allowed in the student version")
    assert not edition.is_limit_message("Undefined identifier: Patient")


def test_codex_config_roundtrip(tmp_path, monkeypatch):
    monkeypatch.setenv("CODEX_HOME", str(tmp_path))
    p = tmp_path / "config.toml"
    p.write_text('model = "x"\n\n[mcp_servers.other]\ncommand = "a"\n', encoding="utf-8")
    install._codex_mcp([r"C:\Users\A B\arena-agent.exe", "mcp"])
    install._codex_mcp([r"C:\Users\A B\arena-agent.exe", "mcp"])  # idempotent
    txt = p.read_text(encoding="utf-8")
    assert txt.count("[mcp_servers.arena-agent]") == 1 and "[mcp_servers.other]" in txt
    assert "command = 'C:\\Users\\A B\\arena-agent.exe'" in txt
    assert install.status("codex")["mcp"]
    install._codex_mcp(None, remove=True)
    txt = p.read_text(encoding="utf-8")
    assert "arena-agent" not in txt and "[mcp_servers.other]" in txt


def test_desktop_config(tmp_path, monkeypatch):
    monkeypatch.setenv("APPDATA", str(tmp_path))
    cfgp = tmp_path / "Claude" / "claude_desktop_config.json"
    cfgp.parent.mkdir()
    cfgp.write_text(json.dumps({"mcpServers": {"x": {"command": "y"}}, "other": 1}), encoding="utf-8")
    install._desktop_mcp(["arena-agent.exe", "mcp"])
    cfg = json.loads(cfgp.read_text(encoding="utf-8"))
    assert cfg["mcpServers"]["arena-agent"]["args"] == ["mcp"] and cfg["mcpServers"]["x"] and cfg["other"] == 1


def test_cli_parsing():
    assert cli.parse_changes(["Doctor:Capacity=4", "Doctor:Name=D", "V:Initial Value=2"]) == {
        "Doctor": {"Capacity": "4", "Name": "D"}, "V": {"Initial Value": "2"}}
    args = ["m.doe", "--reps", "5", "--show", "A", "B", "--per-rep"]
    assert cli.positional(args) == ["m.doe"]
    assert cli.opt_list(args, "--show") == ["A", "B"]


def test_guide_topics_present():
    topics = paths.guide_topics()
    for t in ("skill", "build-spec", "modules", "gotchas", "results", "discoveries"):
        assert t in topics and os.path.exists(topics[t]), t


def test_examples_are_valid_specs():
    for f in ("clinic.json", "bank.json"):
        spec = json.load(open(os.path.join(paths.examples_dir(), f), encoding="utf-8"))
        ids = {m["id"] for m in spec["modules"]}
        assert all(c["from"] in ids and c["to"] in ids for c in spec["connections"])
