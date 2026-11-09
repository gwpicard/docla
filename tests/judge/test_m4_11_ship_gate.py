# Intent: final builds record readiness evidence and the ship gate controls promotion to ready.
import importlib
import importlib.util
import json
import runpy
from pathlib import Path

import pytest

from docla import cli

try:
    gate = importlib.import_module("docla.store.gate")
except ImportError as error:
    if error.name not in ("docla.store", "docla.store.gate"):
        raise
    if importlib.util.find_spec(error.name) is not None:
        raise
    gate = None

FIXTURES = Path(__file__).parent
M1 = runpy.run_path(str(FIXTURES / "test_m1_17_cli_build_check.py"))
M2 = runpy.run_path(str(FIXTURES / "test_m2_theme_in_builds.py"))
SLIDES = M1["SLIDES"]
GAP = SLIDES.replace("- Cheap to repeat.", "- [GAP: owner name]")


def run(args, capsys):
    try:
        code = cli.main(args)
    except SystemExit as error:
        code = error.code if isinstance(error.code, int) else 1
    captured = capsys.readouterr()
    return code, captured.out, captured.err


def build(tmp_path, capsys, text=SLIDES):
    tmp_path.mkdir(parents=True, exist_ok=True)
    source = tmp_path / "deck.md"
    source.write_text(text)
    result = run(["build", "--final", str(source), "--out", str(tmp_path / "out")], capsys)
    return result, tmp_path / "deck.versions" / "v1"


def manifest(version):
    return json.loads((version / "manifest.json").read_text())


def test_D1_final_build_reports_gap_and_clean_gate(tmp_path, capsys):
    (code, out, _), version = build(tmp_path / "gap", capsys, GAP)
    assert code == 1, out
    assert "not ready: 1 gaps" in out.splitlines()
    assert any(line.startswith("not ready: ") and line.endswith("error findings") for line in out.splitlines())
    assert (manifest(version)["final"], manifest(version)["state"]) == (True, "draft")
    (code, out, _), version = build(tmp_path / "clean", capsys)
    assert code == 0, out
    assert out.splitlines() == [str(tmp_path / "clean" / "out" / "deck.pdf"), str(version), "gate: passed"]
    assert manifest(version)["look"]["could_not"] == []
    assert manifest(version)["look"]["tiers"]["semantic"] == "skipped"
    assert manifest(version)["state"] == "draft"


def test_D2_ship_gate_evidence_and_reason_order(tmp_path, capsys):
    assert gate is not None and hasattr(gate, "ship_gate"), "docla.store.gate.ship_gate must exist"
    store = importlib.import_module("docla.store")
    assert hasattr(store, "load_version") and hasattr(store, "write_version")
    from docla.facts.layout import LayoutFacts
    from docla.model import Finding
    from docla.render.compose import compose
    from docla.source.parser import parse
    from docla.theme import neutral_theme

    _, version = build(tmp_path, capsys, GAP)
    assert (version / "manifest.json").is_file(), "final build must write a version"
    look = store.load_version(version).manifest.look
    doc, _ = parse(GAP)
    comp = compose(doc)
    facts = LayoutFacts(pdf_sha256="0" * 64, pages=[], words=[], shapes=[], marks=[])
    finding = Finding(
        id="vision-test",
        rule_id="vision.test",
        tier="semantic",
        severity="error",
        format="slides",
        message="Vision finding",
        fingerprint="vision-test",
        remedy={"class": "report", "hint": "Review"},
        corroborated=False,
    )

    def write(findings, look_record):
        return store.write_version(
            tmp_path / "deck.md",
            doc,
            comp,
            tmp_path / "out" / "deck.pdf",
            facts,
            findings,
            [],
            None,
            theme=neutral_theme(),
            final=False,
            look=look_record,
        )

    assert gate.ship_gate(write([], None))[0] == "not fully looked at"
    incomplete = look.model_copy(update={"could_not": ["semantic page 2: timeout"]})
    reasons = gate.ship_gate(write([finding], incomplete))
    assert reasons[0] == "not fully looked at: semantic page 2: timeout"
    assert "unacknowledged vision findings" in reasons
    assert not any(reason.endswith(" gaps") for reason in reasons)
    corroborated = finding.model_copy(update={"corroborated": True})
    assert "unacknowledged vision findings" not in gate.ship_gate(write([corroborated], incomplete))


def test_D3_force_requires_reason_and_records_it(tmp_path, capsys):
    _, version = build(tmp_path, capsys, GAP)
    path = version / "manifest.json"
    assert path.is_file(), "final build must write a manifest"
    before = path.read_bytes()
    for extra in ([], ["--reason", "  "]):
        code, _, err = run(["ready", str(version), "--force", *extra], capsys)
        assert code == 2 and "--reason" in err
        assert path.read_bytes() == before
    code, out, _ = run(["ready", str(version), "--force", "--reason", "owner accepts the gap"], capsys)
    assert code == 0 and out.splitlines() == ["ready (forced: owner accepts the gap)"]
    assert (manifest(version)["state"], manifest(version)["forced_reason"]) == ("ready", "owner accepts the gap")


def test_D4_ready_refuses_gap_and_accepts_clean(tmp_path, capsys):
    _, refused = build(tmp_path / "gap", capsys, GAP)
    code, out, _ = run(["ready", str(refused)], capsys)
    assert code == 1
    assert "not ready: 1 gaps" in out.splitlines()
    assert manifest(refused)["state"] == "draft"
    _, clean = build(tmp_path / "clean", capsys)
    code, out, _ = run(["ready", str(clean)], capsys)
    assert code == 0 and out.splitlines() == ["ready"]
    assert (manifest(clean)["state"], manifest(clean)["forced_reason"]) == ("ready", None)


def test_D5_plain_build_retains_output(tmp_path, capsys):
    source = tmp_path / "deck.md"
    source.write_text(SLIDES)
    pdf = tmp_path / "out" / "deck.pdf"
    code, out, _ = run(["build", str(source), "--out", str(pdf.parent)], capsys)
    assert code == 0 and out.splitlines() == [str(pdf)]
    assert pdf.is_file() and not (tmp_path / "deck.versions").exists()


@pytest.mark.parametrize("text", [M1["SLIDES"], M1["DOC"], M2["SLIDES"], M2["DOC"]])
def test_D6_check_clean_documents_unchanged(tmp_path, capsys, text):
    source = tmp_path / "input.md"
    source.write_text(text)
    code, out, _ = run(["check", str(source), "--out", str(tmp_path / "out")], capsys)
    assert code == 0 and out.splitlines() == ["no findings"]
