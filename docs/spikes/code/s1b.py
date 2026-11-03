from common import *
import gen, collections
import pypdfium2 as pdfium
from PIL import Image, ImageDraw
N = 10
open("doc.typ", "w").write(gen.doc_typ(N)); compile_pdf("doc.typ", "doc.pdf")
marks, _ = read_marks("doc.typ"); W = words("doc.pdf")
PW, PH, M, GUT = 595.2756, 841.8898, 54.0, 18.0
CW = (PW - 2 * M - GUT) / 2; MID = M + CW + GUT / 2
col = lambda x: 0 if x < MID else 1
CATS = {"H": "heading", "Z": "flow", "F": "figure float", "P": "spanning float", "R": "table", "Y": "table header"}
truth = lambda w: tok_sid(w["text"])
tw = [w for w in W if truth(w)[0] in CATS]
starts = sorted([(m["page"], col(m["x"]), m["y"], int(m["id"][1:])) for m in marks if m["kind"] == "section" and m["edge"] == "start"])
boxes = [m for m in marks if m["kind"] == "element" and m["role"] in ("figure", "span")]

def by_marks(w):
    cx = (w["x0"] + w["x1"]) / 2
    for b in boxes:
        if b["page"] == w["page"] and b["x"] - 1 <= cx <= b["x"] + b["w"] + 1 and b["y"] - 1 <= (w["top"] + w["bottom"]) / 2 <= b["y"] + b["h"] + 1:
            return int(b["id"][1:])
    key = (w["page"], col(cx), w["base"]); sid = None
    for s in starts:
        if (s[0], s[1], s[2]) <= key: sid = s[3]
    return sid

# fallback: no marks at all. Cut points = first heading word of each section in reading order.
hw = sorted([(w["page"], col((w["x0"] + w["x1"]) / 2), w["top"], truth(w)[1]) for w in tw if truth(w)[0] == "H"])
firsth = {}
for p, c, t, s in hw: firsth.setdefault(s, (p, c, t))
cuts = sorted((v[0], v[1], v[2], s) for s, v in firsth.items())
def by_titles(w):
    key = (w["page"], col((w["x0"] + w["x1"]) / 2), w["top"]); sid = None
    for c in cuts:
        if (c[0], c[1], c[2] - 6) <= key: sid = c[3]
    return sid

def score(fn):
    tot, ok = collections.Counter(), collections.Counter()
    for w in tw:
        cat = CATS[truth(w)[0]]; tot[cat] += 1; tot["ALL"] += 1
        if fn(w) == truth(w)[1]: ok[cat] += 1; ok["ALL"] += 1
    return tot, ok
print(f"S1b document: {len(set(w['page'] for w in W))} pages, {len(tw)} tokens, {len(marks)} marks")
for name, fn in (("marks (start cut points + float boxes)", by_marks), ("title-search fallback (no marks)", by_titles)):
    tot, ok = score(fn)
    print(f"\n{name}: {ok['ALL']}/{tot['ALL']} words in the right section")
    for c in ("heading", "flow", "table", "table header", "figure float", "spanning float"):
        print(f"   {c:15s} {ok[c]:4d}/{tot[c]:4d}")

# naive: fragment boxes from start/end marks + known column geometry only
def fragments(i):
    s = starts[i]; e = starts[i + 1] if i + 1 < len(starts) else (99, 0, 0, -1)
    frs = []; p, c = s[0], s[1]
    while (p, c) <= (e[0], e[1]):
        y0 = s[2] if (p, c) == (s[0], s[1]) else M
        y1 = e[2] if (p, c) == (e[0], e[1]) else PH - M
        frs.append((p, M + c * (CW + GUT), y0, M + c * (CW + GUT) + CW, y1))
        c += 1
        if c == 2: p, c = p + 1, 0
    return frs
