# Intent: project configuration, cost accounting, initialisation and credential reporting are reliable.
import importlib
import importlib.util
import json
import sys

import pytest


def _subject(name):
    try:
        return importlib.import_module(name)
    except ImportError as error:
        if error.name != name or importlib.util.find_spec(name) is not None:
            raise
        return None


config = _subject("docla.config")
ledger_module = _subject("docla.agents.ledger")
cli = _subject("docla.cli")


def _require(module, *names):
    assert module is not None, "public module must exist"
    for name in names:
        assert hasattr(module, name), f"{module.__name__}.{name} must exist"


def _run(argv, capsys):
    _require(cli, "main")
    try:
        code = cli.main(argv)
    except SystemExit as error:
        code = error.code
    captured = capsys.readouterr()
    return code, captured.out, captured.err


def test_D1_defaults_and_overrides(tmp_path):
    _require(config, "load_project_config", "ProjectConfig")
    loaded = config.load_project_config(tmp_path)
    assert (loaded.loop.micro_attempts, loaded.loop.best_of_n, loaded.loop.macro_rounds) == (3, 3, 2)
    assert loaded.loop.max_parallel_sections == 6
    assert loaded.loop.act_on_uncorroborated is False
    assert (loaded.budget.max_usd_per_document, loaded.budget.max_wall_seconds, loaded.budget.warn_at_fraction) == (
        5.0, 900, 0.7
    )
    assert loaded.models == {
        "writer": "claude-sonnet-5-5", "critic": "claude-opus-5-5",
        "diagnose": "claude-opus-5-5", "triage": "claude-haiku-4-5",
    }
    assert loaded.prices == {}
    (tmp_path / "docla.toml").write_text(
        '[loop]\nmicro_attempts = 2\n[models]\nwriter = "w"\n'
        '[prices."w"]\ninput = 3.0\noutput = 15.0\n', encoding="utf-8"
    )
    loaded = config.load_project_config(tmp_path)
    assert loaded.loop.micro_attempts == 2
    assert loaded.loop.best_of_n == 3
    assert loaded.models == {
        "writer": "w", "critic": "claude-opus-5-5",
        "diagnose": "claude-opus-5-5", "triage": "claude-haiku-4-5",
    }
    assert loaded.prices["w"].input == 3.0
    assert loaded.prices["w"].output == 15.0
    assert loaded.prices["w"].cache_read == 0.0
    assert loaded.prices["w"].cache_write == 0.0


@pytest.mark.parametrize("content", ['[loop]\nunknown = 1\n', '[loop\n'])
def test_D1_invalid_configuration_names_file(tmp_path, content):
    _require(config, "load_project_config", "ConfigError")
    path = tmp_path / "docla.toml"
    path.write_text(content, encoding="utf-8")
    with pytest.raises(config.ConfigError) as caught:
        config.load_project_config(tmp_path)
    assert "docla.toml" in str(caught.value)


def _ledger(path, max_usd=None):
    _require(config, "Price")
    _require(ledger_module, "Ledger", "PriceMissing", "BudgetExceeded")
    price = config.Price(input=3.0, output=15.0, cache_read=0.3, cache_write=3.75)
    return ledger_module.Ledger(path, {"m": price}, max_usd=max_usd)


def _usage():
    return {"input_tokens": 1000, "output_tokens": 2000, "cache_read_input_tokens": 10000,
            "cache_creation_input_tokens": 400}


def test_D2_cost_jsonl_append_and_missing_price(tmp_path):
    path = tmp_path / "nested" / "calls.jsonl"
    ledger = _ledger(path)
    assert ledger.total == 0
    assert ledger.add("writer.draft", "m", _usage()) == pytest.approx(0.0375, abs=1e-9)
    first = path.read_bytes()
    assert first.endswith(b"\n")
    record = json.loads(first)
    assert record.pop("usd") == pytest.approx(0.0375, abs=1e-9)
    assert record == {"role": "writer.draft", "model": "m", "input": 1000, "cache_read": 10000,
                      "cache_write": 400, "output": 2000}
    assert ledger.add("critic", "m", {"input_tokens": 1000}) == pytest.approx(0.003, abs=1e-9)
    lines = path.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 2
    assert json.loads(lines[1]) == {"role": "critic", "model": "m", "input": 1000, "cache_read": 0,
                                    "cache_write": 0, "output": 0, "usd": 0.003}
    assert ledger.total == pytest.approx(0.0405, abs=1e-9)
    before = path.read_bytes()
    with pytest.raises(ledger_module.PriceMissing, match="missing-model"):
        ledger.add("writer", "missing-model", _usage())
    assert path.read_bytes() == before
    assert ledger.total == pytest.approx(0.0405, abs=1e-9)


def test_D3_budget_exceeded_after_recording(tmp_path):
    path = tmp_path / "calls.jsonl"
    ledger = _ledger(path, max_usd=0.05)
    assert ledger.add("writer.draft", "m", _usage()) == pytest.approx(0.0375, abs=1e-9)
    with pytest.raises(ledger_module.BudgetExceeded):
        ledger.add("writer.draft", "m", _usage())
    assert len(path.read_text(encoding="utf-8").splitlines()) == 2
    assert ledger.total == pytest.approx(0.075, abs=1e-9)


def test_D4_init_creates_project_and_preserves_existing_config(tmp_path, capsys):
    _require(config, "load_project_config", "ProjectConfig")
    folder = tmp_path / "new" / "project"
    path = folder / "docla.toml"
    code, out, _ = _run(["init", str(folder)], capsys)
    assert code == 0
    assert str(path) in out
    assert (folder / "sources").is_dir()
    assert config.load_project_config(folder) == config.ProjectConfig()
    original = path.read_bytes()
    code, _, err = _run(["init", str(folder)], capsys)
    assert code == 1
    assert "docla.toml" in err
    assert path.read_bytes() == original


@pytest.mark.parametrize("key, expected", [("sk-test-value", "set"), (None, "missing"), ("", "missing")])
def test_D5_doctor_reports_key_without_exposing_it(tmp_path, monkeypatch, capsys, key, expected):
    monkeypatch.setenv("PATH", str(tmp_path))
    if key is None:
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    else:
        monkeypatch.setenv("ANTHROPIC_API_KEY", key)
    code, out, err = _run(["doctor"], capsys)
    lines = out.splitlines()
    v = sys.version_info
    assert lines[0] == f"python: {v.major}.{v.minor}.{v.micro}"
    assert lines[1].startswith("typst: ")
    assert lines[-1] == f"anthropic key: {expected}"
    assert "sk-test-value" not in out + err
    assert code == 0
