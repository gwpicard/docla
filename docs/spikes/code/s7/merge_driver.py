"""Spike S7: section-aware three-way merge driver for working files (DESIGN.md 19.3).

git calls it as: merge_driver.py %O %A %B %P  (base, ours = person's main, theirs = the AI run, path).
It writes the result into %A and exits 0, or exits 1 for a conflict that needs the person (delete against edit).
"""
import json, os, sys
from pathlib import Path
from doclo.source import parse, serialise

TEXT = {"title", "items", "paragraphs", "code", "note", "spoken", "source_line", "data"}
IDENTITY = {"id"}

def merge_fields(b, o, t, dropped):
    res = o.model_copy(deep=True)
    for f in type(o).model_fields:
        if f in IDENTITY: continue
        bo, oo, to = getattr(b, f), getattr(o, f), getattr(t, f)
        if oo == to or to == bo: continue
        if oo == bo: setattr(res, f, to)
        elif f in TEXT: dropped.append({"section": b.id, "field": f, "run_value": to if not hasattr(to, "__iter__") or isinstance(to, (str, dict)) else [x.model_dump() if hasattr(x, "model_dump") else x for x in to]})
        # non-text changed by both: the person's value stands
    return res

def three_way(b, o, t):
    """Scalar three-way where the person wins a true conflict."""
    if o == t or t == b: return o
    if o == b: return t
    return o

def merge_docs(base, ours, theirs):
    B = {s.id: s for s in base.sections}; O = {s.id: s for s in ours.sections}; T = {s.id: s for s in theirs.sections}
    dropped, conflicts, out = [], [], {}
    for sid in list(dict.fromkeys([*O, *T, *B])):
        b, o, t = B.get(sid), O.get(sid), T.get(sid)
        if b is not None and (o is None or t is None):
            survivor, other = (t, "run edited, person deleted") if o is None else (o, "person edited, run deleted")
            if survivor is None or survivor == b: continue          # deleted, and the other side did not touch it
            conflicts.append({"section": sid, "why": other}); out[sid] = o if o is not None else None
            continue
        if b is None:                                              # added on one or both sides
            if o is not None and t is not None and o != t:
                out[sid] = merge_fields(o, o, t, dropped)          # both added the same id: person wins text
            else: out[sid] = o if o is not None else t
            continue
        if o == t: out[sid] = o
        elif o == b: out[sid] = t
        elif t == b: out[sid] = o
        else: out[sid] = merge_fields(b, o, t, dropped)
    common = [i for i in B if i in O and i in T]
    base_o = [i for i in B if i in common]; ours_o = [i for i in O if i in common]; theirs_o = [i for i in T if i in common]
    order = theirs_o if ours_o == base_o else ours_o              # the person's order wins if both reordered
    seq = list(order)
    # sections only in ours keep their place after their predecessor in ours; same for sections only in theirs
    for src in (list(O), list(T)):
        for k, sid in enumerate(src):
            if sid in seq or sid not in out or out[sid] is None: continue
            prev = next((p for p in reversed(src[:k]) if p in seq), None)
            seq.insert(seq.index(prev) + 1 if prev else 0, sid)
    sections = [out[i] for i in seq if out.get(i) is not None]
    front = {k: three_way(base.front.get(k), ours.front.get(k), theirs.front.get(k))
             for k in dict.fromkeys([*ours.front, *theirs.front, *base.front])}
    front = {k: v for k, v in front.items() if v is not None}
    merged = ours.model_copy(update={
        "front": front, "sections": sections,
        "context": three_way(base.context, ours.context, theirs.context),
        "sources": three_way(base.sources, ours.sources, theirs.sources),
        "format": three_way(base.format, ours.format, theirs.format)})
    return merged, dropped, conflicts

def main(o_path, a_path, b_path, rel):
    base, _ = parse(Path(o_path).read_text()); ours, _ = parse(Path(a_path).read_text()); theirs, _ = parse(Path(b_path).read_text())
    merged, dropped, conflicts = merge_docs(base, ours, theirs)
    Path(a_path).write_text(serialise(merged))
    report = Path(os.environ.get("DOCLO_MERGE_REPORT", ".doclo/merge-report.json"))
    report.parent.mkdir(parents=True, exist_ok=True)
    report.write_text(json.dumps({"path": rel, "dropped": dropped, "conflicts": conflicts}, indent=2, sort_keys=True, default=str) + "\n")
    return 1 if conflicts else 0

if __name__ == "__main__":
    sys.exit(main(*sys.argv[1:5]))