rec = con = inside = 0; total = 0
for i, s in enumerate(starts):
    fr = fragments(i)
    for w in tw:
        cx, cy = (w["x0"] + w["x1"]) / 2, (w["top"] + w["bottom"]) / 2
        if any(f[0] == w["page"] and f[1] <= cx <= f[3] and f[2] <= cy <= f[4] for f in fr):
            inside += 1
            if truth(w)[1] != s[3]: con += 1
for s in starts: pass
true_in = 0
for w in tw:
    sid = truth(w)[1]; i = [k for k, s in enumerate(starts) if s[3] == sid][0]
    cx, cy = (w["x0"] + w["x1"]) / 2, (w["top"] + w["bottom"]) / 2
    if any(f[0] == w["page"] and f[1] <= cx <= f[3] and f[2] <= cy <= f[4] for f in fragments(i)): true_in += 1
print(f"\nnaive fragment boxes from marks + column geometry: recall {true_in}/{len(tw)} words; "
      f"{con} of {inside} words inside the boxes belong to another section (floats, table, columns)")

# float placement vs PDF
print("\nfloat marks vs glyphs:")
for b in boxes:
    pre = "F" if b["role"] == "figure" else "P"; sid = int(b["id"][1:])
    ws = [w for w in tw if truth(w) == (pre, sid)]
    x0 = min(w["x0"] for w in ws); x1 = max(w["x1"] for w in ws); y1 = max(w["base"] for w in ws)
    print(f'  {b["id"]} {b["role"]:7s} mark p{b["page"]} x{b["x"]:.1f} y{b["y"]:.1f} w{b["w"]:.1f} h{b["h"]:.1f} | caption words p{ws[0]["page"]} x0 {x0:.1f} x1 {x1:.1f} last base {y1:.1f}  (inside box: {b["x"]-0.5<=x0 and x1<=b["x"]+b["w"]+0.5 and y1<=b["y"]+b["h"]+0.5})')
rows = {m["n"]: m for m in marks if m["kind"] == "row"}
dx = []; dy = []
for r in range(40):
    ws = [w for w in tw if w["text"] == f"R04r{r:02d}c0"]
    if ws: dx.append(ws[0]["x0"] - rows[r]["x"]); dy.append(ws[0]["base"] - rows[r]["y"]); pg = (ws[0]["page"], rows[r]["page"])
print(f"table rows: {len(dx)} marks; dx min/max {min(dx):.2f}/{max(dx):.2f}; baseline-minus-mark.y min/max {min(dy):.2f}/{max(dy):.2f}; all rows on the same page as their words: {all((w['page']==rows[int(w['text'][4:6])]['page']) for w in tw if w['text'].startswith('R04') and w['text'].endswith('c0'))}")

# overlay
pdf = pdfium.PdfDocument("doc.pdf"); pal = ["#e6194b","#3cb44b","#4363d8","#f58231","#911eb4","#008080","#9a6324","#800000","#808000","#000075"]
for pno in range(1, len(pdf) + 1):
    img = pdf[pno - 1].render(scale=1.5).to_pil().convert("RGB"); d = ImageDraw.Draw(img, "RGBA")
    grp = collections.defaultdict(list)
    for w in tw:
        if w["page"] == pno: grp[(by_marks(w), col((w["x0"] + w["x1"]) / 2))].append(w)
    for (sid, c), ws in grp.items():
        if sid is None: continue
        b = (min(w["x0"] for w in ws) * 1.5, min(w["top"] for w in ws) * 1.5, max(w["x1"] for w in ws) * 1.5, max(w["bottom"] for w in ws) * 1.5)
        d.rectangle(b, fill=pal[sid % 10] + "33", outline=pal[sid % 10], width=2); d.text((b[0] + 3, b[1] + 2), f"s{sid:02d}", fill=pal[sid % 10])
    for bx in boxes:
        if bx["page"] == pno: d.rectangle((bx["x"]*1.5, bx["y"]*1.5, (bx["x"]+bx["w"])*1.5, (bx["y"]+bx["h"])*1.5), outline="#000000", width=2)
    img.save(f"out/doc_p{pno}.png")
print("overlays written to out/doc_p1..p%d.png" % len(pdf))
