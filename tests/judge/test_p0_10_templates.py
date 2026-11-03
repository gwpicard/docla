# Intent: issue templates and a fixed set of area and severity labels exist under .github/.
import json
import re
from pathlib import Path

GITHUB = Path(__file__).resolve().parents[2] / ".github"
AREAS = ["model", "source", "theme", "render", "facts", "checks", "loop", "learn", "ingest", "agents", "server", "web", "ci", "docs"]
SEVERITIES = ["blocker", "major", "minor"]
EXPECTED_NAMES = {f"area:{a}" for a in AREAS} | {f"severity:{s}" for s in SEVERITIES}


def _read(relative: str) -> str:
    path = GITHUB / relative
    assert path.is_file(), f".github/{relative} must exist"
    return path.read_text(encoding="utf-8")


def _labels() -> list:
    return json.loads(_read("labels.json"))


def _dropdown_options(text: str, keyword: str) -> list[str]:
    """Option values of the dropdown whose block mentions `keyword` in its id or label."""
    blocks = re.split(r"(?m)^\s*-\s+type:\s*", text)
    for block in blocks:
        if not block.startswith("dropdown"):
            continue
        head = block.split("options:")[0].lower()
        if keyword in head:
            tail = block.split("options:", 1)[1]
            options = []
            for line in tail.splitlines()[1:]:
                match = re.match(r"\s+-\s+(.*\S)\s*$", line)
                if match:
                    options.append(match.group(1).strip().strip("\"'"))
                elif line.strip() and not line.strip().startswith("#"):
                    break
            return options
    raise AssertionError(f"bug.yml must have a dropdown for {keyword}")


def _short(option: str) -> str:
    return option.split(":", 1)[1] if ":" in option else option


def test_D1_labels_json_is_valid_list_of_labels():
    labels = _labels()
    assert isinstance(labels, list) and labels, "labels.json must be a non-empty list"
    for label in labels:
        assert isinstance(label, dict)
        assert isinstance(label.get("name"), str) and label["name"].strip()
        assert isinstance(label.get("color"), str) and re.fullmatch(r"[0-9a-fA-F]{6}", label["color"]), label
        assert isinstance(label.get("description"), str) and label["description"].strip()
    names = [label["name"] for label in labels]
    assert len(names) == len(set(names)), "label names must be unique"


def test_D2_labels_are_exactly_the_area_and_severity_set():
    names = [label["name"] for label in _labels()]
    assert len(names) == 17
    assert set(names) == EXPECTED_NAMES


def test_D3_bug_form_has_fields_and_options_match_labels():
    text = _read("ISSUE_TEMPLATE/bug.yml")
    assert re.search(r"(?m)^name:\s*\S", text), "bug.yml needs name:"
    assert re.search(r"(?m)^description:\s*\S", text), "bug.yml needs description:"
    assert re.search(r"steps to reproduce", text, re.IGNORECASE)
    areas = _dropdown_options(text, "area")
    severities = _dropdown_options(text, "severity")
    assert sorted(_short(o) for o in areas) == sorted(AREAS)
    assert sorted(_short(o) for o in severities) == sorted(SEVERITIES)


def test_D4_feature_template_and_config_disable_blank_issues():
    feature = _read("ISSUE_TEMPLATE/feature.yml")
    assert re.search(r"(?m)^name:\s*\S", feature), "feature.yml needs name:"
    assert re.search(r"(?m)^description:\s*\S", feature), "feature.yml needs description:"
    config = _read("ISSUE_TEMPLATE/config.yml")
    assert re.search(r"(?m)^blank_issues_enabled:\s*false\s*$", config)
