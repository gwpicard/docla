# Intent: Summarise completed sections using only supported facts, with one retry.
import asyncio
import importlib
import importlib.util
import json

import pytest

from docla.agents import prompts
from docla.agents.client import Claude
from docla.agents.writer import SectionDraft, SectionJob
from docla.config import ProjectConfig, load_project_config
from docla.doctypes import load_doctype
from docla.model import Citation, Document, Item, Section
from docla.render.components import all_manifests
from docla.source.patches import PatchRejected
from docla.testing.fakes import FakeTransport, fake_response
from docla.theme import neutral_theme
from docla.write import role_models

try:
    summariser = importlib.import_module('docla.agents.summariser')
except ImportError as error:
    if error.name != 'docla.agents.summariser' or importlib.util.find_spec(error.name) is not None:
        raise
    summariser = None


def require(name):
    assert summariser is not None, 'docla.agents.summariser must exist'
    assert hasattr(summariser, name), f'docla.agents.summariser.{name} must exist'
    return getattr(summariser, name)


class Ledger:
    def add(self, role, model, usage):
        pass


def sections():
    return [
        Section(id='a', intent='bullets', section='opener', title='Context',
                items=[Item(head='Growth', body='Revenue rose 12%', citations=[Citation(key='S1')])]),
        Section(id='b', intent='bullets', section='content', title='Delivery',
                paragraphs=['The pilot has 3 teams.']),
        Section(id='c', intent='bullets', section='ask', title='Decision', paragraphs=['Approve the pilot.']),
    ]


def job():
    return SectionJob(section_id='summary', format='slides', intent='bullets', component='bullets',
                      outline='Summarise the plan', section='agenda')


def reply(body):
    return {'title': 'Context', 'items': [{'head': 'Growth', 'body': body, 'priority': 1,
                                           'citations': [{'key': 'S1'}]}], 'paragraphs': []}


def setup_claude(*replies):
    transport = FakeTransport({'m': [fake_response(json.dumps(value)) for value in replies]})
    return Claude(transport, Ledger(), {'summariser': 'm'}), transport


def text_blocks(request):
    return [block['text'] for block in request['messages'][0]['content'] if block['type'] == 'text']


def test_D1_summary_request_and_response():
    summarise = require('summarise')
    expected = reply('Revenue rose 12%')
    claude, transport = setup_claude(expected)
    result = asyncio.run(summarise(claude, sections(), job=job(), brief='brief'))
    assert result == SectionDraft.model_validate(expected)
    assert len(transport.requests) == 1
    request = transport.requests[0]
    assert request['model'] == 'm'
    assert request['system'][0] == prompts.system_blocks('gatherer')[0]
    assert request['system'][1]['text'].startswith('ROLE: ')
    assert request['output_config']['effort'] == 'medium'
    text = '\n'.join(text_blocks(request))
    for value in ('Context', 'Delivery', 'Decision', 'Revenue rose 12%', 'The pilot has 3 teams.',
                  'Approve the pilot.', all_manifests()['bullets'].capacity_text()):
        assert value in text
    assert text.index('Context') < text.index('Delivery') < text.index('Decision')


@pytest.mark.parametrize('second_is_valid', [False, True])
def test_D2_unsupported_fact_retries_once(second_is_valid):
    summarise = require('summarise')
    invalid = reply('Revenue rose 14%')
    valid = reply('Revenue rose 12%')
    claude, transport = setup_claude(invalid, valid if second_is_valid else invalid)
    if second_is_valid:
        result = asyncio.run(summarise(claude, sections(), job=job(), brief='brief'))
        assert result == SectionDraft.model_validate(valid)
    else:
        with pytest.raises(PatchRejected) as caught:
            asyncio.run(summarise(claude, sections(), job=job(), brief='brief'))
        assert caught.value.code == 'fact-support'
        assert '14%' in str(caught.value)
    assert len(transport.requests) == 2
    assert any(block.startswith('Unsupported:') and '14%' in block for block in text_blocks(transport.requests[1]))


def test_D3_summary_sources_follow_outline_and_document_order(tmp_path):
    summary_sources = require('summary_sources')
    entries = [Section(id=str(i), intent='bullets', section=slot) for i, slot in
               enumerate(['agenda', 'opener', 'content', 'content', 'ask'])]
    doc = Document(front={}, format='slides', sections=entries)
    path = tmp_path / 'example.yaml'

    def load(fill):
        path.write_text(
            'name: example\nformat: slides\naudience: readers\nlength: {slides: [1, 20]}\n'
            'questions: []\noutline:\n  - section: agenda\n    intent: any\n' + fill +
            '  - section: chapter\n    children:\n      - section: opener\n        intent: any\n'
            '      - section: content\n        intent: any\n  - section: ask\n    intent: any\n'
            'checks: []\nchecklist: []\n', encoding='utf-8')
        return load_doctype(path)

    assert summary_sources(doc, load('    fill: summary\n    from: [chapter]\n')) == {'0': entries[1:4]}
    assert summary_sources(doc, load('    fill: summary\n')) == {'0': entries[1:]}
    assert summary_sources(doc, load('')) == {}


def test_D4_model_override_and_prompt_blocks(tmp_path):
    assert role_models(ProjectConfig()).get('summariser') == 'claude-sonnet-5-5'
    (tmp_path / 'docla.toml').write_text('[models]\nsummariser = "s"\n', encoding='utf-8')
    assert role_models(load_project_config(tmp_path))['summariser'] == 's'
    blocks = prompts.system_blocks('summariser', neutral_theme(), 'brief')
    assert len(blocks) == 4
    assert blocks[-1]['text'] == 'brief'
    assert blocks[-1]['cache_control'] == {'type': 'ephemeral'}


def test_D5_existing_roles_and_models_stay_stable():
    assert prompts.ROLES[:4] == ('gatherer', 'planner', 'writer.draft', 'writer.repair')
    assert 'critic' not in prompts.ROLES and 'summariser' not in prompts.ROLES
    with pytest.raises(ValueError, match='critic'):
        prompts.system_blocks('critic', neutral_theme())
    models = role_models(ProjectConfig())
    assert {role: models[role] for role in ('gatherer', 'planner', 'writer.draft', 'writer.repair')} == {
        'gatherer': 'claude-sonnet-5-5', 'planner': 'claude-opus-5-5',
        'writer.draft': 'claude-sonnet-5-5', 'writer.repair': 'claude-sonnet-5-5',
    }
