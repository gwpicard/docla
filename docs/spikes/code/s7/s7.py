"""Spike S7: separate git dir beside a user's own repository, worktree runs, and the section-aware merge driver."""
import json, os, shutil, subprocess, sys, time
from pathlib import Path
from doclo.source import parse, serialise
from doclo.model import Item, Section

HERE = Path(__file__).resolve().parent
PY, DRIVER = sys.executable, HERE / "merge_driver.py"
import tempfile
WORK = Path(tempfile.mkdtemp(prefix="doclo-s7-"))
ENV = dict(os.environ, GIT_AUTHOR_NAME="t", GIT_AUTHOR_EMAIL="t@example.com", GIT_COMMITTER_NAME="t",
           GIT_COMMITTER_EMAIL="t@example.com", GIT_CONFIG_GLOBAL="/dev/null", GIT_CONFIG_NOSYSTEM="1")

def sh(*a, cwd, check=True):
    r = subprocess.run(a, cwd=cwd, capture_output=True, text=True, env=ENV)
    if check and r.returncode: raise RuntimeError(f"{a}: {r.stderr}")
    return r

BASE_SRC = """---
doctype: pitch-deck
format: slides
title: Spike deck
---

""" + "\n".join(f"""::: {{#{sid} .section intent="parallel-set" section="{name}"}}
## {name.title()} title

- **Head {name} one**: {name} body one.
- **Head {name} two**: {name} body two.

> note: {name} note
:::
""" for sid, name in [("a1a1a", "alpha"), ("b2b2b", "bravo"), ("c3c3c", "charlie"), ("d4d4d", "delta")])
base_doc, f = parse(BASE_SRC); assert not [x for x in f if x.severity == "error"], f
BASE = serialise(base_doc); assert serialise(parse(BASE)[0]) == BASE

def sec(d, sid): return next(s for s in d.sections if s.id == sid)
def edit(d, sid, **kw):
    return d.model_copy(update={"sections": [s.model_copy(update=kw) if s.id == sid else s for s in d.sections]})
def reorder(d, order): m = {s.id: s for s in d.sections}; return d.model_copy(update={"sections": [m[i] for i in order]})
def ids(d): return [s.id for s in d.sections]
NEW = Section(id="e5e5e", intent="quote", section="echo", title="Echo title", items=[Item(body="echo body")])

S = []
def scenario(name, ours, theirs, expect): S.append((name, ours, theirs, expect))
scenario("1 different sections", lambda d: edit(d, "a1a1a", title="Person alpha"), lambda d: edit(d, "b2b2b", items=[Item(body="run bravo")]),
         lambda r, rep, rc: rc == 0 and sec(r, "a1a1a").title == "Person alpha" and sec(r, "b2b2b").items[0].body == "run bravo")
scenario("2 same section, different fields", lambda d: edit(d, "a1a1a", title="Person alpha"), lambda d: edit(d, "a1a1a", items=[Item(body="run alpha")]),
         lambda r, rep, rc: rc == 0 and sec(r, "a1a1a").title == "Person alpha" and sec(r, "a1a1a").items[0].body == "run alpha")
scenario("3 same text field: person wins, run kept", lambda d: edit(d, "a1a1a", title="Person alpha"), lambda d: edit(d, "a1a1a", title="Run alpha"),
         lambda r, rep, rc: rc == 0 and sec(r, "a1a1a").title == "Person alpha" and rep["dropped"] == [{"section": "a1a1a", "field": "title", "run_value": "Run alpha"}])
scenario("4 run changes a non-text field", lambda d: d, lambda d: edit(d, "c3c3c", span="full"),
         lambda r, rep, rc: rc == 0 and sec(r, "c3c3c").span == "full")
scenario("5 both change a non-text field", lambda d: edit(d, "c3c3c", component="two-col", because="person"), lambda d: edit(d, "c3c3c", component="grid", because="run"),
         lambda r, rep, rc: rc == 0 and sec(r, "c3c3c").component == "two-col" and sec(r, "c3c3c").because == "person")
