# Intent: run background builds and redrafts with observable results and staleness.
import asyncio
import importlib
import importlib.util
import json
import time

from docla.model import Patch, PatchOp
from docla.source.files import apply_to_file, current_rev
from docla.source.ids import IdStore
from docla.source.parser import parse
from docla.source.serialiser import serialise
from docla.write import Agents
from judge.test_m1_17_cli_build_check import SLIDES


def _module(name):
    try:
        return importlib.import_module(name)
    except ImportError as error:
        missing = error.name
        if not missing or not (name == missing or name.startswith(missing + '.')):
            raise
        if importlib.util.find_spec(missing) is not None:
            raise
        return None


jobs = _module('docla.server.jobs')
server = _module('docla.server.app')
events = _module('docla.server.events')


def _interface(module, name):
    assert module is not None and hasattr(module, name), f'{name} must exist'
    return getattr(module, name)


def _wait(runner, job_id):
    deadline = time.monotonic() + 120
    while time.monotonic() < deadline:
        job = runner.get(job_id)
        assert job is not None
        if job.status != 'running':
            assert job.status == 'finished', job.error
            return job
        time.sleep(0.05)
    assert False, 'job timed out'


class FakeWriter:
    def __init__(self, doc, states=None, redraft=False):
        self.doc, self.states, self.redraft = doc, states, redraft

    async def draft(self, job):
        return next(s for s in self.doc.sections if s.id == job.section_id).model_copy(deep=True)

    async def repair(self, job, state, history, *, strategy=None):
        if self.states is not None:
            self.states.append(state.model_copy(deep=True))
        ops = [PatchOp(op='set_fields', section_id=job.section_id, fields={'title': 'Why'})] if self.redraft else []
        return Patch(base_rev=self.doc.rev, author='ai', reason='repair', ops=ops)


def _app(path, writer):
    create_app = _interface(server, 'create_app')
    (path / 'deck.md').write_text(serialise(parse(SLIDES)[0]), encoding='utf-8')
    agents = Agents(gather=lambda *a: None, outline=lambda *a: None, writer=writer)
    import inspect

    assert "agents" in inspect.signature(create_app).parameters, "create_app must accept agents="
    return create_app(path, 'test-token', agents=agents)


def _client(app):
    from fastapi.testclient import TestClient
    return TestClient(app, base_url='http://127.0.0.1:8765', headers={'X-Docla-Token': 'test-token'})


def _post(client, app, url, body):
    response = client.post(url, json=body)
    assert response.status_code == 202, response.text
    job_id = response.json()['job']
    assert isinstance(job_id, str) and job_id
    return _wait(app.state.jobs, job_id)


def _drain(client, queue):
    async def drain():
        found = []
        while not queue.empty():
            found.append(queue.get_nowait())
        return found
    return client.portal.call(drain)


def test_D1_job_events_and_failure():
    runner_type = _interface(jobs, 'JobRunner')
    bus_type = _interface(events, 'EventBus')

    async def exercise():
        bus = bus_type()
        queue = bus.subscribe()
        runner = runner_type(bus)

        async def success(progress):
            progress({'stage': 'x'})
            return {'ok': 1}

        async def failure(progress):
            raise RuntimeError('boom')

        async def finish(job):
            for _ in range(1000):
                current = runner.get(job.id)
                if current is not None and current.status != 'running':
                    await asyncio.sleep(0.01)
                    return current
                await asyncio.sleep(0.01)
            assert False, 'job timed out'

        started = runner.start('build', 'deck', success)
        done = await finish(started)
        assert (done.status, done.result, done.error) == ('finished', {'ok': 1}, None)
        found = []
        while not queue.empty():
            found.append(queue.get_nowait())
        matching = [e for e in found if e['data']['id'] == started.id]
        assert [e['type'] for e in matching] == ['job.started', 'job.progress', 'job.finished']
        assert matching[0]['data'] == {'id': started.id, 'kind': 'build', 'doc': 'deck'}
        assert matching[1]['data'] == {'id': started.id, 'kind': 'build', 'doc': 'deck', 'stage': 'x'}
        assert matching[2]['data'] == {'id': started.id, 'kind': 'build', 'doc': 'deck', 'status': 'finished', 'result': {'ok': 1}, 'error': None}
        failed = runner.start('build', 'deck', failure)
        done = await finish(failed)
        assert (done.status, done.result, done.error) == ('failed', None, 'boom')
        found = []
        while not queue.empty():
            found.append(queue.get_nowait())
        matching = [e for e in found if e['data']['id'] == failed.id]
        assert [e['type'] for e in matching] == ['job.started', 'job.finished']
        assert matching[-1]['data']['status'] == 'failed'
        assert matching[-1]['data']['error'] == 'boom'
        assert runner.get('unknown-job') is None
    asyncio.run(exercise())


