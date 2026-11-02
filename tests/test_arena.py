"""End-to-end tests against a local Arena: pytest -m arena"""
import json
import os

import pytest

from arena_agent import core, paths, worker

pytestmark = pytest.mark.arena


def build_example(name, tmp_path):
    spec = json.load(open(os.path.join(paths.examples_dir(), name), encoding="utf-8"))
    spec["save_as"] = str(tmp_path / spec["save_as"])
    return spec["save_as"], worker.call(core.build, spec)


def test_clinic_builds_runs_and_matches_theory(tmp_path):
    model, res = build_example("clinic.json", tmp_path)
    assert res["ok"], res
    run = worker.call(core.run, model)
    assert run["ok"] and run["end_time"] == 480
    util = run["statistics"]["Doctor.Instantaneous Utilization"]
    # arrival rate 1/5 per minute, mean exam 12 minutes, 3 doctors: utilization 0.8
    assert abs(util["average"] - 0.8) < 2 * util["half_width"] + 0.05
    assert "Examination.Queue.Waiting Time" in run["statistics"]
    worker.call(core.close, [model])


def test_bank_scenarios_more_tellers_wait_less(tmp_path):
    model, res = build_example("bank.json", tmp_path)
    assert res["ok"], res
    out = worker.call(core.scenarios, model, [{"name": "2", "changes": {"Teller": {"Capacity": "2"}}},
                                              {"name": "3", "changes": {"Teller": {"Capacity": "3"}}}], 10)
    w = [s["statistics"]["Teller Service.Queue.Waiting Time"]["average"] for s in out["scenarios"]]
    assert w[1] < w[0]
    # the saved model is unchanged by scenario runs
    ins = worker.call(core.inspect, model, True)
    teller = next(m for m in ins["modules"] if m["name"] == "Teller")
    assert teller["ops"]["Capacity"] == "2"
    worker.call(core.close, [model])


def test_check_maps_error_to_module(tmp_path):
    spec = {"save_as": str(tmp_path / "bad.doe"), "modules": [
        {"id": "c", "type": "Create", "data": {"Name": "Arr"}},
        {"id": "p", "type": "Process", "x": 2000, "data": {"Name": "Work", "Action": "Seize Delay Release",
                                                          "DelayType": "Expression", "Expression": "EXPO(NoSuchVar)"},
         "resources": [{"Resource Name": "R"}]},
        {"id": "d", "type": "Dispose", "x": 4000, "data": {"Name": "Out"}}],
        "connections": [{"from": "c", "to": "p"}, {"from": "p", "to": "d"}]}
    res = worker.call(core.build, spec)
    assert not res["ok"]
    assert any("NoSuchVar" in (e.get("message", "") + " ".join(e.get("code", []))) for e in res["check_errors"])
    worker.call(core.close, [spec["save_as"]])


def test_reserved_word_refused(tmp_path):
    spec = {"save_as": str(tmp_path / "rw.doe"), "modules": [
        {"id": "a", "type": "Assign", "data": {"Name": "A"}, "rows": [{"Type": "Variable", "VName": "Wait",
                                                                       "Value": "1"}]}]}
    res = worker.call(core.build, spec)
    assert res.get("model_changed") is False and res["names"] == ["Wait"]
