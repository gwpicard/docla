# Intent: judge rendered pages against a closed visual rubric with anchored findings.
import asyncio
import base64
import hashlib
import importlib
import importlib.util
import io
import json

import pytest
from PIL import Image

from docla.agents import prompts
from docla.agents.client import Claude
from docla.checks.engine import fingerprint
from docla.facts.layout import LayoutFacts
from docla.model import Box, Finding, Remedy
from docla.render.marks import ElementMark
from docla.testing.fakes import FakeTransport, fake_response
from docla.theme import neutral_theme


def optional(name):
    try:
        return importlib.import_module(name)
    except ImportError as error:
        missing = error.name or ""
        if (missing == name or name.startswith(missing + ".")) and importlib.util.find_spec(missing) is None:
            return None
        raise


critic = optional("docla.agents.critic")
rubric = optional("docla.theme.rubric")


def require():
    assert critic is not None, "docla.agents.critic must exist"
    for name in (
        "BBox",
        "CriticItem",
        "CriticReport",
        "CriticImage",
        "Region",
        "regions_from_facts",
        "critic_blocks",
        "critique",
    ):
        assert hasattr(critic, name), f"critic.{name} must exist"
    assert rubric is not None and hasattr(rubric, "load_rubric"), "rubric.load_rubric must exist"


class Ledger:
    def add(self, role, model, usage):
        pass


def setup(tmp_path, items, size=(960, 540)):
    require()
    path = tmp_path / "page.png"
    Image.new("RGB", size, "white").save(path)
    image = critic.CriticImage(png=path, page=1, width=960, height=540, label="page 1")
    regions = [
        critic.Region(section_id="s1", role="title", page=1, box=Box(x=40, y=40, w=880, h=80)),
        critic.Region(section_id="s1", role="body", page=1, box=Box(x=40, y=140, w=880, h=360)),
        critic.Region(section_id="s1", role=None, page=1, box=Box(x=40, y=40, w=880, h=460)),
    ]
    transport = FakeTransport({"critic-model": [fake_response(json.dumps({"items": items, "anything_else": []}))]})
    claude = Claude(transport, Ledger(), {"critic": "critic-model"})
    rubrics = rubric.load_rubric(neutral_theme())
    return image, regions, transport, claude, [rubrics.get("sem.focal-point"), rubrics.get("sem.reader-words")]


def item(rid, verdict, bbox, evidence="Evidence", image=1):
    return {"rubric_id": rid, "verdict": verdict, "image": image, "bbox": bbox, "evidence": evidence}


def box(x0, y0, x1, y1):
    return dict(x0=x0, y0=y0, x1=x1, y1=y1)


def run(claude, images, rubrics, regions, findings=()):
    return asyncio.run(critic.critique(claude, images, rubrics, list(findings), regions, format="slides"))


def test_D1_closed_vocabulary_and_anything_else(tmp_path):
    data = [
        item("sem.made-up", "fail", box(100, 100, 500, 200)),
        item("sem.focal-point", "fail", box(100, 100, 500, 200), "First"),
        item("sem.focal-point", "pass", None),
        item("sem.reader-words", "unsure", None),
    ]
    image, regions, transport, claude, rubrics = setup(tmp_path, data)
    transport.responses["critic-model"] = [
        fake_response(
            json.dumps(
                {"items": data, "anything_else": [item("sem.reader-words", "fail", box(100, 400, 500, 500), "Second")]}
            )
        )
    ]
    findings = run(claude, [image], rubrics, regions)
    assert [f.rule_id for f in findings] == ["sem.focal-point", "sem.reader-words"]
    assert [f.message for f in findings] == ["First", "Second"]
    assert [f.remedy.class_ for f in findings] == ["restructure", "redraft"]
    assert all(f.tier == "semantic" and f.corroborated is False for f in findings)
    assert len(transport.requests) == 1


def test_D2_anchor_and_downgrade(tmp_path):
    image, regions, transport, claude, rubrics = setup(
        tmp_path, [item("sem.focal-point", "fail", box(100, 100, 500, 200))]
    )
    (finding,) = run(claude, [image], rubrics, regions)
    assert (finding.section_id, finding.role, finding.page, finding.severity) == ("s1", "title", 1, "warning")
    assert finding.region == Box(x=96, y=54, w=384, h=54)
    assert finding.measured == {"image": 1, "bbox": [100, 100, 500, 200]}
    expected = fingerprint("sem.focal-point", "s1", "title", finding.region, (960, 540))
    assert finding.fingerprint == expected
    assert finding.id == hashlib.sha1(f"sem.focal-point|s1|{expected}".encode()).hexdigest()[:12]
    for bad in (box(980, 960, 1000, 1000), None, box(500, 500, 400, 600)):
        transport.responses["critic-model"] = [
            fake_response(json.dumps({"items": [item("sem.focal-point", "fail", bad)]}))
        ]
        (result,) = run(claude, [image], rubrics, regions)
        assert (result.severity, result.section_id, result.role) == ("info", None, None)


