"""Which Arena edition is this, and is it size-limited?

Arena reports its license through Application.LicenseType (the smLicenseType enum in Arena.exe's type library).
Rockwell does not publish the exact limits of the limited editions; the free Student edition is commonly reported to
stop a run once more than 150 entities are in the system at once. Arena itself knows when a model is over the limit
(Model.AreDemoLimitsExceeded), and the core checks that after every check and run.

Because the same license type can mean different things (an "Education" license may be a free student download or a
university lab license with no limits), the user can record the answer once: `arena-agent edition limited|full`.
"""
import json
import os
import re

LICENSES = {
    1: ("Evaluation", "limited"),
    2: ("Viewer", "view-only"),
    3: ("Standard", "full"),
    4: ("Professional", "full"),
    5: ("Education", "unknown"),  # student download (limited) or academic lab license (not): ask once
    6: ("Template Runner", "run-only"),
    7: ("SIMAN", "full"),
    8: ("Runtime", "run-only"),
    9: ("Academic", "full"),
}
LIMIT_MESSAGE = ("This model is over the limits of this Arena edition (Model.AreDemoLimitsExceeded). Limited editions "
                 "(Student, Evaluation) cap model size, commonly reported as 150 entities in the system at once. "
                 "Make the model smaller (fewer entities alive at once, shorter runs, batching), or use a full license.")
LIMIT_PATTERN = re.compile(r"(exceed|limit).*(entit|student|demo|evaluation|model size)|"
                           r"(student|demo|evaluation).*(limit|exceed)", re.I)


def config_path():
    return os.path.join(os.environ.get("APPDATA", os.path.expanduser("~")), "arena-agent", "config.json")


def load_config():
    try:
        return json.load(open(config_path(), encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def save_config(cfg):
    p = config_path()
    os.makedirs(os.path.dirname(p), exist_ok=True)
    json.dump(cfg, open(p, "w", encoding="utf-8"), indent=2)
    return p


def set_limited(value):
    """value: True (limited), False (full), None (forget the answer and go by the license type)."""
    cfg = load_config()
    if value is None:
        cfg.pop("limited", None)
    else:
        cfg["limited"] = bool(value)
    return save_config(cfg)


def remember_report_license(text):
    cfg = load_config()
    if cfg.get("report_license") != text:
        cfg["report_license"] = text
        save_config(cfg)


def describe(license_type):
    name, status = LICENSES.get(license_type, (f"unknown ({license_type})", "unknown"))
    res = {"license_type": license_type, "name": name, "status": status}
    cfg = load_config()
    rl = cfg.get("report_license")
    if rl:  # what Arena printed in the last run report's header, e.g. "STUDENT"
        res["report_license"] = rl
        if status == "unknown" and "STUDENT" in rl.upper():
            res["status"] = "limited"
            res["detected_from"] = "run report header (License: STUDENT)"
    user = cfg.get("limited")
    if user is not None and status in ("full", "limited", "unknown"):
        res["status"] = "limited" if user else "full"
        res["set_by_user"] = True
    res["limited"] = {"limited": True, "full": False}.get(res["status"])
    if res["status"] == "unknown":
        res["note"] = ("Cannot tell whether this license limits model size. Ask the user whether they use the free "
                       "Student edition (limited) or a full/lab license, then record it with set_edition.")
    elif res["status"] == "limited":
        res["note"] = ("Limited edition: keep models small (commonly reported cap: 150 entities in the system at "
                       "once). check/run report edition_limit_exceeded when Arena says the model is over the limit.")
    elif res["status"] in ("view-only", "run-only"):
        res["note"] = f"This {name} license cannot build or edit models; it can only open and run them."
    return res


def is_limit_message(msg):
    return bool(LIMIT_PATTERN.search(msg or ""))
