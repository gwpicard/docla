# Intent: component layout facts provide a shared, drift-sensitive golden harness.
import importlib
import importlib.util
import json
import os
import subprocess
from pathlib import Path

try:
    golden = importlib.import_module("docla.testing.golden")
except ImportError as error:
    if error.name not in {"docla.testing", "docla.testing.golden"}:
        raise
    if error.name == "docla.testing" and importlib.util.find_spec("docla.testing") is not None:
        raise
    if error.name == "docla.testing.golden" and importlib.util.find_spec("docla.testing.golden") is not None:
        raise
    golden = None

ROOT = Path(__file__).resolve().parents[2]


def test_D1_equal_and_tolerance_and_role_named_for_drift():
    assert golden is not None and hasattr(golden, "compare_facts"), "compare_facts must exist"
    baseline = {"item": {"marks": [{"page": 1, "x0": 10.0, "y0": 20.0, "x1": 30.0, "y1": 40.0}], "words": []}}
    within = {"item": {"marks": [{"page": 1, "x0": 10.5, "y0": 19.5, "x1": 30.5, "y1": 39.5}], "words": []}}
    outside = {"item": {"marks": [{"page": 1, "x0": 10.51, "y0": 20.0, "x1": 30.0, "y1": 40.0}], "words": []}}
    assert golden.compare_facts(baseline, baseline) == []
    assert golden.compare_facts(within, baseline) == []
    messages = golden.compare_facts(outside, baseline)
    assert isinstance(messages, list) and any("item" in message for message in messages)


def test_D2_role_and_mark_count_differences():
    assert golden is not None and hasattr(golden, "compare_facts"), "compare_facts must exist"
    box = {"page": 1, "x0": 10.0, "y0": 20.0, "x1": 30.0, "y1": 40.0}
    baseline = {"item": {"marks": [box], "words": []}}
    assert golden.compare_facts({}, baseline)
    assert golden.compare_facts(baseline, {})
    assert golden.compare_facts({"item": {"marks": [], "words": []}}, baseline)
    assert golden.compare_facts({"item": {"marks": [box, box], "words": []}}, baseline)


def test_D3_fixture_and_script_round_trip(tmp_path):
    assert golden is not None and hasattr(golden, "facts_for"), "facts_for must exist"
    assert hasattr(golden, "compare_facts"), "compare_facts must exist"
    (tmp_path / "bullets.yaml").write_text(
        'id: s1\nintent: bullets\ntitle: Animals\nitems:\n  - head: Marmot\n    body: Lives in burrows\n  - head: Ocelot\n    body: Lives in forests\n',
        encoding="utf-8",
    )
    facts = golden.facts_for("bullets", tmp_path)
    assert isinstance(facts, dict)
    assert "item" in facts and len(facts["item"]["marks"]) == 2
    script = ROOT / "scripts/golden_facts.py"
    assert script.is_file(), "scripts/golden_facts.py must exist"
    result = subprocess.run(
        ["uv", "run", "python", str(script), "bullets", "--fixtures", str(tmp_path)],
        cwd=ROOT, capture_output=True, text=True, env={**os.environ, "UV_NO_SYNC": "1"},
    )
    assert result.returncode == 0, result.stdout + result.stderr
    output = tmp_path / "bullets.facts.json"
    assert output.is_file()
    saved = json.loads(output.read_text(encoding="utf-8"))
    assert golden.compare_facts(golden.facts_for("bullets", tmp_path), saved) == []


def test_D4_component_harness_passes():
    harness = ROOT / "tests/test_components.py"
    assert harness.is_file(), "tests/test_components.py must exist"
    result = subprocess.run(
        ["uv", "run", "python", "-m", "pytest", "tests/test_components.py", "-q"],
        cwd=ROOT, capture_output=True, text=True, env={**os.environ, "UV_NO_SYNC": "1"},
    )
    assert result.returncode == 0, result.stdout + result.stderr
