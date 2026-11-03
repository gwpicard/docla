import json, os, re, subprocess, time, hashlib
from pathlib import Path
import pdfplumber
ENV = dict(os.environ, SOURCE_DATE_EPOCH="0")
HERE = Path(__file__).parent

def compile_pdf(typ, pdf):
    t = time.perf_counter()
    r = subprocess.run(["typst", "compile", str(typ), str(pdf), "--root", str(HERE), "--ignore-system-fonts"],
                       capture_output=True, text=True, env=ENV, cwd=HERE)
    assert r.returncode == 0, r.stderr
    return time.perf_counter() - t

def read_marks(typ):
    t = time.perf_counter()
    r = subprocess.run(["typst", "eval", "query(<docla-mark>).map(it => it.value)", "--in", str(typ),
                        "--root", str(HERE), "--ignore-system-fonts"], capture_output=True, text=True, env=ENV, cwd=HERE)
    assert r.returncode == 0, r.stderr
    return json.loads(r.stdout), time.perf_counter() - t

def words(pdf_path):
    """Words with token text, box (top-left origin, pt) and baseline, per page (1-based)."""
    out = []
    with pdfplumber.open(pdf_path) as pdf:
        for pno, page in enumerate(pdf.pages, 1):
            H = float(page.height)
            cur = []
            def flush():
                nonlocal cur
                if cur:
                    out.append(dict(page=pno, text="".join(c["text"] for c in cur),
                                    x0=min(c["x0"] for c in cur), x1=max(c["x1"] for c in cur),
                                    top=min(c["top"] for c in cur), bottom=max(c["bottom"] for c in cur),
                                    base=H - cur[0]["matrix"][5], size=cur[0]["size"]))
                cur = []
            for c in page.chars:
                if c["text"].isspace():
                    flush(); continue
                if cur and (abs(c["matrix"][5] - cur[0]["matrix"][5]) > 0.5 or c["x0"] - cur[-1]["x1"] > 3):
                    flush()
                cur.append(c)
            flush()
    return out

def tok_sid(text):
    m = re.match(r"^([A-Z])(\d\d)", text)
    return (m.group(1), int(m.group(2))) if m else (None, None)