scenario("6 run inserts a section, person edits another", lambda d: edit(d, "c3c3c", note="person note"),
         lambda d: d.model_copy(update={"sections": d.sections[:2] + [NEW] + d.sections[2:]}),
         lambda r, rep, rc: rc == 0 and ids(r) == ["a1a1a", "b2b2b", "e5e5e", "c3c3c", "d4d4d"] and sec(r, "c3c3c").note == "person note")
scenario("7 person deletes, run edits: conflict", lambda d: d.model_copy(update={"sections": [s for s in d.sections if s.id != "c3c3c"]}),
         lambda d: edit(d, "c3c3c", title="Run charlie"),
         lambda r, rep, rc: rc != 0 and rep["conflicts"] == [{"section": "c3c3c", "why": "run edited, person deleted"}])
scenario("8 both reorder: person's order", lambda d: reorder(d, ["d4d4d", "a1a1a", "b2b2b", "c3c3c"]), lambda d: reorder(d, ["b2b2b", "c3c3c", "d4d4d", "a1a1a"]),
         lambda r, rep, rc: rc == 0 and ids(r) == ["d4d4d", "a1a1a", "b2b2b", "c3c3c"])
scenario("9 identical change on both sides", lambda d: edit(d, "b2b2b", title="Same"), lambda d: edit(d, "b2b2b", title="Same"),
         lambda r, rep, rc: rc == 0 and sec(r, "b2b2b").title == "Same" and rep.get("dropped", []) == [])
scenario("10 run changes nothing", lambda d: edit(d, "d4d4d", spoken="person spoken"), lambda d: edit(d, "a1a1a", note="alpha note"),
         lambda r, rep, rc: rc == 0 and sec(r, "d4d4d").spoken == "person spoken")
scenario("11 only the run reorders", lambda d: edit(d, "a1a1a", title="Person alpha"), lambda d: reorder(d, ["b2b2b", "a1a1a", "c3c3c", "d4d4d"]),
         lambda r, rep, rc: rc == 0 and ids(r) == ["b2b2b", "a1a1a", "c3c3c", "d4d4d"] and sec(r, "a1a1a").title == "Person alpha")
scenario("12 run deletes a section the person did not touch", lambda d: edit(d, "a1a1a", title="Person alpha"),
         lambda d: d.model_copy(update={"sections": [s for s in d.sections if s.id != "d4d4d"]}),
         lambda r, rep, rc: rc == 0 and ids(r) == ["a1a1a", "b2b2b", "c3c3c"])

def project(path, driver):
    if path.exists(): shutil.rmtree(path)
    path.mkdir(parents=True)
    (path / "README.md").write_text("my notes\n"); (path / "deck.md").write_text(BASE)
    sh("git", "init", "-q", "-b", "main", cwd=path); sh("git", "add", ".", cwd=path); sh("git", "commit", "-qm", "user's own commit", cwd=path)
    with open(path / ".git/info/exclude", "a") as fh: fh.write(".doclo/\n")
    G = ["git", "--git-dir=.doclo/git", "--work-tree=."]
    (path / ".doclo").mkdir()  # git init does not create the parent of --git-dir
    sh(*G, "init", "-q", "-b", "main", cwd=path)
    (path / ".doclo/git/info").mkdir(parents=True, exist_ok=True)
    (path / ".doclo/git/info/exclude").write_text(".doclo/\n")
    if driver:
        sh(*G, "config", "merge.doclo-md.name", "doclo section-aware merge", cwd=path)
        sh(*G, "config", "merge.doclo-md.driver", f"{PY} {DRIVER} %O %A %B %P", cwd=path)
        (path / ".doclo/git/info/attributes").write_text("*.md merge=doclo-md\n")
    sh(*G, "add", "deck.md", cwd=path); sh(*G, "commit", "-qm", "base", cwd=path)
    return G