def test_D3_no_repeats(tmp_path):
    title = item("sem.focal-point", "fail", box(100, 100, 500, 200), "Title")
    body = item("sem.focal-point", "fail", box(100, 400, 500, 500), "Body")
    image, regions, transport, claude, rubrics = setup(tmp_path, [title, body, body])
    engine = Finding(
        id="engine",
        rule_id="geo.text-fits",
        tier="geometry",
        severity="warning",
        format="slides",
        section_id="s1",
        role="title",
        page=1,
        region=Box(x=280, y=75, w=16, h=12),
        message="Overflow",
        fingerprint="engine",
        remedy=Remedy(class_="tune", hint="Fix"),
    )
    findings = run(claude, [image], rubrics, regions, [engine])
    assert [(f.role, f.message) for f in findings] == [("body", "Body")]
    assert len(transport.requests) == 1


def test_D4_request_and_empty_inputs(tmp_path):
    image, regions, transport, claude, rubrics = setup(tmp_path, [], (1920, 1080))
    engine = Finding(
        id="engine",
        rule_id="geo.text-fits",
        tier="geometry",
        severity="warning",
        format="slides",
        section_id="s1",
        role="title",
        page=1,
        region=Box(x=280, y=75, w=16, h=12),
        message="Overflow",
        fingerprint="engine",
        remedy=Remedy(class_="tune", hint="Fix"),
    )
    transport.responses["critic-model"].append(fake_response('{"items": []}'))
    assert run(claude, [image], rubrics, regions, [engine]) == []
    assert run(claude, [image], rubrics, regions, [engine]) == []
    first, second = transport.requests
    assert first == second
    assert first["model"] == "critic-model"
    assert first["system"] == critic.critic_blocks()
    assert len(first["system"]) == 2
    assert first["system"][0]["text"] == prompts.system_blocks("gatherer")[0]["text"]
    assert "cache_control" not in first["system"][0]
    assert first["system"][1]["cache_control"] == {"type": "ephemeral"}
    assert first["output_config"]["format"]["type"] == "json_schema"
    assert first["output_config"]["effort"] == "medium"
    content = first["messages"][0]["content"]
    text = "\n".join(block["text"] for block in content if block["type"] == "text")
    assert "Image 1 = page 1" in text
    for entry in rubrics:
        assert entry.id in text and entry.question in text
    assert "geo.text-fits" in text and "Overflow" in text
    assert "image 1 s1 title 42 74 958 222" in text
    blocks = [block for block in content if block["type"] == "image"]
    assert len(blocks) == 1
    with Image.open(io.BytesIO(base64.b64decode(blocks[0]["source"]["data"]))) as sent:
        assert max(sent.size) <= 1568
    small, _, small_transport, small_claude, _ = setup(tmp_path, [], (800, 450))
    assert run(small_claude, [small], rubrics, regions) == []
    block = next(b for b in small_transport.requests[0]["messages"][0]["content"] if b["type"] == "image")
    with Image.open(io.BytesIO(base64.b64decode(block["source"]["data"]))) as sent:
        assert sent.size == (800, 450)
    assert run(small_claude, [small], [], regions) == []
    assert run(small_claude, [], rubrics, regions) == []
    assert len(small_transport.requests) == 1


def test_D5_regions_from_facts():
    require()
    marks = [
        ElementMark(kind="element", id="s1", role="title", page=1, x=40, y=40, w=880, h=80),
        ElementMark(kind="element", id="s1", role="body", page=1, x=40, y=140, w=880, h=360),
    ]
    facts = LayoutFacts(pdf_sha256="abc", pages=[], words=[], shapes=[], marks=marks)
    regions = critic.regions_from_facts(facts)
    assert [(r.section_id, r.role, r.page, r.box) for r in regions] == [
        ("s1", "title", 1, Box(x=40, y=40, w=880, h=80)),
        ("s1", "body", 1, Box(x=40, y=140, w=880, h=360)),
        ("s1", None, 1, Box(x=40, y=40, w=880, h=460)),
    ]


def test_D6_existing_prompt_roles_stay_closed():
    assert prompts.ROLES[:4] == ("gatherer", "planner", "writer.draft", "writer.repair")
    assert "critic" not in prompts.ROLES
    with pytest.raises(ValueError, match="critic"):
        prompts.system_blocks("critic", neutral_theme())
