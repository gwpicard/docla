# Intent: closing sections route to a capacity-accurate, marked slide component.
import importlib
import re
from pathlib import Path

import yaml


def _optional(name):
    try:
        return importlib.import_module(name)
    except ImportError as error:
        if error.name != name and not str(error.name).startswith(name + "."):
            raise
        return None


components = _optional("docla.render.components")
chooser_module = _optional("docla.render.chooser")
model = _optional("docla.model")
swatch_module = _optional("docla.render.swatch")
theme = _optional("docla.theme")
marks = _optional("docla.render.marks")
serialiser = _optional("docla.source.serialiser")
cli = _optional("docla.cli")
ROOT = Path(__file__).resolve().parents[2]


def _manifests():
    assert components is not None and hasattr(components, "all_manifests"), "all_manifests must exist"
    return components.all_manifests()


def _fixture():
    assert model is not None and hasattr(model, "Section"), "Section must exist"
    path = ROOT / "tests/fixtures/components/closing.yaml"
    assert path.is_file(), "closing fixture must exist"
    section = model.Section.model_validate(yaml.safe_load(path.read_text()))
    assert section.id and section.intent == "closing"
    return section


def _document(section):
    return model.Document(
        front={"doctype": "pitch-deck", "format": "slides", "title": "Closing"}, format="slides", sections=[section]
    )


def _render(section, tmp_path):
    _manifests()
    assert swatch_module is not None and hasattr(swatch_module, "swatch"), "swatch must exist"
    assert theme is not None and hasattr(theme, "neutral_theme"), "neutral_theme must exist"
    assert marks is not None and hasattr(marks, "FitMark"), "mark types must exist"
    return swatch_module.swatch(_document(section), section.id, tmp_path, theme=theme.neutral_theme())


def test_D1_closing_manifest_and_packaged_components():
    manifests = _manifests()
    assert "closing" in manifests
    manifest = manifests["closing"]
    assert manifest.name == "closing"
    assert manifest.format == "slides"
    assert list(manifest.intents) == ["closing"]
    assert {k: tuple(v) for k, v in manifest.capacity.items()} == {"title_words": (1, 10), "paragraphs": (0, 1)}
    assert list(manifest.elements) == ["title", "spoken"]
    assert manifest.label.strip()
    assert sorted(components.load_manifests()) == ["body", "bullets", "callout", "statement"]


def test_D2_closing_and_pinned_routes():
    manifests = _manifests()
    assert chooser_module is not None and hasattr(chooser_module, "load_chooser")
    assert model is not None and hasattr(model, "Section") and hasattr(model, "Item")
    chooser = chooser_module.load_chooser(manifests=manifests)
    cases = [
        ("slides", model.Section(id="a", intent="closing", title="Thank you"), "closing"),
        ("slides", model.Section(id="b", intent="statement", title="Claim"), "statement"),
        (
            "slides",
            model.Section(id="c", intent="bullets", items=[model.Item(body="A point") for _ in range(3)]),
            "bullets",
        ),
        ("doc", model.Section(id="d", intent="body", title="Title", paragraphs=["Text"]), "body"),
        ("doc", model.Section(id="e", intent="callout", title="Title", items=[model.Item(body="A point")]), "callout"),
    ]
    for fmt, section, expected in cases:
        assert chooser.choose(section, fmt, 0, 1) == expected


def test_D3_fixture_page_and_marks(tmp_path):
    section = _fixture()
    assert section.title and section.paragraphs, "fixture must fill both roles"
    facts = _render(section, tmp_path).facts
    assert [(p.width, p.height) for p in facts.pages] == [(960, 540)]
    sections = [m for m in facts.marks if isinstance(m, marks.SectionMark)]
    assert [(m.id, m.edge) for m in sections] == [(section.id, "start"), (section.id, "end")]
    elements = [m for m in facts.marks if isinstance(m, marks.ElementMark)]
    assert {m.role for m in elements if m.id == section.id} >= {"title", "spoken"}


def test_D4_title_capacity_boundary(tmp_path):
    section = _fixture()
    for count, expected in [(10, True), (11, False)]:
        title = " ".join(["closing"] * count)
        result = _render(section.model_copy(update={"title": title}), tmp_path / str(count))
        fits = [m for m in result.facts.marks if isinstance(m, marks.FitMark)]
        assert fits, "closing must report fit marks"
        assert all(m.ok for m in fits) is expected


def test_D5_check_fixture_deck(tmp_path, capsys):
    section = _fixture()
    assert serialiser is not None and hasattr(serialiser, "serialise")
    assert cli is not None and hasattr(cli, "main")
    source = tmp_path / "deck.md"
    source.write_text(serialiser.serialise(_document(section)))
    try:
        code = cli.main(["check", str(source), "--out", str(tmp_path / "out")])
    except SystemExit as error:
        code = error.code
    captured = capsys.readouterr()
    assert code == 0, captured.err
    assert captured.out.strip() == "no findings"


def test_D6_no_colour_literals():
    path = ROOT / "src/docla/render/library/closing.typ"
    assert path.is_file(), "closing.typ must exist"
    text = path.read_text()
    assert not re.search(r"\b(?:rgb|luma|cmyk)\s*\(|#[0-9a-fA-F]{6}\b", text)
