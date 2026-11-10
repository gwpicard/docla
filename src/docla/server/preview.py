"""Render and check previews after accepted content edits."""

import asyncio
import base64
import tempfile
from pathlib import Path
from typing import Any

from starlette.datastructures import State

from docla.checks.catalogue import all_rules
from docla.checks.engine import TIERS, CheckContext, run_checks
from docla.facts.layout import layout_facts
from docla.facts.raster import PdfiumRasteriser
from docla.model import Document, Section
from docla.render.compose import ComposeError, assemble, compose, font_paths
from docla.render.kit import read_tokens
from docla.render.swatch import swatch
from docla.render.typst import TypstError, compile_pdf
from docla.server.versions import finding_views
from docla.store import page_index
from docla.theme.rules import load_theme_rules


def flow_sensitive(doc: Document, section: Section) -> bool:
    return doc.format == "doc"


def _render(state: State, doc: Document, section_id: str) -> dict[str, Any]:
    theme = state.theme
    project: Path = state.project
    assets = [project / "assets", theme.root / "assets"]
    rules = all_rules() + load_theme_rules(theme)
    root = project / ".docla" / "render" / "preview"
    root.mkdir(parents=True, exist_ok=True)
    section = next(s for s in doc.sections if s.id == section_id)
    if flow_sensitive(doc, section):
        dest = Path(tempfile.mkdtemp(dir=root, prefix="draft-")) / "render"
        composition = compose(doc, assets=assets)
        main = assemble(composition, dest, theme=theme)
        fonts = font_paths(dest)
        pdf = dest / "draft.pdf"
        compile_pdf(main, dest, pdf, fonts)
        facts = layout_facts(pdf, main, dest, font_paths=fonts)
        pngs = PdfiumRasteriser().render(pdf, dest / "pages")
    else:
        doc = doc.model_copy(update={"sections": [section]})
        render = swatch(doc, section_id, root, theme, assets=assets)
        main, facts, pngs = render.main, render.facts, render.pngs
        composition = compose(doc, assets=assets)
    ctx = CheckContext(
        doc,
        facts,
        read_tokens(main.parent),
        theme=theme,
        composition=composition,
        final=False,
        assets=assets,
        pages_png=pngs,
    )
    findings = [f for tier in TIERS for f in run_checks([r for r in rules if r.tier == tier], ctx)]
    kept = [f for f in findings if f.section_id in (section_id, None)]
    if flow_sensitive(doc, section):
        page = next(p["page"] for p in page_index(facts, findings) if section_id in p["sections"])
        image = pngs[page - 1]
    else:
        image = pngs[0]
    return {
        "state": "findings" if kept else "clean",
        "findings": finding_views(kept, rules),
        "png": base64.b64encode(image.read_bytes()).decode("ascii"),
    }


async def preview(state: State, name: str, section_id: str, rev: int, doc: Document | None = None) -> None:
    locks: dict[str, asyncio.Lock] = state.preview_locks
    async with locks.setdefault(name, asyncio.Lock()):
        data = {"doc": name, "id": section_id, "rev": rev}
        state.bus.publish("section.state", {**data, "state": "working"})
        try:
            document = doc if doc is not None else state.docs.load(name)
            result = await asyncio.to_thread(_render, state, document, section_id)
        except (ComposeError, TypstError) as exc:
            state.bus.publish("section.state", {**data, "state": "error", "message": str(exc)})
            return
        state.bus.publish("section.state", {**data, **result})
        state.bus.publish("look.progress", {"doc": name, "done": 1, "total": 1})
