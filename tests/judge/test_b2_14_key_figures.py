# Intent: key figures renders key numbers within its advertised slide capacity.
import importlib
import re
from pathlib import Path

import pytest
import yaml
from docla.model import Document, Item, Section


def optional(name):
    try:
        return importlib.import_module(name)
    except ImportError as error:
        if error.name == name or str(error.name).startswith(name + '.'):
            return None
        raise


components = optional('docla.render.components')
chooser = optional('docla.render.chooser')
swatch = optional('docla.render.swatch')
theme = optional('docla.theme')
serialiser = optional('docla.source.serialiser')
cli = optional('docla.cli')
ROOT = Path(__file__).resolve().parents[2]
FIXTURE = ROOT / 'tests/fixtures/components/key-figures.yaml'
SOURCE = ROOT / 'src/docla/render/library/key-figures.typ'


def manifests():
    assert components is not None and hasattr(components, 'all_manifests'), 'all_manifests must exist'
    return components.all_manifests()


def fixture():
    assert FIXTURE.is_file(), 'key-figures fixture must exist'
    section = Section.model_validate(yaml.safe_load(FIXTURE.read_text()))
    assert section.id and section.intent == 'key-numbers'
    return section


def render(section, tmp_path):
    assert swatch is not None and hasattr(swatch, 'swatch')
    assert theme is not None and hasattr(theme, 'neutral_theme')
    assert 'key-figures' in manifests()
    doc = Document(front={'title': 'Figures'}, format='slides', sections=[section])
    return swatch.swatch(doc, section.id, tmp_path, theme=theme.neutral_theme())


def test_D1_manifest_and_packaged_components():
    values = manifests()
    assert 'key-figures' in values
    manifest = values['key-figures']
    assert manifest.name == 'key-figures'
    assert manifest.format == 'slides'
    assert list(manifest.intents) == ['key-numbers']
    assert {key: tuple(value) for key, value in manifest.capacity.items()} == {
        'title_words': (1, 8), 'items': (3, 4), 'item_chars': (10, 60)
    }
    assert list(manifest.elements) == ['title', 'figure-value', 'figure-caption']
    assert manifest.label.strip()
    assert sorted(components.load_manifests()) == ['body', 'bullets', 'callout', 'statement']


@pytest.mark.parametrize('count,expected', [(0, 'bullets'), (2, 'bullets'), (3, 'key-figures'), (4, 'key-figures'), (5, 'bullets')])
def test_D2_key_numbers_routes(count, expected):
    assert chooser is not None and hasattr(chooser, 'load_chooser')
    routes = chooser.load_chooser(manifests=manifests())
    section = Section(id='figures', intent='key-numbers', items=[Item(body='A caption') for _ in range(count)])
    assert routes.choose(section, 'slides', 0, 1) == expected


def test_D2_pinned_routes():
    assert chooser is not None and hasattr(chooser, 'load_chooser')
    routes = chooser.load_chooser(manifests=manifests())
    for fmt, intent, count, expected in [
        ('slides', 'statement', 0, 'statement'), ('slides', 'bullets', 3, 'bullets'),
        ('doc', 'body', 0, 'body'), ('doc', 'callout', 1, 'callout'),
    ]:
        section = Section(id='s', intent=intent, title='Title', items=[Item(body='A point') for _ in range(count)])
        assert routes.choose(section, fmt, 0, 1) == expected


def test_D3_fixture_page_and_marks(tmp_path):
    section = fixture()
    result = render(section, tmp_path)
    assert [(page.width, page.height) for page in result.facts.pages] == [(960, 540)]
    marks = result.facts.marks
    assert [(m.id, m.edge) for m in marks if m.kind == 'section'] == [(section.id, 'start'), (section.id, 'end')]
    roles = {m.role for m in marks if m.kind == 'element' and m.id == section.id}
    assert {'title', 'figure-value', 'figure-caption'} <= roles


def test_D4_caption_capacity_boundary(tmp_path):
    def fits(length, folder):
        section = Section(id='figures', intent='key-numbers', title='Key figures', items=[
            Item(head='123456', body='x' * length) for _ in range(4)
        ])
        return [m for m in render(section, folder).facts.marks if m.kind == 'fit']
    within = fits(60, tmp_path / 'within')
    assert within and all(mark.ok for mark in within)
    overflow = fits(61, tmp_path / 'over')
    assert overflow and any(not mark.ok for mark in overflow)


def test_D5_fixture_deck_checks_clean(tmp_path, capsys):
    section = fixture()
    assert serialiser is not None and hasattr(serialiser, 'serialise')
    assert cli is not None and hasattr(cli, 'main')
    doc = Document(front={'doctype': 'pitch-deck', 'title': 'Figures'}, format='slides', sections=[section])
    source = tmp_path / 'deck.md'
    source.write_text(serialiser.serialise(doc))
    assert 'key-figures' in manifests()
    try:
        code = cli.main(['check', str(source), '--out', str(tmp_path / 'out')])
    except SystemExit as error:
        code = error.code
    output = capsys.readouterr()
    assert code == 0, output.err
    assert output.out.splitlines() == ['no findings']


def test_D6_no_colour_literals():
    assert SOURCE.is_file(), 'key-figures.typ must exist'
    text = SOURCE.read_text()
    assert not re.search(r'\b(?:rgb|luma|cmyk)\s*\(|#[0-9a-fA-F]{6}\b', text)
