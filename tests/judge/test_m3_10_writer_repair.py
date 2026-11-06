# Intent: Writer repair turns measured findings into a section-local set_fields patch.
import asyncio
import importlib
import importlib.util
import json

import pytest

from docla import model
from docla.source import patches
from docla.theme import neutral_theme


def optional(name):
    try:
        return importlib.import_module(name)
    except ImportError as error:
        missing = error.name
        if not missing or not (missing == name or name.startswith(missing + ".") or missing.startswith(name + ".")):
            raise
        try:
            spec = importlib.util.find_spec(missing)
        except ModuleNotFoundError as parent:
            if not missing.startswith(str(parent.name) + "."):
                raise
            spec = None
        if spec is not None:
            raise
        return None


writer = optional("docla.agents.writer")
client = optional("docla.agents.client")
fakes = optional("docla.testing.fakes")
prompts = optional("docla.agents.prompts")


def interfaces():
    for module, names in (
        (writer, ("repair", "RepairOp", "RepairReply")),
        (client, ("Claude", "image_block")),
        (fakes, ("FakeTransport", "fake_response")),
        (prompts, ("system_blocks",)),
    ):
        assert module is not None, f"module providing {names[0]} must exist"
        for name in names:
            assert hasattr(module, name), f"{name} must exist"


class Ledger:
    def add(self, role, model, usage):
        pass


def section():
    return model.Section(
        id="c4e10",
        intent="bullets",
        title="A title with a fact",
        items=[
            model.Item(body="First original item"),
            model.Item(body="Second original item"),
            model.Item(body="Third original item"),
        ],
    )


def finding():
    return model.Finding(
        id="finding-1",
        rule_id="geo.text-fits",
        tier="geometry",
        severity="error",
        format="slides",
        section_id="c4e10",
        role="body",
        message="The body overflows the frame.",
        fingerprint="fingerprint-1",
        remedy=model.Remedy(class_="redraft", hint="cut the items that wrap until the frame fits"),
        measured={
            "need": 420.0,
            "have": 380.0,
            "over": 40.0,
            "items": [
                {"n": 0, "lines": 1, "cut_to_save_line": None},
                {"n": 1, "lines": 3, "cut_to_save_line": 27},
                {"n": 2, "lines": 2, "cut_to_save_line": 12},
            ],
        },
    )


def reply(ops=None):
    if ops is None:
        ops = [
            {
                "op": "set_fields",
                "section_id": "c4e10",
                "items": [
                    {"body": "First revised"},
                    {"body": "Second revised"},
                    {"body": "Third revised"},
                ],
            }
        ]
    return {"reason": "shortened items 1 and 2", "ops": ops}


def run_repair(response=None, *, history=None, images=None, base_rev=0):
    interfaces()
    transport = fakes.FakeTransport({"claude-sonnet-5-5": [fakes.fake_response(json.dumps(response or reply()))]})
    claude = client.Claude(transport, Ledger(), {"writer.repair": "claude-sonnet-5-5"})
    result = asyncio.run(
        writer.repair(
            claude,
            section(),
            [finding()],
            history or [],
            "BRIEF X",
            images=images,
            base_rev=base_rev,
        )
    )
    assert len(transport.requests) == 1
    return result, transport.requests[0]


def prompt(request):
    return request["messages"][0]["content"][-1]["text"]


def test_D1_measured_findings_and_system():
    _, request = run_repair()
    assert request["model"] == "claude-sonnet-5-5"
    assert request["system"] == prompts.system_blocks("writer.repair", neutral_theme(), "BRIEF X")
    text = prompt(request)
    for value in (
        "geo.text-fits",
        "The body overflows the frame.",
        "cut the items that wrap until the frame fits",
        "items[1]: 3 line(s); cutting about 27 characters brings it to 2 line(s)",
        "items[2]: 2 line(s); cutting about 12 characters brings it to 1 line(s)",
    ):
        assert value in text
    line = next(line for line in text.splitlines() if "items[0]: 1 line(s)" in line)
    assert "cutting about" not in line


def test_D2_section_and_attempt_history():
    _, request = run_repair()
    text = prompt(request)
    for value in (
        "A title with a fact",
        "First original item",
        "Second original item",
        "Third original item",
        "EARLIER ATTEMPTS: none",
        "A fact a title cannot hold may move into an item; do not drop it.",
        "Return a set_fields patch only.",
    ):
        assert value in text
    history = [
        "attempt 1: shortened title; geo.text-fits persisted at items[1]",
        "attempt 2: rejected by the fact guard",
    ]
    _, request = run_repair(history=history)
    text = prompt(request)
    assert history[0] in text and history[1] in text
    assert text.index(history[0]) < text.index(history[1])


@pytest.mark.parametrize("base_rev", [0, 5])
def test_D3_patch_and_apply(base_rev):
    patch, _ = run_repair(base_rev=base_rev)
    assert isinstance(patch, model.Patch)
    assert (patch.author, patch.base_rev, patch.reason, patch.finding_ids) == (
        "ai",
        base_rev,
        "shortened items 1 and 2",
        ["finding-1"],
    )
    assert len(patch.ops) == 1
    op = patch.ops[0]
    assert (op.op, op.section_id) == ("set_fields", "c4e10")
    assert op.fields == {
        "items": [
            {"head": None, "body": "First revised", "sub": [], "citations": []},
            {"head": None, "body": "Second revised", "sub": [], "citations": []},
            {"head": None, "body": "Third revised", "sub": [], "citations": []},
        ]
    }
    doc = model.Document(front={"doctype": "pitch-deck"}, format="slides", sections=[section()], rev=base_rev)
    result = patches.apply_patch(doc, patch)
    assert [item.body for item in result.sections[0].items] == ["First revised", "Second revised", "Third revised"]


@pytest.mark.parametrize(
    ("ops", "code", "message"),
    [
        ([{"op": "delete_section", "section_id": "c4e10"}], "repair-op", "delete_section"),
        ([{"op": "replace_section", "section_id": "c4e10"}], "repair-op", "replace_section"),
        ([{"op": "set_fields", "section_id": "other", "title": "New"}], "repair-op", "other"),
        ([], "repair-empty", None),
        ([{"op": "set_fields", "section_id": "c4e10"}], "repair-empty", None),
    ],
)
def test_D4_reject_invalid_ops(ops, code, message):
    with pytest.raises(patches.PatchRejected) as exc:
        run_repair(reply(ops))
    assert exc.value.code == code
    if message is not None:
        assert message in str(exc.value)


def test_D5_images_precede_prompt(tmp_path):
    first, second = tmp_path / "first.png", tmp_path / "second.png"
    first.write_bytes(b"\x89PNG\r\n\x1a\nfirst")
    second.write_bytes(b"\x89PNG\r\n\x1a\nsecond")
    _, request = run_repair(images=[first, second])
    blocks = request["messages"][0]["content"]
    assert len(blocks) == 5
    assert blocks[0]["type"] == "text" and blocks[0]["text"].startswith("Image 1:")
    assert blocks[1] == client.image_block(first)
    assert blocks[2]["type"] == "text" and blocks[2]["text"].startswith("Image 2:")
    assert blocks[3] == client.image_block(second)
    assert blocks[4]["type"] == "text" and "geo.text-fits" in blocks[4]["text"]
    _, request = run_repair()
    blocks = request["messages"][0]["content"]
    assert len(blocks) == 1 and blocks[0]["type"] == "text" and "geo.text-fits" in blocks[0]["text"]
