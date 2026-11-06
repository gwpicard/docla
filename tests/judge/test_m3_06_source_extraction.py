# Extract project sources into stable, complete plain-text files.
import importlib.util
from pathlib import Path

from docla.render.typst import compile_pdf
from docla.theme import neutral_theme

try:
    import docla.sources as sources
except ImportError as error:
    if error.name != "docla.sources" and not (
        error.name and error.name.startswith("docla.sources.") and importlib.util.find_spec(error.name) is None
    ):
        raise
    sources = None


def get_api():
    assert sources is not None and hasattr(sources, "extract") and hasattr(sources, "Extracted"), (
        "docla.sources.extract and Extracted must exist"
    )
    return sources


def make_pdf(project: Path) -> None:
    source_dir = project / "sources"
    source_dir.mkdir(parents=True, exist_ok=True)
    main = project / "report.typ"
    main.write_text(
        "First page words.\n#pagebreak()\nSecond page words.\n#pagebreak()\nThird page words.\n",
        encoding="utf-8",
    )
    compile_pdf(main, project, source_dir / "report.pdf", [neutral_theme().fonts_dir])


def make_vtt(project: Path) -> None:
    source_dir = project / "sources"
    source_dir.mkdir(parents=True, exist_ok=True)
    (source_dir / "workshop.vtt").write_text(
        "WEBVTT\n\ncue-one\n00:00:41.000 --> 00:00:45.000\n"
        "<v Maria>Short intervals catch drift early.\n\n"
        "01:02:03.500 --> 01:02:09.000\nCheap to repeat.\n",
        encoding="utf-8",
    )


def test_D1_pdf_pages_and_metadata(tmp_path):
    api = get_api()
    make_pdf(tmp_path)
    results = api.extract(tmp_path)
    assert len(results) == 1
    item = results[0]
    assert isinstance(item, api.Extracted)
    assert (item.key, item.name, item.kind, item.pages) == ("S1", "report.pdf", "pdf", 3)
    assert item.source == tmp_path / "sources" / "report.pdf"
    assert item.path == tmp_path / "extracted" / "report.pdf.md"
    assert item.path.is_file()
    assert item.path.read_text(encoding="utf-8") == item.text
    parts = item.text.split("<!-- page ")
    assert len(parts) == 4
    assert parts[1].startswith("1 -->\n") and "First page words." in parts[1]
    assert parts[2].startswith("2 -->\n") and "Second page words." in parts[2]
    assert parts[3].startswith("3 -->\n") and "Third page words." in parts[3]
    assert item.text.endswith("\n") and not item.text.endswith("\n\n")


def test_D2_vtt_cues(tmp_path):
    api = get_api()
    make_vtt(tmp_path)
    results = api.extract(tmp_path)
    assert len(results) == 1
    item = results[0]
    assert (item.kind, item.pages) == ("vtt", None)
    assert item.text == ("[00:41] Maria: Short intervals catch drift early.\n[01:02:03] Cheap to repeat.\n")
    assert item.path.read_text(encoding="utf-8") == item.text
    for unwanted in ("WEBVTT", "-->", "cue-one", "<v"):
        assert unwanted not in item.text


def test_D3_selection_order_and_complete_text(tmp_path):
    api = get_api()
    assert api.extract(tmp_path / "missing") == []
    source_dir = tmp_path / "sources"
    source_dir.mkdir()
    (source_dir / "a.md").write_text("Alpha\n", encoding="utf-8")
    (source_dir / "b.txt").write_bytes(b"First\r\nSecond\r\n")
    (source_dir / "c.vtt").write_text("WEBVTT\n", encoding="utf-8")
    (source_dir / ".DS_Store").write_text("hidden", encoding="utf-8")
    (source_dir / "image.png").write_bytes(b"image")
    results = api.extract(tmp_path)
    assert [(item.key, item.name) for item in results] == [("S1", "a.md"), ("S2", "b.txt"), ("S3", "c.vtt")]
    assert sorted(path.name for path in (tmp_path / "extracted").iterdir()) == ["a.md.md", "b.txt.md", "c.vtt.md"]
    assert results[1].kind == "text" and results[1].pages is None
    assert results[1].text == "First\nSecond\n"
    assert results[1].path.read_bytes() == b"First\nSecond\n"
    long_project = tmp_path / "long"
    (long_project / "sources").mkdir(parents=True)
    long_text = "x" * 300_000
    (long_project / "sources" / "long.txt").write_text(long_text, encoding="utf-8")
    long_results = api.extract(long_project)
    assert len(long_results) == 1
    assert long_results[0].text == long_text + "\n"
    assert long_results[0].path.read_bytes() == (long_text + "\n").encode("utf-8")


def test_D4_repeat_extraction_is_stable(tmp_path):
    api = get_api()
    make_pdf(tmp_path)
    make_vtt(tmp_path)
    (tmp_path / "sources" / "notes.txt").write_text("A note.\n", encoding="utf-8")
    first = api.extract(tmp_path)
    assert [(item.key, item.name) for item in first] == [
        ("S1", "notes.txt"),
        ("S2", "report.pdf"),
        ("S3", "workshop.vtt"),
    ]
    before = {path.name: path.read_bytes() for path in (tmp_path / "extracted").iterdir()}
    second = api.extract(tmp_path)
    after = {path.name: path.read_bytes() for path in (tmp_path / "extracted").iterdir()}
    assert first == second
    assert before == after
    assert set(before) == {"notes.txt.md", "report.pdf.md", "workshop.vtt.md"}