def test_D2_build_versions_and_mode(tmp_path):
    app = _app(tmp_path, lambda facts, doc: FakeWriter(doc))
    with _client(app) as client:
        queue = client.portal.call(app.state.bus.subscribe)
        draft = _post(client, app, '/api/docs/deck/build', {'mode': 'draft'})
        assert draft.result == {'version': 1, 'stale': False, 'snapshot_rev': 0}
        assert json.loads((tmp_path / 'deck.versions/v1/manifest.json').read_text())['final'] is False
        assert {'type': 'build.finished', 'data': {'doc': 'deck', 'version': 1, 'stale': False}} in _drain(client, queue)
        final = _post(client, app, '/api/docs/deck/build', {'mode': 'final'})
        assert final.result == {'version': 2, 'stale': False, 'snapshot_rev': 0}
        assert json.loads((tmp_path / 'deck.versions/v2/manifest.json').read_text())['final'] is True
        assert client.post('/api/docs/deck/build', json={'mode': 'fast'}).status_code == 422


def test_D3_human_edit_during_build_marks_stale(tmp_path):
    def writer(facts, doc):
        oplog = tmp_path / '.docla/oplog.jsonl'
        patch = Patch(base_rev=current_rev(oplog), author='human', reason='edit during build', ops=[PatchOp(op='set_fields', section_id='aaaa1', fields={'title': 'One pilot'})])
        apply_to_file(tmp_path / 'deck.md', patch, oplog, IdStore(tmp_path / '.docla/ids.json'))
        return FakeWriter(doc)
    app = _app(tmp_path, writer)
    with _client(app) as client:
        queue = client.portal.call(app.state.bus.subscribe)
        job = _post(client, app, '/api/docs/deck/build', {'mode': 'draft'})
        assert job.result == {'version': 1, 'stale': True, 'snapshot_rev': 0}
        assert {'type': 'build.finished', 'data': {'doc': 'deck', 'version': 1, 'stale': True}} in _drain(client, queue)


def test_D4_redraft_owned_section_is_a_proposal(tmp_path):
    states = []
    app = _app(tmp_path, lambda facts, doc: FakeWriter(doc, states, True))
    with _client(app) as client:
        response = client.patch('/api/docs/deck/sections/aaaa2', json={'base_rev': 0, 'fields': {'title': 'Why it works'}})
        assert response.status_code == 200, response.text
        source, oplog = tmp_path / 'deck.md', tmp_path / '.docla/oplog.jsonl'
        before = source.read_bytes(), oplog.read_bytes()
        url = '/api/docs/deck/sections/aaaa2/redraft'
        job = _post(client, app, url, {'ask': 'Make the title shorter'})
        assert job.result['section_id'] == 'aaaa2'
        assert job.result['before']['title'] == 'Why it works'
        assert job.result['before']['owner'] == 'human'
        assert job.result['after']['title'] == 'Why'
        assert job.result['status'] in ('clean', 'residual')
        assert isinstance(job.result['findings'], list)
        assert any(f.rule_id == 'human.ask' and f.message == 'Make the title shorter' and f.remedy.class_ == 'redraft' for state in states for f in state.findings)
        assert (source.read_bytes(), oplog.read_bytes()) == before
        assert client.post(url, json={'ask': '  '}).status_code == 422
        assert client.post('/api/docs/deck/sections/zzzzz/redraft', json={'ask': 'Shorten'}).status_code == 404
        assert (source.read_bytes(), oplog.read_bytes()) == before


def test_D5_injected_agents_do_not_create_transport(tmp_path, monkeypatch):
    import docla.write
    def forbidden(*args, **kwargs):
        raise AssertionError('injected agents must not create a transport')
    monkeypatch.setattr(docla.write, 'transport_for', forbidden)
    app = _app(tmp_path, lambda facts, doc: FakeWriter(doc, redraft=True))
    with _client(app) as client:
        assert _post(client, app, '/api/docs/deck/build', {'mode': 'draft'}).result['version'] == 1
        assert _post(client, app, '/api/docs/deck/build', {'mode': 'final'}).result['version'] == 2
        assert _post(client, app, '/api/docs/deck/sections/aaaa2/redraft', {'ask': 'Make the title shorter'}).result['after']['title'] == 'Why'
