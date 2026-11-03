"""Spike S8: can flow defects be measured from the PDF plus marks reliably enough to drive repairs?

Seeds widows, orphans, headings stranded at a column foot, near-empty last pages and unbalanced last pages by placing blocks
at computed heights. Ground truth comes from the line tokens in the PDF; the detectors see only line positions and the
paragraph start marks, never the tokens or the seeds.
"""
import collections, json, subprocess, os
from pathlib import Path
import pdfplumber
HERE = Path(__file__).resolve().parent
ENV = dict(os.environ, SOURCE_DATE_EPOCH="0")
HEAD = '''#import "lib/marks.typ": *
#set page(paper: "a4", margin: 54pt, columns: 2)
#set columns(gutter: 18pt)
#set text(size: 10pt, costs: (widow: 0%, orphan: 0%))
'''
CAP, PITCH, HEADING, GAP = 6.58, 13.08, 8.385, 12.0       # calibrated with calib.typ
TOP, BOTTOM, PW = 54.0, 841.8898 - 54.0, 595.2756
MID = PW / 2
LPC = int((BOTTOM - TOP - CAP) // PITCH) + 1              # lines per full column

LINEBREAK = " \\ "   # Typst forced line break: a single backslash

def para(pid, n, k0=0):
    lines = [" ".join(f"p{pid:02d}l{li:02d}{c}" for c in "abcd") for li in range(k0, k0 + n)]
    return f'#el("para", "p{pid:02d}", [{LINEBREAK.join(lines)}], width: 234pt)'

def heading(pid):
    return f'#el("heading", "h{pid:02d}", text(size: 13pt, weight: "bold")[h{pid:02d}x heading], width: 234pt)'

def top_for_k(k):            # block top so that exactly k lines fit above the column bottom
    return BOTTOM - CAP - (k - 1) * PITCH - PITCH / 2

SCENES = []                   # (pid, kind, expected defect or None, typst)
def scene(kind, expect, body): SCENES.append((len(SCENES), kind, expect, body))
for _ in range(3): scene("widow", "widow", lambda pid: f"#v({top_for_k(5) - TOP:.2f}pt)\n{para(pid, 6)}")
for _ in range(3): scene("orphan", "orphan", lambda pid: f"#v({top_for_k(1) - TOP:.2f}pt)\n{para(pid, 6)}")
for _ in range(2): scene("heading at foot", "heading-at-foot", lambda pid: f"#v({BOTTOM - HEADING - 9 - TOP:.2f}pt)\n{heading(pid)}\n{para(pid, 4)}")
for k in (2, 3, 4, 2, 3, 4): scene(f"clean split {k}/{6 - k}", None, lambda pid, k=k: f"#v({top_for_k(k) - TOP:.2f}pt)\n{para(pid, 6)}")
for _ in range(2): scene("clean, fits", None, lambda pid: f"#v(40pt)\n{para(pid, 6)}")
for _ in range(2): scene("clean heading, 2 lines after", None,
                         lambda pid: f"#v({BOTTOM - HEADING - GAP - CAP - PITCH - PITCH / 2 - TOP:.2f}pt)\n{heading(pid)}\n{para(pid, 4)}")

def build(name, body):
    (HERE / f"{name}.typ").write_text(HEAD + body)
    for cmd in (["typst", "compile", f"{name}.typ", f"{name}.pdf"], ["typst", "eval", "query(<doclo-mark>).map(it => it.value)", "--in", f"{name}.typ"]):
        r = subprocess.run(cmd + ["--root", str(HERE), "--ignore-system-fonts"], capture_output=True, text=True, cwd=HERE, env=ENV)
        if r.returncode: raise RuntimeError(r.stderr)
    marks = json.loads(r.stdout)
    lines = collections.defaultdict(list)
    with pdfplumber.open(HERE / f"{name}.pdf") as pdf:
        pages = len(pdf.pages)
        for pno, page in enumerate(pdf.pages, 1):
            for w in page.extract_words():
                lines[(pno, 0 if (w["x0"] + w["x1"]) / 2 < MID else 1, round(w["bottom"], 1))].append(w["text"])
    ordered = sorted(lines)                                   # reading order: page, column, height
    return marks, ordered, {k: lines[k] for k in ordered}, pages

col = lambda x: 0 if x < MID else 1
def assign(marks, ordered):
    """Detector side: a line belongs to the last block mark whose start precedes it (page, column, y)."""
    starts = sorted((m["page"], col(m["x"]), m["y"], m["role"], m["id"]) for m in marks if m["kind"] == "element")
    out = collections.defaultdict(list)
    for key in ordered:
        owner = None
        for s in starts:
            if s[:3] <= key: owner = (s[3], s[4])
        out[owner].append(key)
    return out

def frags(keys): return [list(g) for _, g in __import__("itertools").groupby(keys, key=lambda k: k[:2])]

def detect(marks, ordered):
    found = {}
    owned = assign(marks, ordered)
    for (role, bid), keys in owned.items():
        if role == "para" and len(keys) >= 2:
            f = frags(keys)
            if len(f) > 1 and len(f[-1]) == 1: found[bid] = ("widow", "pull 1 line back or push 1 more line over")
            if len(f) > 1 and len(f[0]) == 1: found[bid] = ("orphan", "push the first line to the next column")
        if role == "heading":
            last = keys[-1]; i = ordered.index(last)
            if i + 1 < len(ordered) and ordered[i + 1][:2] != last[:2]:
                found["p" + bid[1:]] = ("heading-at-foot", "move the heading to the next column (needs 1 body line, about 18.6 pt)")
    return found

def truth(lines_by_key):
    """Ground truth from the tokens: where did each paragraph's lines and each heading actually land?"""
    pos = collections.defaultdict(list); head = {}
    for key, toks in lines_by_key.items():
        for t in toks:
            if t.startswith("p") and t[3] == "l": pos[t[:3]].append((int(t[4:6]), key[:2]))
            if t.startswith("h") and t.endswith("x"): head["p" + t[1:3]] = key
    real = {}
    for pid, ls in pos.items():
        ls = sorted(set(ls)); cols = [c for _, c in ls]
        if len(set(cols)) > 1:
            if cols.count(cols[-1]) == 1: real[pid] = "widow"
            if cols.count(cols[0]) == 1: real[pid] = "orphan"
        if pid in head and ls and ls[0][1] != head[pid][:2]: real[pid] = "heading-at-foot"
    return real

marks, ordered, by_key, pages = build("scenes", "\n#colbreak()\n".join(s[3](s[0]) for s in SCENES))
found, real = detect(marks, ordered), truth(by_key)
print(f"S8 flow rules: scene document of {pages} pages, {len(SCENES)} scenes, {len(ordered)} lines\n")
print(f"{'scene':34s} {'seeded':16s} {'actually happened':18s} {'detected':16s}")
tp = fp = fn = 0; seed_ok = 0
for pid, kind, expect, _ in SCENES:
    key = f"p{pid:02d}"; r = real.get(key); d = found.get(key, (None,))[0]
    seed_ok += r == expect; tp += bool(d) and d == r; fp += bool(d) and d != r; fn += bool(r) and d != r
    print(f"{kind:34s} {str(expect):16s} {str(r):18s} {str(d):16s}")

# last-page rules: near-empty page and column balance, each in its own two-page document
def last_page(name, col1, col2):
    body = para(90, 2 * LPC) + "\n#pagebreak()\n" + para(91, col1, 0)
    if col2: body += "\n#colbreak()\n" + para(92, col2, 0)
    m, o, b, pages = build(name, body)
    last = [k for k in o if k[0] == pages]
    n1 = sum(1 for k in last if k[1] == 0); n2 = sum(1 for k in last if k[1] == 1)
    det = []
    fill = (n1 + n2) / (2 * LPC)
    if fill < 0.15: det.append(("near-empty", f"cut about {n1 + n2} lines from the section before the page break"))
    if n2 and abs(n1 - n2) > 0.25 * LPC: det.append(("imbalance", f"move about {abs(n1 - n2) // 2} lines from column {1 if n1 > n2 else 2}"))
    t1 = sum(1 for k in last for t in b[k] if t.startswith("p91") and t.endswith("a"))
    t2 = sum(1 for k in last for t in b[k] if t.startswith("p92") and t.endswith("a"))
    return det, (t1, t2), pages
print(f"\nlast page ({LPC} lines per full column)")
lp = [("near-empty", "near-empty", 2, 0), ("near-empty", "near-empty", 5, 0), ("near-empty control", None, 34, 34),
      ("near-empty control", None, 30, 30), ("imbalance", "imbalance", LPC, 3), ("imbalance", "imbalance", LPC, 8),
      ("imbalance control", None, 28, 28), ("imbalance control", None, 40, 38)]
for i, (kind, expect, c1, c2) in enumerate(lp):
    det, real_lines, pages = last_page(f"last{i}", c1, c2)
    names = [d[0] for d in det]
    hit = expect in names if expect else not names
    tp += bool(expect and hit); fn += bool(expect and not hit); fp += len([n for n in names if n != expect])
    seed_ok += 1
    print(f"  {kind:20s} lines on last page {str(real_lines):10s} detected {names or 'nothing'}  {det[0][1] if det else ''}")
print(f"\nseeded defects detected: {tp}/{tp + fn}; false positives: {fp} (out of {len(SCENES) + len(lp)} scenes); "
      f"seeds that came out as intended: {seed_ok}/{len(SCENES) + len(lp)}")
