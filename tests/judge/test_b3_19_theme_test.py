# Intent: The neutral gold corpus and theme test command demonstrate that a theme is whole.
import re
import shutil
from pathlib import Path

import yaml

try:
    from docla import cli
    from docla.render import compose
    from docla.source import parser
except ImportError as error:
    if error.name not in {
        "docla",
        "docla.cli",
        "docla.render",
        "docla.render.compose",
        "docla.source",
        "docla.source.parser",
    }:
        raise
    cli = compose = parser = None

ROOT = Path(__file__).resolve().parents[2]
NEUTRAL = ROOT / "src/docla/themes/neutral"
CHOOSER = ROOT / "src/docla/render/chooser.yaml"


def _run(args, capsys):
    assert cli is not None and hasattr(cli, "main"), "docla.cli.main must exist"
    try:
        code = cli.main(args)
    except SystemExit as error:
        code = error.code
    captured = capsys.readouterr()
    return code, captured.out, captured.err


def _copy_theme(tmp_path):
    assert NEUTRAL.is_dir(), "neutral theme must exist"
    target = tmp_path / "theme"
    shutil.copytree(NEUTRAL, target)
    return target


def test_D1_gold_files_parse_compose_and_pass_final_check(tmp_path, capsys):
    assert parser is not None and hasattr(parser, "parse"), "docla.source.parser.parse must exist"
    assert compose is not None and hasattr(compose, "compose"), "docla.render.compose.compose must exist"
    for name, fmt, doctype in (("deck.md", "slides", "pitch-deck"), ("report.md", "doc", "report")):
        path = NEUTRAL / "exemplars" / "gold" / name
        assert path.is_file(), f"{path} must exist"
        document, findings = parser.parse(path.read_text())
        assert findings == [], (name, findings)
        assert document.format == fmt
        assert document.front.get("doctype") == doctype
        if name == "deck.md":
            assert len({section.component for section in compose.compose(document).sections}) >= 5
        code, out, err = _run(["check", str(path), "--final", "--out", str(tmp_path / name)], capsys)
        assert code == 0, (name, out, err)
        assert not any(line.startswith("error") for line in out.splitlines()), out


def test_D2_default_theme_suite_succeeds_in_order(capsys, monkeypatch):
    monkeypatch.chdir(ROOT)
    code, out, err = _run(["theme", "test"], capsys)
    assert code == 0, (out, err)
    lines = out.splitlines()
    assert len(lines) == 5, lines
    for line, step in zip(lines, ("rules", "chooser", "doctypes", "fixtures", "gold"), strict=True):
        assert re.fullmatch(rf"ok {step}(?: \[\d+\])?", line), line


def test_D3_unknown_chooser_component_names_intent_and_component(tmp_path, capsys):
    theme = _copy_theme(tmp_path)
    chooser = yaml.safe_load(CHOOSER.read_text())
    chooser["intents"]["bullets"]["slides"][0]["component"] = "no-such-component"
    (theme / "chooser.yaml").write_text(yaml.safe_dump(chooser))
    code, out, err = _run(["theme", "test", "--theme", str(theme)], capsys)
    assert code == 1, (out, err)
    assert any(
        line.startswith("fail chooser:") and "bullets" in line and "no-such-component" in line
        for line in out.splitlines()
    ), out


def test_D4_rule_without_provenance_names_file(tmp_path, capsys):
    theme = _copy_theme(tmp_path)
    authored = theme / "rules" / "authored"
    authored.mkdir(parents=True, exist_ok=True)
    (authored / "bad.yaml").write_text(
        yaml.safe_dump(
            {
                "id": "test.no-provenance",
                "title": "Missing provenance",
                "origin": "manual",
                "strength": "soft",
                "status": "active",
                "severity": "warning",
                "tier": "source",
                "scope": {"format": "slides"},
                "check": {"kind": "empty-section"},
                "remedy": {"class": "report", "hint": "Add content."},
            }
        )
    )
    code, out, err = _run(["theme", "test", "--theme", str(theme)], capsys)
    assert code == 1, (out, err)
    assert any(line.startswith("fail rules:") and "bad.yaml" in line for line in out.splitlines()), out


def test_D5_gold_unresolved_citation_names_file_and_rule(tmp_path, capsys):
    theme = _copy_theme(tmp_path)
    gold = theme / "exemplars" / "gold"
    gold.mkdir(parents=True, exist_ok=True)
    (gold / "broken.md").write_text("""---
doctype: pitch-deck
format: slides
title: Evidence
---

## Sources

- [S1] Workshop notes

::: {#abcde .section intent="bullets"}
## Findings

- A claim. [S2]
:::
""")
    code, out, err = _run(["theme", "test", "--theme", str(theme)], capsys)
    assert code == 1, (out, err)
    assert any(
        line.startswith("fail gold:") and "broken.md" in line and "source.citations-resolve" in line
        for line in out.splitlines()
    ), out


def test_D6_missing_tokens_is_theme_error(tmp_path, capsys):
    theme = tmp_path / "empty"
    theme.mkdir()
    code, out, err = _run(["theme", "test", "--theme", str(theme)], capsys)
    assert code == 2, (out, err)
    assert "tokens.yaml" in err
