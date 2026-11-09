# Intent: the critic eval measures labelled crops reproducibly and preserves the heal eval.
import asyncio
import importlib
import importlib.util
import re
import shutil
import subprocess
import sys
from collections import Counter
from pathlib import Path

import pytest
import yaml
from PIL import Image

from docla import cli
from docla.theme import load_theme, neutral_theme


def optional(name):
    try:
        return importlib.import_module(name)
    except ImportError as error:
        if (error.name != name and not name.startswith(str(error.name) + ".")) or (
            error.name and importlib.util.find_spec(error.name) is not None
        ):
            raise
        return None


critic = optional("docla.evals.critic")
rubric = optional("docla.theme.rubric")
sheets = optional("docla.facts.sheets")
ROOT = Path(__file__).resolve().parents[2]
CASES = ROOT / "tests/fixtures/critic-eval"
ITEMS = {"sem.focal-point", "sem.repetition", "sem.balance"}
MUTATIONS = {"cramped": "sem.focal-point", "off-balance": "sem.balance", "repeated": "sem.repetition"}


def need(module, *names):
    assert module is not None, "required public module must exist"
    for name in names:
        assert hasattr(module, name), f"{module.__name__}.{name} must exist"
    return module


def run(argv, capsys):
    try:
        code = cli.main(argv)
    except SystemExit as error:
        code = error.code if isinstance(error.code, int) else 1
    captured = capsys.readouterr()
    return code, captured.out, captured.err


def test_D1_labelled_crops_and_rubric():
    cases = need(critic, "load_cases").load_cases(CASES)
    ids = need(rubric, "load_rubric").load_rubric(neutral_theme()).ids()
    assert len(cases) >= 12 and len({case.id for case in cases}) == len(cases)
    counts = Counter((case.rubric_id, case.verdict) for case in cases)
    for case in cases:
        assert case.crop.is_file() and case.rubric_id in ids
        with Image.open(case.crop) as image:
            assert image.format == "PNG" and max(image.size) <= 1568
    for item in ITEMS:
        assert counts[item, "pass"] >= 2 and counts[item, "fail"] >= 2


