# Intent: Synthesise a labelled, renderable brand theme from settled values and checked fonts.
import importlib
import importlib.util
import json
import shutil

import pytest
import yaml

from docla import cli
from docla.brand.git import run_git
from docla.brand.workspace import BrandError, init_brand
from docla.theme import load_theme, neutral_theme


def _module(name):
    try:
        return importlib.import_module(name)
    except ImportError as error:
        if error.name != name and not name.startswith(f"{error.name}."):
            raise
        if importlib.util.find_spec(name) is not None:
            raise
        return None


synth = _module("docla.brand.synth_tokens")
labels = _module("docla.theme.labels")
questions = _module("docla.brand.questions")


def _interface():
    assert synth is not None and hasattr(synth, "synthesise_tokens"), "synthesise_tokens must exist"
    assert labels is not None and hasattr(labels, "token_label"), "token_label must exist"
    assert questions is not None and hasattr(questions, "load_questions"), "load_questions must exist"


def _settled(path, value, status="single", origin="template", page=None):
    role = {"template": "templates", "guidelines": "guidelines", "examples": "examples"}[origin]
    source = {"file": "materials/templates/deck.pptx", "role": role}
    if origin == "guidelines":
        source = {"file": "materials/guidelines/book.pdf", "role": role, "page": page}
    elif origin == "examples":
        source = {"files": ["materials/examples/deck.pdf"], "role": role, "note": "measured over 4 pages"}
    return {
        "path": path,
        "format": "slides" if ".slides." in path else "doc" if ".doc." in path else None,
        "status": status,
        "value": value,
        "provenance": {"label": "measured", "source": source},
        "candidates": [{"value": value, "origin": origin, "source": source}],
    }


def _write_reconciliation(brand, values):
    path = brand / "theme/ingest/reconcile.json"
    path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "values": sorted(values, key=lambda v: v["path"]),
                "proposed_rules": [],
                "questions": [],
            }
        )
        + "\n"
    )


def _brand(tmp_path):
    brand = init_brand("acme", tmp_path / ".brand")
    fonts = brand / "theme/fonts"
    neutral_fonts = neutral_theme().fonts_dir
    names = ["Inter-Regular.ttf", "Inter-SemiBold.ttf", "SourceSerif4-Regular.ttf"]
    for name in names:
        shutil.copyfile(neutral_fonts / name, fonts / name)
    (fonts / "LICENSES.txt").write_text("\n\n".join(f"file: {name}" for name in names) + "\n")
    ingest = brand / "theme/ingest"
    ingest.mkdir(exist_ok=True)
    (ingest / "fonts.json").write_text(
        json.dumps({"files": [], "typefaces": {"Inter": names[:2], "Source Serif 4": names[2:]}, "questions": []})
        + "\n"
    )
    values = [
        _settled("colour.roles.accent", "#0B5FFF", "agreed", "guidelines", 4),
        _settled("colour.roles.ink", "#101820"),
        _settled("colour.roles.surface", "#FFFFFF"),
        _settled("type.families.text.name", "Inter", origin="guidelines", page=7),
        _settled("type.families.display.name", "Source Serif 4", origin="guidelines", page=7),
        _settled("type.scale.slides.body.size", 20, "proposed", "examples"),
        _settled("type.scale.slides.title.size", 36, "agreed"),
        _settled("type.scale.doc.body.size", 11, "conflict"),
    ]
    for path, value in {
        "pages.slides.width": 960,
        "pages.slides.height": 540,
        "pages.slides.margin.top": 48,
        "pages.slides.margin.right": 48,
        "pages.slides.margin.bottom": 40,
        "pages.slides.margin.left": 48,
        "pages.doc.width": 595.28,
        "pages.doc.height": 841.89,
        "pages.doc.margin.top": 56.69,
        "pages.doc.margin.right": 70.87,
        "pages.doc.margin.left": 70.87,
    }.items():
        values.append(_settled(path, value, "agreed"))
    _write_reconciliation(brand, values)
    run_git(brand, "add", "-A")
    run_git(brand, "commit", "-m", "Add settled inputs")
    return brand, values


def test_D1_renderable_theme_and_settled_values(tmp_path):
    _interface()
    brand, _ = _brand(tmp_path)
    synth.synthesise_tokens(brand)
    theme = load_theme(brand / "theme")
    neutral = neutral_theme()
    assert theme.info.labelled is True
    assert theme.info.formats == ["slides", "doc"]
    roles = theme.tokens.colour.roles
    assert set(roles) == set(neutral.tokens.colour.roles)
    assert {k: roles[k] for k in ("accent", "ink", "surface", "dark", "on-dark", "muted")} == {
        "accent": "#0B5FFF",
        "ink": "#101820",
        "surface": "#FFFFFF",
        "dark": "#101820",
        "on-dark": "#FFFFFF",
        "muted": "#707479",
    }
    families = theme.tokens.type.families
    assert (families["text"].name, families["text"].files) == ("Inter", ["Inter-Regular.ttf", "Inter-SemiBold.ttf"])
    assert (families["display"].name, families["display"].files) == ("Source Serif 4", ["SourceSerif4-Regular.ttf"])
    scales = theme.tokens.type.scale
    for fmt in ("slides", "doc"):
        assert set(scales[fmt].roles) == set(neutral.tokens.type.scale[fmt].roles)
    assert [scales["slides"].roles[x].size for x in ("body", "title", "caption")] == [20, 36, 18]
    assert [scales["doc"].roles[x].size for x in ("body", "h2", "caption")] == [11, 13, 9]
    page = theme.tokens.pages["slides"]
    assert (page.width, page.height, page.margin.left) == (960, 540, 48)


