"""Shared component fixture and catalogue checks."""

import json
from pathlib import Path

import pytest

from docla.doctypes import load_doctypes
from docla.render.components import all_manifests
from docla.render.compose import default_chooser
from docla.testing.golden import compare_facts, facts_for

FIXTURES = Path(__file__).parent / "fixtures" / "components"


@pytest.mark.parametrize("manifest", [m for m in all_manifests().values() if m.fixture], ids=lambda m: m.name)
def test_component_fixture(manifest):
    name = Path(manifest.fixture).stem
    actual = facts_for(name, FIXTURES)
    golden = FIXTURES / f"{name}.facts.json"
    if golden.exists():
        assert not compare_facts(actual, json.loads(golden.read_text(encoding="utf-8")))


def test_chooser_components():
    chooser = default_chooser()
    manifests = all_manifests()
    for entries in chooser.entries.values():
        for entry in entries:
            if entry.component is not None:
                assert entry.component in manifests
                assert manifests[entry.component].label.strip()


def _check_outline(entries, fmt, chooser):
    for entry in entries:
        if entry.intent not in (None, "any"):
            assert chooser.knows(entry.intent, fmt), entry.intent
        _check_outline(entry.children, fmt, chooser)


def test_doctype_intents():
    chooser = default_chooser()
    for doctype in load_doctypes().values():
        _check_outline(doctype.outline, doctype.format, chooser)