def test_D2_mutations_and_script(tmp_path):
    module = need(critic, "load_cases", "mutate", "MUTATIONS")
    sheet = need(sheets, "contact_sheet")
    assert module.MUTATIONS == MUTATIONS
    cases = module.load_cases(CASES)
    source = next(c.crop for c in cases if c.rubric_id == "sem.focal-point" and c.verdict == "pass")
    for kind in ("cramped", "off-balance"):
        first, second = tmp_path / f"{kind}.png", tmp_path / f"{kind}-again.png"
        assert module.mutate(source, kind, first) == first
        module.mutate(source, kind, second)
        assert first.read_bytes() == second.read_bytes() != source.read_bytes()
        with Image.open(source) as original, Image.open(first) as changed:
            assert changed.format == "PNG" and changed.size == original.size
    repeated, expected = tmp_path / "repeated.png", tmp_path / "expected.png"
    module.mutate(source, "repeated", repeated)
    sheet.contact_sheet([source] * 4, ["1", "2", "3", "4"], expected)
    assert repeated.read_bytes() == expected.read_bytes()
    with pytest.raises(ValueError):
        module.mutate(source, "blurred", tmp_path / "bad.png")
    inputs, outputs = tmp_path / "inputs", tmp_path / "outputs"
    inputs.mkdir()
    shutil.copyfile(source, inputs / "one.png")
    shutil.copyfile(source, inputs / "two.png")
    script = ROOT / "scripts/mutate_crops.py"
    assert script.is_file(), "scripts/mutate_crops.py must exist"
    result = subprocess.run([sys.executable, str(script), str(inputs), str(outputs)], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    assert {p.name for p in outputs.glob("*.png")} == {
        f"{stem}-{kind}.png" for stem in ("one", "two") for kind in MUTATIONS
    }
    entries = yaml.safe_load((outputs / "mutations.yaml").read_text())["cases"]
    assert len(entries) == 6 and len({entry["id"] for entry in entries}) == 6
    for entry in entries:
        assert entry["verdict"] == "fail"
        assert any(Path(entry["crop"]).name == f"{stem}-{kind}.png" and entry["rubric_id"] == item
                   for stem in ("one", "two") for kind, item in MUTATIONS.items())


def test_D3_pooled_metrics_and_agreement(tmp_path):
    module = need(critic, "CriticCase", "run_critic", "calibration_yaml")
    labels = ["fail", "fail", "fail", "pass", "pass", "pass"]
    cases = [module.CriticCase(id=str(i), crop=tmp_path / f"{i}.png", rubric_id="sem.balance", verdict=label)
             for i, label in enumerate(labels)]
    cases.append(module.CriticCase(id="none", crop=tmp_path / "none.png", rubric_id="sem.repetition", verdict="fail"))
    calls = []

    async def verdict(case, run_number):
        calls.append((case.id, run_number))
        if case.id == "none":
            return "unsure"
        first = ("fail", "fail", "pass", "fail", "pass", "pass")
        second = ("fail", "pass", "pass", "fail", "pass", "pass")
        return (first if run_number == 1 else second)[int(case.id)]

    report = asyncio.run(module.run_critic(cases, verdict))
    assert sorted(calls) == sorted((case.id, n) for case in cases for n in (1, 2))

    def mappings(value):
        if isinstance(value, dict):
            yield value
            for child in value.values():
                yield from mappings(child)
        elif isinstance(value, (list, tuple)):
            for child in value:
                yield from mappings(child)

    rows = list(mappings(report.model_dump()))
    assert any(row.get("tp") == 3 and row.get("fp") == 2 and row.get("fn") == 3
               and row.get("precision") == pytest.approx(0.6) and row.get("recall") == pytest.approx(0.5)
               and row.get("agreement") == pytest.approx(5 / 6) for row in rows)
    assert any(row.get("precision", "missing") is None for row in rows)
    calibration = yaml.safe_load(module.calibration_yaml(report))["items"]
    assert calibration["sem.balance"]["precision"] == pytest.approx(0.6)
    assert "sem.repetition" not in calibration


def test_D4_offline_results_and_calibration(tmp_path, capsys):
    module = need(critic, "load_cases")
    calibration_api = need(rubric, "load_calibration")
    items = {case.rubric_id for case in module.load_cases(CASES)}
    outputs = []
    for name in ("first", "second"):
        out, cal = tmp_path / name / "CRITIC.md", tmp_path / name / "calibration.yaml"
        code, stdout, stderr = run(["eval", "critic", "--cases", str(CASES), "--out", str(out),
                                    "--calibration", str(cal)], capsys)
        assert code == 0, (stdout, stderr)
        assert out.is_file() and cal.is_file()
        outputs.append((out.read_bytes(), cal.read_bytes()))
    assert outputs[0] == outputs[1]
    lines = outputs[0][0].decode().splitlines()
    assert lines[:2] == ["# Critic eval", ""]
    assert "Mode: offline" in lines and "Runs: 2" in lines
    assert any(re.fullmatch(r"Agreement: (\d+) / \1 \(100\.0%\)", line) for line in lines)
    for item in items:
        assert any(line.startswith(f"| {item} |") and line.endswith("| yes |") for line in lines)
    text = outputs[0][1].decode()
    assert text.splitlines()[0] == "# docla eval critic, mode: offline"
    entries = yaml.safe_load(text)["items"]
    assert set(entries) == items
    for item in items:
        assert entries[item]["precision"] == 1.0 and entries[item]["recall"] == 1.0
    theme_root = tmp_path / "theme"
    shutil.copytree(neutral_theme().root, theme_root)
    (theme_root / "rubric").mkdir(exist_ok=True)
    (theme_root / "rubric/calibration.yaml").write_text(text)
    loaded = calibration_api.load_calibration(load_theme(theme_root))
    loaded_items = loaded if isinstance(loaded, dict) else loaded.items
    for item in items:
        entry = loaded_items[item]
        # load_calibration (M4.06, merged) returns {item: precision} as floats.
        value = entry if isinstance(entry, (int, float)) else (entry["precision"] if isinstance(entry, dict) else entry.precision)
        assert value == 1.0


def test_D5_live_opt_in_and_offline_does_not_write_theme(tmp_path, capsys, monkeypatch):
    write = need(optional("docla.write"), "live_transport")
    calls = []
    monkeypatch.setattr(write, "live_transport", lambda: calls.append(True))
    monkeypatch.delenv("DOCLA_LIVE", raising=False)
    out = tmp_path / "live/CRITIC.md"
    code, _, err = run(["eval", "critic", "--live", "--out", str(out)], capsys)
    assert code == 2 and "DOCLA_LIVE=1" in err and not out.exists() and calls == []
    root = neutral_theme().root
    before = {p.relative_to(root) for p in root.rglob("*") if p.is_file()}
    offline = tmp_path / "offline/CRITIC.md"
    code, stdout, err = run(["eval", "critic", "--cases", str(CASES), "--out", str(offline)], capsys)
    assert code == 0, (stdout, err)
    assert offline.is_file() and {p for p in offline.parent.rglob("*") if p.is_file()} == {offline}
    assert {p.relative_to(root) for p in root.rglob("*") if p.is_file()} == before


def test_D6_heal_eval_remains_deterministic_and_requires_live_opt_in(tmp_path, capsys, monkeypatch):
    outputs = [tmp_path / "first/RESULTS.md", tmp_path / "second/RESULTS.md"]
    for output in outputs:
        code, stdout, err = run(["eval", "heal", "--cases", str(ROOT / "tests/fixtures/heal-eval"),
                                 "--out", str(output)], capsys)
        assert code == 0, (stdout, err)
        assert output.is_file()
    assert outputs[0].read_bytes() == outputs[1].read_bytes()
    lines = outputs[0].read_text().splitlines()
    assert lines[0] == "# Heal eval"
    assert {"Mode: offline", "Cases: 40", "Gate: met"} <= set(lines)
    monkeypatch.delenv("DOCLA_LIVE", raising=False)
    live = tmp_path / "live/RESULTS.md"
    code, _, err = run(["eval", "heal", "--live", "--out", str(live)], capsys)
    assert code == 2 and "DOCLA_LIVE=1" in err and not live.exists()
