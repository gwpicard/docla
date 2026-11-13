# Intent: Spreadsheet cells become ordered, typed facts with precise source locators.
import asyncio
import importlib
import importlib.util
import re
import subprocess
import sys
import tomllib
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path

import pytest

try:
    import docla.tables as tables
except ImportError as error:
    if error.name != "docla.tables" and not (
        error.name and error.name.startswith("docla.tables.") and importlib.util.find_spec(error.name) is None
    ):
        raise
    tables = None

from docla.agents import gatherer
from docla import sources


def api(*names):
    assert tables is not None, "docla.tables must exist"
    for name in names:
        assert hasattr(tables, name), f"docla.tables.{name} must exist"
    return tables


def workbook(path, extra=False):
    assert importlib.util.find_spec("openpyxl") is not None, "openpyxl must be installed"
    openpyxl = importlib.import_module("openpyxl")
    book = openpyxl.Workbook()
    sheet = book.active
    sheet.title = "Sales"
    sheet.append(["Region", "Revenue", "Margin", "Closed", "Deals", "Note"])
    sheet.append(["North", 1234500, 0.125, datetime(2026, 9, 30), 42, "Delayed by audit"])
    sheet.append(["South", 980000.5, None, None, 7, None, "=B2*2"])
    for cell, fmt in {"B2": '"£"#,##0', "C2": "0.0%", "D2": "yyyy-mm-dd", "B3": "#,##0.00"}.items():
        sheet[cell].number_format = fmt
    if extra:
        sheet = book.create_sheet("Q3 Sales")
        sheet.append(["Region", "Revenue"])
        sheet.append(["East", 10, 5])
        book.create_sheet("Empty").append(["Region", "Revenue"])
    book.save(path)


def pipeline(path):
    path.write_text(
        '\ufeffRegion,Revenue,Share,Closed\nNorth,£1200,12%,2026-09-30\nSouth,"1,050",8.5%,Q4\n',
        encoding="utf-8",
    )


def test_D1_workbook_cells(tmp_path):
    module = api("read_cells", "TableCell", "CellValue")
    path = tmp_path / "sales.xlsx"
    workbook(path)
    cells = module.read_cells(path)
    assert all(isinstance(cell, module.TableCell) and isinstance(cell.value, module.CellValue) for cell in cells)
    assert [(c.locator, c.value.kind, c.value.number, c.value.text, c.header, c.label) for c in cells] == [
        ("Sales!B2", "currency", Decimal("1234500"), "£1,234,500", "Revenue", "North"),
        ("Sales!C2", "percent", Decimal("12.5"), "12.5%", "Margin", "North"),
        ("Sales!D2", "date", None, "2026-09-30", "Closed", "North"),
        ("Sales!E2", "number", Decimal("42"), "42", "Deals", "North"),
        ("Sales!F2", "text", None, "Delayed by audit", "Note", "North"),
        ("Sales!B3", "number", Decimal("980000.5"), "980,000.50", "Revenue", "South"),
        ("Sales!E3", "number", Decimal("7"), "7", "Deals", "South"),
    ]
    assert [(c.sheet, c.cell) for c in cells] == [
        ("Sales", "B2"), ("Sales", "C2"), ("Sales", "D2"), ("Sales", "E2"),
        ("Sales", "F2"), ("Sales", "B3"), ("Sales", "E3"),
    ]
    assert cells[0].value.currency == "GBP"
    assert cells[2].value.date == date(2026, 9, 30)


def test_D2_facts_and_sheet_quoting(tmp_path):
    module = api("table_facts", "sheet_locator")
    path = tmp_path / "sales.xlsx"
    workbook(path, extra=True)
    facts = module.table_facts(path, "S1")
    assert facts == [
        gatherer.Fact(text="North, Revenue: £1,234,500", source_key="S1", locator="Sales!B2"),
        gatherer.Fact(text="North, Margin: 12.5%", source_key="S1", locator="Sales!C2"),
        gatherer.Fact(text="North, Closed: 2026-09-30", source_key="S1", locator="Sales!D2"),
        gatherer.Fact(text="North, Deals: 42", source_key="S1", locator="Sales!E2"),
        gatherer.Fact(text="North, Note: Delayed by audit", source_key="S1", locator="Sales!F2"),
        gatherer.Fact(text="South, Revenue: 980,000.50", source_key="S1", locator="Sales!B3"),
        gatherer.Fact(text="South, Deals: 7", source_key="S1", locator="Sales!E3"),
        gatherer.Fact(text="East, Revenue: 10", source_key="S1", locator="'Q3 Sales'!B2"),
        gatherer.Fact(text="East: 5", source_key="S1", locator="'Q3 Sales'!C2"),
    ]
    assert module.sheet_locator("Bob's", "A1") == "'Bob''s'!A1"


