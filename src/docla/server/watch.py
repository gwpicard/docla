"""Poll working documents for edits made outside the visualiser."""

import asyncio
import json
from collections.abc import Awaitable, Callable

from docla.checks.catalogue import all_rules
from docla.model import Finding, Patch
from docla.server.docs import DocumentService, document_names
from docla.server.versions import finding_views
from docla.source import parse
from docla.source.files import UNPARSEABLE_RULES, apply_to_document, current_rev
from docla.source.patches import PatchRejected, diff_ops
from docla.theme import neutral_theme
from docla.theme.rules import load_theme_rules


class FileWatcher:
    def __init__(
        self,
        service: DocumentService,
        *,
        interval: float = 0.5,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ) -> None:
        self.service = service
        self.interval = interval
        self.sleep = sleep
        self.pending: dict[str, bytes] = {}

    async def poll(self) -> list[str]:
        changed = []
        async with self.service.lock:
            for name in document_names(self.service.project):
                if self._poll_one(name):
                    changed.append(name)
        return changed

    def _poll_one(self, name: str) -> bool:
        service = self.service
        path = service.path(name)
        data = path.read_bytes()
        if name not in service.last_bytes:
            service.load(name)
            return False
        if data == service.last_bytes[name]:
            self.pending.pop(name, None)
            return False
        rev = current_rev(service.oplog)
        if rev > service.last_rev[name]:
            doc, findings = parse(data.decode("utf-8"))
            if not any(f.rule_id in UNPARSEABLE_RULES for f in findings):
                service.record(name, data, doc.model_copy(update={"rev": rev}))
                author = json.loads(service.oplog.read_text(encoding="utf-8").splitlines()[-1])["author"]
                service.bus.publish("doc.changed", {"doc": name, "rev": rev, "by": author})
                self.pending.pop(name, None)
                return True
        if self.pending.get(name) != data:
            self.pending[name] = data
            return False
        self.pending.pop(name, None)
        return self._external(name, data, rev)

    def _external(self, name: str, data: bytes, rev: int) -> bool:
        service = self.service
        doc, findings = parse(data.decode("utf-8"))
        if any(f.rule_id in UNPARSEABLE_RULES for f in findings):
            return self._invalid(name, data, findings)
        ops = diff_ops(service.last_good[name], doc)
        if not ops:
            service.record(name, data, service.last_good[name])
            return False
        for op in ops:
            if op.op == "set_fields":
                op.fields = {**(op.fields or {}), "owner": "human"}
            if op.op == "insert_after" and op.value is not None:
                op.value.owner = "human"
        patch = Patch(base_rev=rev, author="human", reason="External edit", ops=ops)
        try:
            result = apply_to_document(service.path(name), service.last_good[name], patch, service.oplog, service.ids)
        except PatchRejected:
            return self._invalid(name, data, findings)
        service.record(name, service.path(name).read_bytes(), result)
        service.bus.publish("doc.changed", {"doc": name, "rev": result.rev, "by": "human"})
        return True

    def _invalid(self, name: str, data: bytes, findings: list[Finding]) -> bool:
        service = self.service
        service.last_bytes[name] = data
        service.last_rev[name] = current_rev(service.oplog)
        rules = all_rules() + load_theme_rules(neutral_theme())
        service.bus.publish("queue.changed", {"doc": name, "findings": finding_views(findings, rules)})
        return True

    async def run(self) -> None:
        while True:
            await self.poll()
            await self.sleep(self.interval)
