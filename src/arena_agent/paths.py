"""Where the bundled skill and examples are: inside the installed package, or in the repository for an editable
install."""
import os

PKG = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.normpath(os.path.join(PKG, "..", ".."))


def _first(*cands):
    for c in cands:
        if os.path.isdir(c):
            return c
    return cands[0]


def skill_dir():
    return _first(os.path.join(PKG, "skills", "arena-modeling"), os.path.join(REPO, "skills", "arena-modeling"))


def examples_dir():
    return _first(os.path.join(PKG, "examples"), os.path.join(REPO, "examples"))


def guide_topics():
    """{topic: path}: "skill" is SKILL.md, the rest are the files in references/."""
    d = skill_dir()
    topics = {"skill": os.path.join(d, "SKILL.md")}
    ref = os.path.join(d, "references")
    if os.path.isdir(ref):
        for f in sorted(os.listdir(ref)):
            if f.endswith(".md"):
                topics[f[:-3]] = os.path.join(ref, f)
    return topics