def test_D3_csv_and_broken_workbook(tmp_path):
    module = api("read_cells", "TableError")
    path = tmp_path / "pipeline.csv"
    pipeline(path)
    cells = module.read_cells(path)
    assert [(c.locator, c.value.kind, c.value.number, c.value.text, c.label, c.header) for c in cells] == [
        ("pipeline!B2", "currency", Decimal("1200"), "£1200", "North", "Revenue"),
        ("pipeline!C2", "percent", Decimal("12"), "12%", "North", "Share"),
        ("pipeline!D2", "date", None, "2026-09-30", "North", "Closed"),
        ("pipeline!B3", "number", Decimal("1050"), "1,050", "South", "Revenue"),
        ("pipeline!C3", "percent", Decimal("8.5"), "8.5%", "South", "Share"),
        ("pipeline!D3", "text", None, "Q4", "South", "Closed"),
    ]
    broken = tmp_path / "broken.xlsx"
    broken.write_bytes(b"not a workbook")
    with pytest.raises(module.TableError, match="broken.xlsx"):
        module.read_cells(broken)


class CitingClaude:
    def __init__(self):
        self.calls = []

    async def cite(self, role, *, system, content):
        self.calls.append((role, system, content))
        return {"content": [{"type": "text", "citations": [
            {"type": "char_location", "cited_text": "A note.", "start_char_index": 0, "end_char_index": 7}
        ]}]}


def test_D4_extraction_and_gathering(tmp_path):
    api("table_facts")
    directory = tmp_path / "sources"
    directory.mkdir()
    (directory / "notes.txt").write_text("A note.\n", encoding="utf-8")
    pipeline(directory / "pipeline.csv")
    workbook(directory / "sales.xlsx")
    extracted = sources.extract(tmp_path)
    assert [(s.key, s.name, s.kind, s.pages) for s in extracted] == [
        ("S1", "notes.txt", "text", None), ("S2", "pipeline.csv", "table", None),
        ("S3", "sales.xlsx", "table", None),
    ]
    sales = tmp_path / "extracted" / "sales.xlsx.md"
    assert sales.read_text(encoding="utf-8") == extracted[2].text
    assert extracted[2].text.splitlines()[0] == "[Sales!B2] North, Revenue: £1,234,500"
    assert extracted[2].text.endswith("\n") and not extracted[2].text.endswith("\n\n")
    before = {p.name: p.read_bytes() for p in (tmp_path / "extracted").iterdir()}
    sources.extract(tmp_path)
    assert {p.name: p.read_bytes() for p in (tmp_path / "extracted").iterdir()} == before
    claude = CitingClaude()
    facts = asyncio.run(gatherer.gather(claude, extracted))
    assert len(claude.calls) == 1
    assert claude.calls[0][2][0]["title"] == "S1 notes.txt"
    assert [(f.text, f.source_key, f.locator) for f in facts] == [
        ("A note.", "S1", None),
        ("North, Revenue: £1200", "S2", "pipeline!B2"),
        ("North, Share: 12%", "S2", "pipeline!C2"),
        ("North, Closed: 2026-09-30", "S2", "pipeline!D2"),
        ("South, Revenue: 1,050", "S2", "pipeline!B3"),
        ("South, Share: 8.5%", "S2", "pipeline!C3"),
        ("South, Closed: Q4", "S2", "pipeline!D3"),
        ("North, Revenue: £1,234,500", "S3", "Sales!B2"),
        ("North, Margin: 12.5%", "S3", "Sales!C2"),
        ("North, Closed: 2026-09-30", "S3", "Sales!D2"),
        ("North, Deals: 42", "S3", "Sales!E2"),
        ("North, Note: Delayed by audit", "S3", "Sales!F2"),
        ("South, Revenue: 980,000.50", "S3", "Sales!B3"),
        ("South, Deals: 7", "S3", "Sales!E3"),
    ]


def test_D5_dependencies_licence_and_selection(tmp_path):
    root = Path(__file__).resolve().parents[2]
    config = tomllib.loads((root / "pyproject.toml").read_text(encoding="utf-8"))
    assert "openpyxl" in {re.split(r"[\s\[<>=!~;]", item)[0].lower() for item in config["project"]["dependencies"]}
    assert "types-openpyxl" in {
        re.split(r"[\s\[<>=!~;]", item)[0].lower() for item in config["dependency-groups"]["dev"]
    }
    result = subprocess.run([sys.executable, str(root / "scripts/licence_report.py")], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    assert any(line.split()[0].lower() == "openpyxl" and line.split()[-1] == "MIT" for line in result.stdout.splitlines())
    directory = tmp_path / "sources"
    directory.mkdir()
    (directory / "a.md").write_text("Alpha\n", encoding="utf-8")
    (directory / "image.png").write_bytes(b"image")
    (directory / "old.xls").write_bytes(b"old")
    assert [(s.key, s.name) for s in sources.extract(tmp_path)] == [("S1", "a.md")]
