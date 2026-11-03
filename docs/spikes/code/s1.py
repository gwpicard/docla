from common import *
import gen, statistics as st
open("slides.typ", "w").write(gen.slides_typ(3)); compile_pdf("slides.typ", "slides.pdf")
marks, _ = read_marks("slides.typ"); W = words("slides.pdf")
print("S1 slides: element mark vs real glyph geometry (pt)")
rows = []
for m in marks:
    if m["kind"] != "element": continue
    sid = int(m["id"][1:]); prefix = "H" if m["role"] == "title" else "Z"
    ws = [w for w in W if w["page"] == m["page"] and tok_sid(w["text"]) == (prefix, sid)]
    x0 = min(w["x0"] for w in ws); x1 = max(w["x1"] for w in ws)
    first_base = min(w["base"] for w in ws); last_base = max(w["base"] for w in ws)
    top = min(w["top"] for w in ws); bot = max(w["bottom"] for w in ws)
    rows.append(dict(id=m["id"], role=m["role"], d_left=x0 - m["x"], d_right=x1 - (m["x"] + m["w"]),
                     d_firstbase=first_base - m["y"], d_lastbase_vs_bottom=last_base - (m["y"] + m["h"]),
                     mark_y=m["y"], mark_h=m["h"], first_base=first_base, last_base=last_base, glyph_top=top, glyph_bottom=bot))
for r in rows[:2] + rows[2:4]:
    print({k: (round(v, 2) if isinstance(v, float) else v) for k, v in r.items()})
for k in ("d_left", "d_right", "d_firstbase", "d_lastbase_vs_bottom"):
    for role in ("title", "body"):
        v = [r[k] for r in rows if r["role"] == role]
        print(f"{k:22s} {role:5s} min {min(v):7.2f} max {max(v):7.2f}")