def test_D2_labels_and_inferred_values(tmp_path):
    _interface()
    brand, _ = _brand(tmp_path)
    result = synth.synthesise_tokens(brand)
    theme = load_theme(brand / "theme")

    def label(path):
        return labels.token_label(theme, path)

    assert label("colour.roles.accent").label == "measured"
    assert label("colour.roles.accent").source.page == 4
    assert label("colour.roles.muted").label == "derived"
    assert "colour.roles.ink" in label("colour.roles.muted").source.from_
    assert label("type.scale.doc.caption.size").label == "derived"
    assert label("type.scale.doc.caption.size").source.from_ == ["type.scale.doc.body.size"]
    assert label("type.families.text.files").label == "measured"
    assert label("type.families.text.files").source.role == "fonts"
    for path in ("colour.usage.text", "spacing.unit", "colour.contrast_min", "pages.doc.margin.bottom"):
        entry = label(path)
        assert entry.label == "inferred" and entry.source.note.strip()
    assert theme.tokens.pages["doc"].margin.bottom == pytest.approx(56.69, abs=0.01)
    assert "pages.doc.margin.bottom" in result.inferred


def test_D3_blocking_question_closes_when_settled(tmp_path):
    _interface()
    brand, values = _brand(tmp_path)
    synth.synthesise_tokens(brand)
    stored = questions.load_questions(brand)
    question = next(q for q in stored if q.id == "token.pages.doc.margin.bottom")
    assert (question.kind, question.format, question.blocking, question.recommended) == ("token", "doc", True, "a")
    option = next(o for o in question.options if o.id == "a")
    assert len(option.effects) == 1
    assert (option.effects[0].kind, option.effects[0].path) == ("set-token", "pages.doc.margin.bottom")
    assert float(option.effects[0].value) == pytest.approx(56.69, abs=0.01)
    assert not {"token." + v["path"] for v in values} & {q.id for q in stored}
    values.append(_settled("pages.doc.margin.bottom", 56.69))
    _write_reconciliation(brand, values)
    synth.synthesise_tokens(brand)
    assert "token.pages.doc.margin.bottom" not in {q.id for q in questions.load_questions(brand) if q.answer is None}
    assert labels.token_label(load_theme(brand / "theme"), "pages.doc.margin.bottom").label == "measured"


def test_D4_answer_preserved_and_repeatable(tmp_path):
    _interface()
    brand, _ = _brand(tmp_path)
    synth.synthesise_tokens(brand)
    token_file = brand / "theme/tokens.yaml"
    provenance_file = brand / "theme/provenance.yaml"
    tokens = yaml.safe_load(token_file.read_text())
    provenance = yaml.safe_load(provenance_file.read_text())
    tokens["colour"]["roles"]["accent"] = "#0000FF"
    provenance["tokens"]["colour.roles.accent"] = {"label": "answered", "source": {"question": "q-1"}}
    token_file.write_text(yaml.safe_dump(tokens, sort_keys=False))
    provenance_file.write_text(yaml.safe_dump(provenance, sort_keys=False))
    synth.synthesise_tokens(brand)
    theme = load_theme(brand / "theme")
    assert theme.tokens.colour.roles["accent"] == "#0000FF"
    assert labels.token_label(theme, "colour.roles.accent").label == "answered"
    assert labels.token_label(theme, "colour.roles.accent").source.question == "q-1"
    paths = [token_file, provenance_file, brand / "theme/theme.yaml"]
    before = [path.read_bytes() for path in paths]
    synth.synthesise_tokens(brand)
    assert [path.read_bytes() for path in paths] == before


def test_D5_refusals_and_cli_change(tmp_path, capsys):
    _interface()
    brand, values = _brand(tmp_path)
    without_text = [v for v in values if v["path"] != "type.families.text.name"]
    _write_reconciliation(brand, without_text)
    with pytest.raises(BrandError, match="(?i)text.*typeface|typeface.*text"):
        synth.synthesise_tokens(brand)
    assert not (brand / "theme/tokens.yaml").exists()
    missing = without_text + [_settled("type.families.text.name", "Acme Sans")]
    _write_reconciliation(brand, missing)
    with pytest.raises(BrandError, match="font\\.missing\\.acme-sans"):
        synth.synthesise_tokens(brand)
    assert not (brand / "theme/tokens.yaml").exists()
    assert "font.missing.acme-sans" in {q.id for q in questions.load_questions(brand)}
    run_git(brand, "add", "-A")
    run_git(brand, "commit", "-m", "Set missing font input")
    head = run_git(brand, "rev-parse", "HEAD")
    assert cli.main(["brand", "synthesise", "acme", "--root", str(brand.parent)]) == 2
    assert run_git(brand, "rev-parse", "HEAD") == head
    assert run_git(brand, "branch", "--show-current").strip() == "main"
    _write_reconciliation(brand, values)
    run_git(brand, "add", "-A")
    run_git(brand, "commit", "-m", "Restore settled input")
    assert cli.main(["brand", "synthesise", "acme", "--root", str(brand.parent)]) == 0
    assert run_git(brand, "branch", "--show-current").strip() == "main"
    assert run_git(brand, "status", "--porcelain") == ""
    assert "Synthesise the brand theme" in run_git(brand, "log", "-p", "--all")
    assert "open questions" in capsys.readouterr().out
