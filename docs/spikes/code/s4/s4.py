"""Spike S4: does patch-based repair converge on overflow and long-title defects in 3 attempts without losing facts?

Run from the doclo repository root:
  uv run --with anthropic python <this file> --mock      # plumbing check, no API calls
  DOCLO_RECORD=1 uv run --with anthropic python <this file>   # live, records a cassette
  uv run --with anthropic python <this file>             # replays the cassette, free
"""
import json, os, re, subprocess, sys, tempfile
from pathlib import Path
from doclo.model import Citation, Document, Item, Patch, PatchOp, Section
from doclo.source.patches import PatchRejected, apply_patch
from doclo.agents.cassette import Cassette

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE)); import seeds
MODEL, EFFORT = "claude-opus-5-5", "medium"
ARM = "B" if "--arm-b" in sys.argv else "A"   # B: findings name the wrapping items
PRICE_IN, PRICE_OUT = 4.00, 20.00          # USD per million tokens, claude-opus-5-5
TITLE_W, TITLE_H, BODY_W, BODY_H, ATTEMPTS = 840, 25, 560, 260, 3
ENV = dict(os.environ, SOURCE_DATE_EPOCH="0")

def q(s): return '"' + s.replace("\\", "\\\\").replace('"', '\\"') + '"'
def cite_text(cs): return " ".join(f"[{c.key} {c.locator}]" if c.locator else f"[{c.key}]" for c in cs)

def measure(sec):
    items = ", ".join(f"[#strong({q(i.head)}): #{q(i.body + ' ' + cite_text(i.citations))}]" if i.head else f"[#{q(i.body)}]" for i in sec.items)
    src = f'''#import "{HERE}/lib/fit.typ": fit-box
#set page(width: 960pt, height: 540pt, margin: (x: 60pt, y: 50pt))
#set text(size: 18pt)
#fit-box("title", "{sec.id}", {TITLE_W}pt, {TITLE_H}pt, text(size: 34pt, weight: "bold", {q(sec.title or "")}))
#v(24pt)
#fit-box("body", "{sec.id}", {BODY_W}pt, {BODY_H}pt, list({items}{"," if len(sec.items) == 1 else ""}))
#context {{
  let its = ({items}{"," if len(sec.items) == 1 else ""})
  for (n, c) in its.enumerate() [#metadata((kind: "item", n: n, w: measure(c).width / 1pt, one: measure(block(width: {BODY_W - 18}pt, [x])).height / 1pt, h: measure(block(width: {BODY_W - 18}pt, c)).height / 1pt)) <doclo-item>]
}}
'''
    with tempfile.TemporaryDirectory() as d:
        f = Path(d) / "swatch.typ"; f.write_text(src)
        r = subprocess.run(["typst", "eval", "(query(<doclo-fit>) + query(<doclo-item>)).map(it => it.value)", "--in", str(f), "--root", "/",
                            "--ignore-system-fonts"], capture_output=True, text=True, env=ENV)
        if r.returncode: raise RuntimeError(r.stderr)
        allm = json.loads(r.stdout)
    marks = [m for m in allm if m["kind"] == "fit"]
    per_item = []
    avail = BODY_W - 18
    for m in (m for m in allm if m["kind"] == "item"):
        it = sec.items[m["n"]]; text = f"{it.head}: {it.body} {cite_text(it.citations)}" if it.head else it.body
        lines = max(1, round((m["h"] - m["one"]) / 21.6) + 1) if m["h"] > m["one"] + 1 else 1
        last = m["w"] - (lines - 1) * avail
        cpc = m["w"] / max(1, len(text))
        per_item.append(dict(n=m["n"], lines=lines, cut_to_save_line=max(1, int(last / cpc) + 1) if lines > 1 else None))
    return [dict(rule=f"geo.{m['role']}-fits", role=m["role"], need=round(m["need"], 1), have=m["have"],
                 over=round(m["need"] - m["have"], 1), items=per_item if m["role"] == "body" else None) for m in marks if not m["ok"]]

def phi(fs): return 10 * len(fs) + sum(f["over"] for f in fs) / 100

# fact guard, after DESIGN.md 11.5
NUM = re.compile(r"(?<![\w.])[-+]?\d[\d,.]*\d%?|\b\d%?\b")
MONTHS = "January|February|March|April|May|June|July|August|September|October|November|December"
DATE = re.compile(rf"\b(?:19|20)\d{{2}}\b|\b\d{{1,2}}\s+(?:{MONTHS})\b")
ENT = re.compile(r"\b[A-Z][a-zA-Z&-]+(?:[ ]+[A-Z][a-zA-Z&-]+)+\b")
def norm(n): return n.replace(",", "")
def support_tokens(text):
    toks = {norm(m.group()) for m in NUM.finditer(text)} | {m.group().lower() for m in DATE.finditer(text)}
    return toks | {m.group().lower() for m in ENT.finditer(text)}
