"""Read spreadsheet cells as typed, located facts."""

import csv
import re
from datetime import date as Date
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from typing import Literal

import openpyxl
from openpyxl.utils import get_column_letter
from pydantic import BaseModel

from docla.agents.gatherer import Fact

ValueKind = Literal["number", "percent", "currency", "date", "text"]
_CURRENCIES = {"£": "GBP", "$": "USD", "€": "EUR"}
_NUMBER = r"\d[\d,]*(?:\.\d+)?"


class CellValue(BaseModel):
    kind: ValueKind
    number: Decimal | None = None
    currency: str | None = None
    date: Date | None = None
    text: str


class TableCell(BaseModel):
    sheet: str
    cell: str
    locator: str
    header: str | None
    label: str | None
    value: CellValue


class TableError(Exception):
    """A table could not be read."""


def sheet_locator(sheet: str, cell: str) -> str:
    if not re.fullmatch(r"[A-Za-z0-9_]+", sheet):
        sheet = "'" + sheet.replace("'", "''") + "'"
    return f"{sheet}!{cell}"


def parse_text_value(text: str) -> CellValue:
    text = text.strip()
    if re.fullmatch(rf"[-+]?{_NUMBER}%", text):
        return CellValue(kind="percent", number=Decimal(text[:-1].replace(",", "")), text=text)
    match = re.fullmatch(rf"([-+]?)([£$€])({_NUMBER})", text)
    if match:
        return CellValue(
            kind="currency",
            number=Decimal((match[1] + match[3]).replace(",", "")),
            currency=_CURRENCIES[match[2]],
            text=text,
        )
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", text):
        try:
            return CellValue(kind="date", date=Date.fromisoformat(text), text=text)
        except ValueError:
            pass
    if re.fullmatch(rf"[-+]?{_NUMBER}", text):
        return CellValue(kind="number", number=Decimal(text.replace(",", "")), text=text)
    return CellValue(kind="text", text=text)


def _numeric(value: int | float, fmt: str) -> CellValue:
    number = Decimal(str(value))
    section = fmt.split(";", 1)[0]
    placeholders = re.sub(r'"[^"]*"|\[[^\]]*\]', "", section)
    decimals = sum(c in "0#" for c in placeholders.split(".", 1)[1]) if "." in placeholders else 0
    grouping = "," in placeholders
    if "%" in section:
        number *= 100
        text = f"{number:,.{decimals}f}%" if grouping else f"{number:.{decimals}f}%"
        return CellValue(kind="percent", number=number, text=text)
    symbol = next((s for s in _CURRENCIES if s in section), None)
    if symbol:
        magnitude = f"{abs(number):,.{decimals}f}" if grouping else f"{abs(number):.{decimals}f}"
        sign = "-" if number < 0 else ""
        return CellValue(
            kind="currency", number=number, currency=_CURRENCIES[symbol], text=f"{sign}{symbol}{magnitude}"
        )
    if fmt.lower() == "general":
        text = str(int(value)) if number == number.to_integral_value() else repr(value)
    else:
        text = f"{number:,.{decimals}f}" if grouping else f"{number:.{decimals}f}"
    return CellValue(kind="number", number=number, text=text)


def _value(value: object, fmt: str) -> CellValue:
    if isinstance(value, bool):
        return CellValue(kind="text", text="TRUE" if value else "FALSE")
    if isinstance(value, datetime):
        value = value.date()
    if isinstance(value, Date):
        return CellValue(kind="date", date=value, text=value.isoformat())
    if isinstance(value, int | float):
        return _numeric(value, fmt)
    return parse_text_value(str(value))


def _sheet_cells(sheet: str, values: dict[tuple[int, int], CellValue]) -> list[TableCell]:
    if not values:
        return []
    header_row = min(row for row, _ in values)
    label_column = min(column for _, column in values)
    cells = []
    for (row, column), value in sorted(values.items()):
        if row == header_row or (column == label_column and value.kind == "text"):
            continue
        header = values.get((header_row, column))
        label = values.get((row, label_column))
        cell = f"{get_column_letter(column)}{row}"
        cells.append(
            TableCell(
                sheet=sheet,
                cell=cell,
                locator=sheet_locator(sheet, cell),
                header=header.text if header else None,
                label=label.text if label and label.kind == "text" else None,
                value=value,
            )
        )
    return cells


def _xlsx(path: Path) -> list[TableCell]:
    book = openpyxl.load_workbook(path, data_only=True)
    try:
        result = []
        for sheet in book.worksheets:
            values = {
                (cell.row, cell.column): _value(cell.value, cell.number_format)
                for row in sheet.iter_rows()
                for cell in row
                if cell.value is not None
            }
            result.extend(_sheet_cells(sheet.title, values))
        return result
    finally:
        book.close()


def _csv(path: Path) -> list[TableCell]:
    with path.open(encoding="utf-8-sig", newline="") as handle:
        values = {
            (row, column): parse_text_value(value)
            for row, line in enumerate(csv.reader(handle), 1)
            for column, value in enumerate(line, 1)
            if value.strip()
        }
    return _sheet_cells(path.stem, values)


def read_cells(path: Path) -> list[TableCell]:
    try:
        if path.suffix.lower() == ".xlsx":
            return _xlsx(path)
        if path.suffix.lower() == ".csv":
            return _csv(path)
        raise ValueError("Unsupported table format")
    except Exception as error:
        raise TableError(f"Cannot read table {path.name}: {error}") from error


def table_facts(path: Path, source_key: str) -> list[Fact]:
    facts = []
    for cell in read_cells(path):
        prefix = ", ".join(part for part in (cell.label, cell.header) if part is not None)
        text = f"{prefix}: {cell.value.text}" if prefix else cell.value.text
        facts.append(
            Fact(
                text=text,
                source_key=source_key,
                locator=cell.locator,
                kind=cell.value.kind,
                value=cell.value.number,
                unit="%" if cell.value.kind == "percent" else cell.value.currency,
            )
        )
    return facts
