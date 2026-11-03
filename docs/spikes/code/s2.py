from common import *
import gen, statistics as st, platform
import pypdfium2 as pdfium
def med(f, n=3):
    ts = []
    for _ in range(n):
        t = time.perf_counter(); r = f(); ts.append(time.perf_counter() - t)
    return st.median(ts), r
def case(name, typ_text):
    open(f"{name}.typ", "w").write(typ_text)
    ct, _ = med(lambda: compile_pdf(f"{name}.typ", f"{name}.pdf"))
    h1 = hashlib.sha256(open(f"{name}.pdf", "rb").read()).hexdigest(); compile_pdf(f"{name}.typ", f"{name}.pdf")
    h2 = hashlib.sha256(open(f"{name}.pdf", "rb").read()).hexdigest()
    qt, (marks, _) = med(lambda: read_marks(f"{name}.typ"))
    pdf = pdfium.PdfDocument(f"{name}.pdf"); pages = len(pdf)
    def raster(scale):
        for i in range(pages): pdf[i].render(scale=scale).to_pil()
    r1, _ = med(lambda: raster(1.0)); r2, _ = med(lambda: raster(2.0))
    def facts():
        with pdfplumber.open(f"{name}.pdf") as p:
            return sum(len(pg.chars) for pg in p.pages)
    ft, nchars = med(facts, 2)
    def facts_full():
        with pdfplumber.open(f"{name}.pdf") as p:
            return sum(len(pg.extract_words()) + len(pg.rects) + len(pg.lines) for pg in p.pages)
    fw, _ = med(facts_full, 2)
    size = os.path.getsize(f"{name}.pdf") / 1024
    print(f"{name:12s} pages {pages:3d} marks {len(marks):4d} chars {nchars:6d} pdf {size:6.0f} KiB | compile {ct:5.2f}s  query {qt:5.2f}s  raster@1x {r1:5.2f}s  raster@2x {r2:5.2f}s  "
          f"chars {ft:5.2f}s  words+shapes {fw:5.2f}s | byte-identical twice: {h1 == h2}")
    return dict(name=name, pages=pages, compile=ct, query=qt, r1=r1, r2=r2, facts=ft, facts_full=fw, same=h1 == h2)
print(f"machine: {platform.platform()} {platform.machine()}; typst {subprocess.run(['typst','--version'],capture_output=True,text=True).stdout.strip()}; python {platform.python_version()}")
case("swatch_1", gen.slides_typ(1))
case("deck_20", gen.slides_typ(20))
case("deck_25", gen.slides_typ(25))
case("doc_20pg", gen.doc_typ(50))
case("doc_100pg", gen.doc_typ(250))