def run(name, ours, theirs, expect, driver):
    path = WORK / ("drv" if driver else "txt") / name.split()[0]
    G = project(path, driver)
    user_head = sh("git", "rev-parse", "HEAD", cwd=path).stdout.strip()
    t0 = time.perf_counter()
    sh(*G, "worktree", "add", "-q", ".doclo/runs/r1", "-b", "run/r1", cwd=path)
    wt_time = time.perf_counter() - t0
    wt = path / ".doclo/runs/r1"
    (wt / "deck.md").write_text(serialise(theirs(parse(BASE)[0])))
    sh("git", "add", "-A", cwd=wt); sh("git", "commit", "-qm", "run r1", "--allow-empty", cwd=wt)
    (path / "deck.md").write_text(serialise(ours(parse(BASE)[0])))
    sh(*G, "add", "deck.md", cwd=path); sh(*G, "commit", "-qm", "edit: person", "--allow-empty", cwd=path)
    rpt = path / ".doclo/merge-report.json"
    m = sh(*G, "merge", "--no-edit", "run/r1", cwd=path, check=False)
    text = (path / "deck.md").read_text()
    rep = json.loads(rpt.read_text()) if rpt.exists() else {}
    doc, findings = parse(text)
    ok = expect(doc, rep, m.returncode) if driver else None
    # coexistence: the user's repository must not see or be changed by any of this
    us = sh("git", "status", "--porcelain", cwd=path).stdout.split("\n")
    co = dict(user_head_same=sh("git", "rev-parse", "HEAD", cwd=path).stdout.strip() == user_head,
              user_sees_doclo=any(".doclo" in l for l in us),
              user_worktrees=len(sh("git", "worktree", "list", cwd=path).stdout.splitlines()),
              user_branches=sh("git", "branch", "--format=%(refname:short)", cwd=path).stdout.split(),
              run_wt_resolves_to_doclo=sh("git", "rev-parse", "--git-common-dir", cwd=wt).stdout.strip().endswith(".doclo/git"))
    return dict(ok=ok, rc=m.returncode, markers="<<<<<<<" in text, parse_errors=len([x for x in findings if x.severity == "error"]),
                co=co, wt_time=wt_time, merged_text=text)

results = []
for name, o, t, e in S:
    d = run(name, o, t, e, True); p = run(name, o, t, e, False)
    results.append((name, d, p))
    print(f"{name:48s} driver: {'PASS' if d['ok'] else 'FAIL'} (exit {d['rc']})   plain text merge: exit {p['rc']}{' with conflict markers' if p['markers'] else ''}{', file no longer parses' if p['parse_errors'] else ''}")
print(f"\n{sum(1 for _, d, _ in results if d['ok'])}/{len(results)} scenarios pass with the driver")
co = [d["co"] for _, d, _ in results]
print("user's HEAD unchanged in every scenario:", all(c["user_head_same"] for c in co))
print("user's git status ever shows .doclo/:", any(c["user_sees_doclo"] for c in co))
print("user's repo ever lists a doclo worktree:", any(c["user_worktrees"] != 1 for c in co), "| user's branches:", sorted(set(b for c in co for b in c["user_branches"])))
print("run worktree resolves to .doclo/git with plain git:", all(c["run_wt_resolves_to_doclo"] for c in co))
print(f"worktree creation: median {sorted(d['wt_time'] for _, d, _ in results)[len(results)//2]*1000:.0f} ms")

print("\nplain text merges that exited 0: is the result what the policy wants?")
for (name, o, t, e), (_, d, p) in zip(S, results):
    if p["rc"] == 0:
        pd = parse(p["merged_text"])[0]
        good = e(pd, {"dropped": [], "conflicts": []}, 0) if name.split()[0] not in ("3",) else None
        print(f"   {name:48s} {'same as policy' if good else 'DIFFERENT from policy'}")

sys.path.insert(0, str(HERE)); from merge_driver import merge_docs
b = parse(BASE)[0]; props = dict(deterministic=True, ours_equals_theirs=True, run_unchanged=True, person_unchanged=True)
for name, o, t, e in S:
    od, td = o(parse(BASE)[0]), t(parse(BASE)[0])
    r1 = serialise(merge_docs(b, od, td)[0]); r2 = serialise(merge_docs(b, od, td)[0])
    props["deterministic"] &= r1 == r2
    props["ours_equals_theirs"] &= serialise(merge_docs(b, od, od)[0]) == serialise(od)
    props["run_unchanged"] &= serialise(merge_docs(b, od, b)[0]) == serialise(od)
    props["person_unchanged"] &= serialise(merge_docs(b, b, td)[0]) == serialise(td)
print("\nproperties over all 12 scenarios:", props)
