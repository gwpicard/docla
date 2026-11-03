"""Same widow, orphan and heading placements, but with Typst's defaults: widow/orphan costs at 100% and real (sticky) headings."""
import sys; sys.path.insert(0, ".")
import s8
s8.HEAD = s8.HEAD.replace("#set text(size: 10pt, costs: (widow: 0%, orphan: 0%))", "#set text(size: 10pt)")
def real_heading(pid):
    return f'#heading(level: 2)[h{pid:02d}x heading]'
scenes = [("widow", lambda p: f"#v({s8.top_for_k(5) - s8.TOP:.2f}pt)\n{s8.para(p, 6)}")] * 3 + \
         [("orphan", lambda p: f"#v({s8.top_for_k(1) - s8.TOP:.2f}pt)\n{s8.para(p, 6)}")] * 3 + \
         [("heading at foot", lambda p: f"#v({s8.BOTTOM - s8.HEADING - 9 - s8.TOP:.2f}pt)\n{real_heading(p)}\n{s8.para(p, 4)}")] * 2
body = "\n#colbreak()\n".join(f(i) for i, (_, f) in enumerate(scenes))
marks, ordered, by_key, pages = s8.build("defaults", body)
real = s8.truth(by_key)
# real headings carry no mark here, so locate them from the tokens
heads = {k[:2] for k, toks in by_key.items() if any(t.endswith("x") and t.startswith("h") for t in toks)}
for i, (kind, _) in enumerate(scenes):
    print(f"{kind:16s} with Typst defaults -> {real.get(f'p{i:02d}') or 'no defect'}")
