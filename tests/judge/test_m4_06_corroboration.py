# Intent: Semantic findings require corroboration and calibration before they can drive repairs.
import asyncio
import importlib
import importlib.util
import json
import shutil

import pytest
from PIL import Image

from docla.agents.client import Claude
from docla.loop.router import route
from docla.model import Box, Finding, Remedy, Section
from docla.testing.fakes import FakeTransport, fake_response
from docla.theme import ThemeError, load_theme, neutral_theme


def optional_module(name):
    try:
        return importlib.import_module(name)
    except ImportError as error:
        if error.name != name and not str(error.name).startswith(name + "."):
            raise
        if importlib.util.find_spec(name) is not None:
            raise
        return None


critic = optional_module("docla.agents.critic")
rubric = optional_module("docla.theme.rubric")


def interfaces():
    assert critic is not None, "docla.agents.critic must exist"
    assert rubric is not None, "docla.theme.rubric must exist"
    for name in ("corroborate", "calibrate", "CriticImage", "Region"):
        assert hasattr(critic, name), f"critic.{name} must exist"
    for name in ("load_rubric", "load_calibration"):
        assert hasattr(rubric, name), f"rubric.{name} must exist"


class Ledger:
    def add(self, role, model, usage):
        pass


def response(verdict, box=None, rule_id="sem.focal-point"):
    item = {"rubric_id": rule_id, "verdict": verdict, "image": 1, "bbox": box, "evidence": "Visible evidence"}
    return fake_response(json.dumps({"items": [item], "anything_else": []}))


def finding(rule_id="sem.focal-point", *, tier="semantic", severity="warning", corroborated=True, role="title"):
    return Finding(
        id=rule_id, rule_id=rule_id, tier=tier, severity=severity, format="slides", section_id="s1", role=role,
        page=1, region=Box(x=10, y=10, w=20, h=20), message="Visible evidence", fingerprint=rule_id,
        remedy=Remedy(class_="restructure", hint="Make a focal point"), corroborated=corroborated,
    )


def run_critic(tmp_path, replies, engine_findings=()):
    interfaces()
    image_path = tmp_path / "page.png"
    Image.new("RGB", (100, 100), "white").save(image_path)
    images = [critic.CriticImage(png=image_path, page=1, width=100, height=100, label="page 1")]
    regions = [
        critic.Region(section_id="s1", role="title", page=1, box=Box(x=0, y=0, w=100, h=100)),
    ]
    items = rubric.load_rubric(neutral_theme()).items
    selected = [next(item for item in items if item.id == key) for key in ("sem.focal-point", "sem.reader-words")]
    transport = FakeTransport({"critic-model": replies})
    claude = Claude(transport, Ledger(), {"critic": "critic-model"})
    result = asyncio.run(critic.corroborate(claude, images, selected, list(engine_findings), regions, format="slides"))
    return result, transport.requests


def rubric_lines(request):
    content = request["messages"][0]["content"]
    text = next(block["text"] for block in content if block["type"] == "text" and "RUBRIC ITEMS" in block["text"])
    return [line.split(":", 1)[0] for line in text.splitlines() if line.startswith("- sem.")]


FIRST_BOX = {"x0": 100, "y0": 100, "x1": 300, "y1": 300}


def test_D1_second_opinion_reverses_rubric_order(tmp_path):
    findings, requests = run_critic(tmp_path, [response("fail", FIRST_BOX), response("pass")])
    assert len(findings) == 1
    assert findings[0].rule_id == "sem.focal-point"
    assert findings[0].corroborated is False
    assert len(requests) == 2
    assert rubric_lines(requests[0]) == ["- sem.focal-point", "- sem.reader-words"]
    assert rubric_lines(requests[1]) == ["- sem.reader-words", "- sem.focal-point"]


@pytest.mark.parametrize(
    ("second_box", "expected"),
    [({"x0": 200, "y0": 200, "x1": 400, "y1": 400}, True),
     ({"x0": 500, "y0": 500, "x1": 700, "y1": 700}, False),
     ({"x0": 300, "y0": 100, "x1": 400, "y1": 300}, False)],
)
def test_D2_second_failure_must_overlap(tmp_path, second_box, expected):
    findings, requests = run_critic(tmp_path, [response("fail", FIRST_BOX), response("fail", second_box)])
    assert len(findings) == 1
    assert findings[0].rule_id == "sem.focal-point"
    assert findings[0].corroborated is expected
    assert len(requests) == 2


def test_D2_no_failure_needs_no_second_call(tmp_path):
    findings, requests = run_critic(tmp_path, [response("pass")])
    assert findings == []
    assert len(requests) == 1


def test_D3_engine_agreement_avoids_second_call(tmp_path):
    engine = finding("geo.test", tier="geometry", role=None).model_copy(
        update={"region": Box(x=0, y=0, w=100, h=100)}
    )
    findings, requests = run_critic(tmp_path, [response("fail", FIRST_BOX)], [engine])
    assert len(findings) == 1
    assert findings[0].section_id == "s1" and findings[0].role == "title"
    assert findings[0].corroborated is True
    assert len(requests) == 1


def test_D4_calibration_and_neutral_theme(tmp_path):
    interfaces()
    neutral = neutral_theme()
    assert not (neutral.root / "rubric" / "calibration.yaml").exists()
    assert rubric.load_calibration(neutral) == {}
    root = tmp_path / "theme"
    shutil.copytree(neutral.root, root)
    path = root / "rubric" / "calibration.yaml"
    path.parent.mkdir(exist_ok=True)
    path.write_text("items:\n  sem.focal-point: {precision: 0.9}\n  sem.reader-words: {precision: 0.7}\n")
    theme = load_theme(root)
    calibration = rubric.load_calibration(theme)
    assert calibration == {"sem.focal-point": 0.9, "sem.reader-words": 0.7}
    original = [finding(), finding("sem.reader-words"), finding("sem.balance"),
                finding("geo.text-fits", tier="geometry", severity="error")]
    result = critic.calibrate(original, calibration)
    assert [f.severity for f in result] == ["warning", "info", "info", "error"]
    assert result[0].remedy.class_ == "restructure"
    assert result[3] == original[3]
    assert [f.severity for f in critic.calibrate(original, {})] == ["info", "info", "info", "error"]
    assert [f.severity for f in original] == ["warning", "warning", "warning", "error"]
    for invalid in ("items: {sem.balance: {precision: 0.9, weight: 1}}",
                    "items: {sem.balance: {precision: 1.5}}", "items: ["):
        path.write_text(invalid)
        with pytest.raises(ThemeError, match=r"^rubric/calibration\.yaml: "):
            rubric.load_calibration(theme)


def test_D5_uncorroborated_is_routed_to_report():
    interfaces()
    original = finding(corroborated=False)
    result = critic.calibrate([original], {"sem.focal-point": 0.9})
    assert len(result) == 1
    assert result[0].severity == "warning"
    assert result[0].remedy.class_ == "report"
    assert result[0].remedy.hint == "Make a focal point"
    plan = route(result, Section(id="s1", intent="statement"))
    assert plan.report == result
    assert plan.restructure == []
    enabled = critic.calibrate([original], {"sem.focal-point": 0.9}, act_on_uncorroborated=True)
    assert enabled[0].remedy.class_ == "restructure"
    assert enabled[0].severity == "warning"
    assert original.remedy.class_ == "restructure"