def fields(sec): return [sec.title or ""] + [x for i in sec.items for x in (i.head or "", i.body)]
def fact_tokens(sec):
    """Per field, so a capitalised head and a name in the body never merge into a fake entity. Citations are checked separately."""
    out = set()
    for f in fields(sec): out |= support_tokens(f)
    return out
def sec_text(sec): return "\n".join(fields(sec))
SOURCES_TEXT = " ".join(f"{k} {t}" for k, t in seeds.SOURCES)

SCHEMA = {"type": "object", "additionalProperties": False, "required": ["title", "items", "reason"], "properties": {
    "title": {"type": "string"}, "reason": {"type": "string"},
    "items": {"type": "array", "items": {"type": "object", "additionalProperties": False, "required": ["head", "body", "citations"],
              "properties": {"head": {"type": "string"}, "body": {"type": "string"},
                             "citations": {"type": "array", "items": {"type": "object", "additionalProperties": False,
                                           "required": ["key", "locator"], "properties": {"key": {"type": "string"}, "locator": {"type": "string"}}}}}}}}}
SYSTEM = ("You repair one section of a branded slide so that it passes measured layout checks. "
          "Change only what the findings require. Keep every fact, number, date, name and citation, and keep the item order, "
          "unless a finding cannot be fixed otherwise. Do not add facts. Prefer shortening wording to deleting an item. "
          "You cannot change font sizes, boxes or layout: only the words. Return the whole title and all items after your change.")

def prompt(sec, findings, history):
    lines = [f"CURRENT SECTION (JSON): {json.dumps({'title': sec.title, 'items': [i.model_dump(exclude={'sub'}) for i in sec.items]})}",
             "FINDINGS (from code that measured the rendered result):"]
    for n, f in enumerate(findings, 1):
        what = "the title" if f["role"] == "title" else "the item list"
        lines.append(f"  {n}. [{f['rule']}] {what} overflows its box by {f['over']} pt (measured need {f['need']} pt, have {f['have']} pt). Hint: shorten; do not reduce size.")
        if ARM == "B" and f["items"]:
            lines.append("     Height only drops in whole lines (about 22 pt each). Lines per item, measured:")
            for it in f["items"]:
                extra = f"; cutting about {it['cut_to_save_line']} characters (head, body or citation) brings it to {it['lines'] - 1} line(s)" if it["cut_to_save_line"] else ""
                lines.append(f"       items[{it['n']}]: {it['lines']} line(s){extra}")
    lines.append(f"CAPACITY: title is one line of about 45 characters at 34 pt bold. The item list box is {BODY_W} x {BODY_H} pt at 18 pt, about 10 lines of about 55 characters, including the citation text.")
    lines.append("EARLIER ATTEMPTS: " + ("; ".join(history) if history else "none") + ". Do not repeat a change that did not work.")
    return "\n".join(lines)

def key():
    if os.environ.get("ANTHROPIC_API_KEY"): return None
    r = subprocess.run(["security", "find-generic-password", "-s", "doclo-anthropic-api-key", "-w"], capture_output=True, text=True)
    if r.returncode: sys.exit("No key: set ANTHROPIC_API_KEY or store it with: security add-generic-password -a \"$USER\" -s doclo-anthropic-api-key -w")
    return r.stdout.strip()

def live_transport():
    import anthropic
    client = anthropic.Anthropic(api_key=key())
    def call(req):
        resp = client.beta.messages.create(**req)
        text = next((b.text for b in resp.content if b.type == "text"), None)
        return {"text": text, "stop_reason": resp.stop_reason, "model": resp.model,
                "usage": {"input_tokens": resp.usage.input_tokens, "output_tokens": resp.usage.output_tokens}}
    return call

def mock_transport(req):
    """Plumbing check only: crudely shortens every field, which should also trip the fact guard sometimes."""
    cur = json.loads(req["messages"][0]["content"].split("\n")[0].split(": ", 1)[1])
    cur["title"] = " ".join(cur["title"].split()[:4])
    for i in cur["items"]: i["body"] = " ".join(i["body"].split()[:9])
    cur["items"] = cur["items"][:4]; cur["reason"] = "mock shortening"
    return {"text": json.dumps(cur), "stop_reason": "end_turn", "model": "mock", "usage": {"input_tokens": 0, "output_tokens": 0}}

