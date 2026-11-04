# Intent: shared slide frames and neutral type roles provide consistent component layout.
import json
import shutil
from pathlib import Path

from docla.facts.pdf import PdfPlumberFacts
from docla.model import Document, Section
from docla.render import compose, kit, marks, typst
from docla.theme import neutral_theme


def _assemble(tmp_path: Path) -> Path:
    doc = Document(front={}, format="slides", sections=[Section(id="s1", intent="statement", title="Example")])
    dest = tmp_path / "render"
    compose.assemble(compose.compose(doc), dest, theme=neutral_theme())
    return dest


def _eval(root: Path, source: str, expression: str):
    main = root / "probe.typ"
    main.write_text(source + "\n#metadata(" + expression + ") <probe>\n", encoding="utf-8")
    return json.loads(typst.run_typst(["eval", "query(<probe>).first().value", "--in", str(main)], root, compose.font_paths(root)))


def test_D1_frames_and_slide_title(tmp_path: Path):
    root = _assemble(tmp_path)
    assert (root / "lib" / "frames.typ").is_file(), "assemble must include lib/frames.typ"
    values = _eval(root, '#import "/lib/frames.typ": title-frame, content-frame, full-frame',
                   '(title: (title-frame.x.pt(), title-frame.y.pt(), title-frame.w.pt(), title-frame.h.pt()), content: (content-frame.x.pt(), content-frame.y.pt(), content-frame.w.pt(), content-frame.h.pt()), full: (full-frame.x.pt(), full-frame.y.pt(), full-frame.w.pt(), full-frame.h.pt()))')
    assert values == {"title": [40, 40, 880, 60], "content": [40, 120, 880, 380], "full": [40, 40, 880, 460]}
    main = root / "title.typ"
    main.write_text('#import "/lib/theme.typ": page-setup\n#import "/lib/frames.typ": slide-title\n#show: page-setup.with("slides")\n#slide-title((id: "s1", title: "Example"))\n', encoding="utf-8")
    fits = [m for m in marks.read_marks(main, root, compose.font_paths(root)) if isinstance(m, marks.FitMark)]
    assert [(m.role, m.id, m.have, m.ok) for m in fits] == [("title", "s1", 60, True)]
    pdf = root / "title.pdf"
    typst.compile_pdf(main, root, pdf, compose.font_paths(root))
    pages = PdfPlumberFacts().extract(pdf)
    assert len(pages) == 1
    assert (pages[0].width, pages[0].height) == (960, 540)
    word = pages[0].words[0]
    assert word.text == "Example"
    assert abs(word.box.x0 - 40) < 1
    assert 40 <= word.box.y0 < 100
    assert abs(word.size - 32) < 0.1


def test_D2_neutral_slide_roles_obey_minimum():
    scale = neutral_theme().tokens.type.scale["slides"]
    assert scale.min_size == 18
    assert all(role.size >= 18 for role in scale.roles.values())
    assert (scale.roles["figure"].family, scale.roles["figure"].size, scale.roles["figure"].weight) == ("display", 48, 600)
    assert (scale.roles["label"].family, scale.roles["label"].size) == ("text", 18)
    assert scale.roles["caption"].size == 18


def test_D3_stub_tokens_and_existing_component_frames(tmp_path: Path):
    shutil.copytree(kit.lib_dir(), tmp_path / "lib")
    shutil.copytree(kit.components_dir(), tmp_path / "components")
    assert _eval(tmp_path, '#import "/lib/theme.typ": tokens', 'tokens.keys().sorted()') == ["accent", "ink", "muted", "paper"]
    for component, expected in (("statement", [("title", 300)]), ("bullets", [("title", 60), ("body", 380)])):
        main = tmp_path / f"{component}.typ"
        main.write_text('#import "/lib/theme.typ": page-setup\n' + f'#import "/components/{component}.typ": {component}\n' + f'#show: page-setup.with("slides")\n#{component}((id: "s1", title: "Example", items: ((head: "First", body: "Point"),)))\n', encoding="utf-8")
        fits = [m for m in marks.read_marks(main, tmp_path) if isinstance(m, marks.FitMark)]
        assert [(m.role, m.have) for m in fits] == expected


def test_D4_generated_theme_names_and_new_styles(tmp_path: Path):
    roles = neutral_theme().tokens.type.scale["slides"].roles
    assert "figure" in roles and "label" in roles, "figure and label roles must exist"
    root = _assemble(tmp_path)
    values = _eval(root, '#import "/lib/theme.typ": colour, page-setup, type-style, space', '(figure: type-style("slides", "figure").size.pt(), label: type-style("slides", "label").size.pt(), body: type-style("doc", "body").size.pt(), space: space(3).pt())')
    assert values == {"figure": 48, "label": 18, "body": 11, "space": 16}
    main = root / "styles.typ"
    main.write_text('#import "/lib/theme.typ": colour, page-setup, type-style\n#show: page-setup.with("slides")\n#text(..type-style("slides", "figure"), fill: colour("ink"))[42] #text(..type-style("slides", "label"))[Label]\n', encoding="utf-8")
    pdf = root / "styles.pdf"
    typst.compile_pdf(main, root, pdf, compose.font_paths(root))
    words = PdfPlumberFacts().extract(pdf)[0].words
    assert [(word.text, round(word.size)) for word in words] == [("42", 48), ("Label", 18)]
