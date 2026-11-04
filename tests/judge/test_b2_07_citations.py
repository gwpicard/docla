# Intent: show item citation keys and locators while preserving existing slide marks and clean checks.
import importlib
import json
import shutil


def _optional(name):
    try:
        return importlib.import_module(name)
    except ImportError as error:
        if error.name not in ("docla", name) and not name.startswith(str(error.name) + "."):
            raise
        return None


model = _optional("docla.model")
compose = _optional("docla.render.compose")
typst = _optional("docla.render.typst")
layout = _optional("docla.facts.layout")
marks = _optional("docla.render.marks")
kit = _optional("docla.render.kit")
cli = _optional("docla.cli")


def _render(tmp_path, fmt, intent, items):
    assert model is not None and hasattr(model, "Document") and hasattr(model, "Section")
    assert compose is not None and hasattr(compose, "compose") and hasattr(compose, "assemble")
    assert typst is not None and hasattr(typst, "compile_pdf")
    assert layout is not None and hasattr(layout, "layout_facts")
    doc = model.Document(front={}, format=fmt, sections=[model.Section(id="s1", intent=intent, title="Evidence", items=items)])
    root = tmp_path / "render"
    main = compose.assemble(compose.compose(doc), root)
    pdf = tmp_path / "out.pdf"
    typst.compile_pdf(main, root, pdf)
    return layout.layout_facts(pdf, main, root)


def test_D1_bullets_print_key_and_locator_after_body(tmp_path):
    facts = _render(tmp_path, "slides", "bullets", [{"body": "Claim here.", "citations": [{"key": "S1", "locator": "00:41"}]}])
    words = [word.text for word in facts.words]
    assert words == ["Evidence", "Claim", "here.", "[S1", "00:41]"]
    citation = [word for word in facts.words if word.text in ("[S1", "00:41]")]
    assert [word.colour for word in citation] == ["#6B6B6B", "#6B6B6B"]
    assert [word.size for word in citation] == [20, 20]
    assert [word.role for word in citation] == ["item", "item"]


def test_D2_m1_slide_marks_stay_in_their_frames(tmp_path):
    assert kit is not None and hasattr(kit, "lib_dir") and hasattr(kit, "components_dir")
    assert marks is not None and hasattr(marks, "read_marks")
    shutil.copytree(kit.lib_dir(), tmp_path / "lib")
    shutil.copytree(kit.components_dir(), tmp_path / "components")
    sec = {"id": "s2", "title": "Plan", "items": [{"head": f"Head {i}", "body": "Short body", "cites": []} for i in range(1, 4)], "paragraphs": [], "source_line": ""}
    (tmp_path / "sec.json").write_text(json.dumps(sec))
    main = tmp_path / "main.typ"
    main.write_text('#import "/lib/theme.typ": page-setup\n#import "/components/bullets.typ": bullets\n#page-setup("slides")[#bullets(json("/sec.json"))]\n')
    result = marks.read_marks(main, tmp_path)
    fits = [m for m in result if isinstance(m, marks.FitMark)]
    assert [(m.role, m.id, m.have) for m in fits] == [("title", "s2", 60), ("body", "s2", 380)]
    items = [m for m in result if isinstance(m, marks.ElementMark) and m.role == "item"]
    assert len(items) == 3
    assert all(abs(m.x - 40) <= 0.5 and m.y >= 120 and m.y + m.h <= 500 for m in items)
    assert [m.y for m in items] == sorted(m.y for m in items)
    assert len({m.y for m in items}) == 3


def test_D3_callout_cited_and_uncited_items(tmp_path):
    facts = _render(tmp_path, "doc", "callout", [
        {"body": "First claim.", "citations": [{"key": "S1", "locator": "00:41"}, {"key": "S2", "locator": "p.7"}]},
        {"body": "Second claim."},
    ])
    assert [word.text for word in facts.words if word.text != "•"] == ["Evidence", "First", "claim.", "[S1", "00:41]", "[S2", "p.7]", "Second", "claim."]


def test_D4_clean_m1_checks_print_exactly_no_findings(tmp_path, capsys):
    assert cli is not None and hasattr(cli, "main"), "docla.cli.main must exist"
    slides = '''---
doctype: pitch-deck
format: slides
title: Readout
---

## Sources

- [S1] workshop.vtt, transcript

::: {#aaaa1 .section intent="statement"}
## One pilot is enough
:::

::: {#aaaa2 .section intent="bullets"}
## Why it works

- Short intervals catch drift early. [S1 00:41]
- Cheap to repeat.
:::
'''
    doc = '''---
doctype: report
format: doc
title: Note
---

## Sources

- [S1] workshop.vtt, transcript

::: {#bbbb1 .section intent="body"}
## Findings

The pipeline drops some readings, and the team agreed to measure how many. [S1 00:41]
:::
'''
    for name, text in (("deck", slides), ("note", doc)):
        source = tmp_path / f"{name}.md"
        source.write_text(text)
        try:
            code = cli.main(["check", str(source), "--out", str(tmp_path / name)])
        except SystemExit as error:
            code = error.code
        captured = capsys.readouterr()
        assert code == 0
        assert captured.out == "no findings\n"