def run(mock):
    cassette = None if mock else Cassette.from_env(HERE / "cassettes" / ("s4b.json" if ARM == "B" else "s4.json"), transport=None if os.environ.get("DOCLO_RECORD") != "1" else live_transport())
    call = mock_transport if mock else cassette.call
    rows = []
    for s in seeds.seeds():
        orig = Section(id=s["id"], intent="parallel-set", title=s["title"],
                       items=[Item(head=i["head"], body=i["body"], citations=[Citation(**c) for c in i["citations"]]) for i in s["items"]])
        doc = Document(front={"doctype": "spike"}, format="slides", sections=[orig])
        allowed = fact_tokens(orig) | support_tokens(SOURCES_TEXT)
        findings0 = findings = measure(orig); history, attempts, rejected, usage = [], 0, 0, [0, 0]
        while findings and attempts < ATTEMPTS:
            attempts += 1
            sec = doc.sections[0]
            req = {"model": MODEL, "max_tokens": 16000, "system": SYSTEM, "messages": [{"role": "user", "content": prompt(sec, findings, history)}],
                   "output_config": {"effort": EFFORT, "format": {"type": "json_schema", "schema": SCHEMA}},
                   "betas": ["server-side-fallback-2026-07-01"], "fallbacks": "default"}
            out = call(req); usage[0] += out["usage"]["input_tokens"]; usage[1] += out["usage"]["output_tokens"]
            if out["stop_reason"] == "refusal" or not out["text"]:
                history.append(f"attempt {attempts}: no answer ({out['stop_reason']})"); continue
            data = json.loads(out["text"])
            cand = sec.model_copy(update={"title": data["title"], "items": [Item(head=i["head"] or None, body=i["body"], citations=[Citation(**c) for c in i["citations"]]) for i in data["items"]]})
            bad = sorted(fact_tokens(cand) - allowed)
            try:
                new = apply_patch(doc, Patch(base_rev=doc.rev, author="ai", reason=data["reason"],
                                  ops=[PatchOp(op="set_fields", section_id=sec.id, fields={"title": cand.title, "items": [i.model_dump() for i in cand.items]})]),
                                  fact_guard=lambda d, x: not bad)
            except PatchRejected as e:
                rejected += 1; history.append(f"attempt {attempts}: rejected by the fact guard, unsupported {bad}"); continue
            newf = measure(new.sections[0])
            if phi(newf) < phi(findings):
                doc, findings = new, newf; history.append(f"attempt {attempts}: accepted, {len(newf)} findings left")
            else:
                history.append(f"attempt {attempts}: no progress, still over by {sum(f['over'] for f in newf):.0f} pt")
        final = doc.sections[0]
        lost = sorted(fact_tokens(orig) - fact_tokens(final))
        cites_o = {(c.key, c.locator) for i in orig.items for c in i.citations}; cites_f = {(c.key, c.locator) for i in final.items for c in i.citations}
        rows.append(dict(id=s["id"], kind=s["kind"], start=len(findings0), cleared=not findings, attempts=attempts, rejected=rejected,
                         facts=len(fact_tokens(orig)), lost=lost, cites_lost=len(cites_o - cites_f),
                         items=(len(orig.items), len(final.items)), usage=usage, history=history, title=final.title))
    return rows

def report(rows):
    n = len(rows); cleared = sum(r["cleared"] for r in rows)
    facts = sum(r["facts"] for r in rows); lost = sum(len(r["lost"]) for r in rows)
    tin = sum(r["usage"][0] for r in rows); tout = sum(r["usage"][1] for r in rows)
    print(f"cleared in <= {ATTEMPTS} attempts: {cleared}/{n}")
    for k in ("title", "body", "both"):
        rs = [r for r in rows if r["kind"] == k]; print(f"   {k:5s} {sum(r['cleared'] for r in rs)}/{len(rs)}  attempts used {[r['attempts'] for r in rs]}")
    print(f"facts kept: {facts - lost}/{facts} ({100 * (facts - lost) / facts:.1f}%); citations lost: {sum(r['cites_lost'] for r in rows)}; "
          f"items deleted: {sum(a - b for a, b in (r['items'] for r in rows))}; patches rejected by the fact guard: {sum(r['rejected'] for r in rows)}")
    print(f"tokens: {tin} in, {tout} out; cost about ${(tin * PRICE_IN + tout * PRICE_OUT) / 1e6:.2f}")
    for r in rows:
        if not r["cleared"] or r["lost"]: print(f"   {r['id']}: cleared={r['cleared']} lost={r['lost']} | {' / '.join(r['history'])}")
    (HERE / "out").mkdir(exist_ok=True); (HERE / "out" / ("s4-mock.json" if "--mock" in sys.argv else f"s4-arm{ARM}.json")).write_text(json.dumps(rows, indent=2) + "\n")

if __name__ == "__main__":
    report(run("--mock" in sys.argv))
