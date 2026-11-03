"""Spike fixture generators. Every word is a token Z<sid>q<i> so the true section of any PDF word is known."""
import random

def toks(prefix, sid, n, start=0):
    return " ".join(f"{prefix}{sid:02d}q{start+i:03d}" for i in range(n))

def q(s):
    return '"' + s.replace('"', '\\"') + '"'

def slides_typ(n_slides, paras=3, words=28):
    out = ['#import "lib/marks.typ": *',
           '#set page(width: 960pt, height: 540pt, margin: (x: 60pt, y: 50pt))',
           '#set text(size: 18pt)']
    for s in range(n_slides):
        ps = ", ".join(q(toks("Z", s, words, i * words)) for i in range(paras))
        title = q(toks("H", s, 4))
        out.append(f'''#section("s{s:02d}", [
  #el("title", "s{s:02d}", text(size: 34pt, weight: "bold")[#{title}], width: 840pt)
  #v(20pt)
  #el("body", "s{s:02d}", block(width: 560pt)[#({ps}, ).join(parbreak())], width: 560pt)
  #place(top + right, dy: 0pt, rect(width: 200pt, height: 120pt, fill: rgb("#1f6f5c")))
])''')
        if s != n_slides - 1:
            out.append("#pagebreak()")
    return "\n".join(out) + "\n"

COLW = 234
def doc_typ(n_sections, paras=3, words=60, features=True, table_rows=40, fig_every=3):
    out = ['#import "lib/marks.typ": *',
           '#set page(paper: "a4", margin: 54pt, columns: 2, footer: context align(center, counter(page).display()))',
           '#set columns(gutter: 18pt)', '#set text(size: 10pt)']
    for s in range(n_sections):
        body = [f'#el("heading", "s{s:02d}", text(size: 14pt, weight: "bold")[#{q(toks("H", s, 3))}], width: {COLW}pt)',
                '#v(4pt)']
        for p in range(paras):
            body.append(f'#{q(toks("Z", s, words, p * words))}')
            body.append('#parbreak()')
        if features and s % fig_every == 1:
            body.append(f'#place(top, float: true, el("figure", "s{s:02d}", block(width: 100%)[#rect(width: 100%, height: 90pt, fill: luma(220)) #text(size: 8pt)[#{q(toks("F", s, 6))}]], width: {COLW}pt))')
        if features and s == 2:
            body.append(f'#place(top + center, scope: "parent", float: true, el("span", "s{s:02d}", block(width: 100%)[#rect(width: 100%, height: 60pt, fill: luma(200)) #text(size: 8pt)[#{q(toks("P", s, 8))}]], width: 487pt))')
        if features and s == 4:
            rows = []
            for r in range(table_rows):
                rows.append(f'row-mark("s{s:02d}", {r}) + [R{s:02d}r{r:02d}c0], [R{s:02d}r{r:02d}c1], [R{s:02d}r{r:02d}c2]')
            body.append('#table(columns: (1fr, 1fr, 1fr), table.header[Y%02dh0][Y%02dh1][Y%02dh2], %s)' % (s, s, s, ", ".join(rows)))
        out.append(f'#section("s{s:02d}", [\n  ' + "\n  ".join(body) + '\n])')
        if features and s == 6:
            out.append("#pagebreak()")
    return "\n".join(out) + "\n"
