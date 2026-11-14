"""Synthesise labelled theme tokens from reconciled brand evidence."""

import re
from collections import Counter
from pathlib import Path
from typing import Any

import yaml  # type: ignore[import-untyped]
from pydantic import BaseModel

from docla.brand.fonts import FontReport
from docla.brand.questions import (
    BrandQuestion,
    QuestionOption,
    SetToken,
    add_questions,
    drop_open_questions,
    open_questions,
)
from docla.brand.reconcile import load_reconciliation
from docla.brand.tokenmap import path_format
from docla.brand.workspace import BrandError
from docla.model.rules import ValueLabel
from docla.theme import ThemeError, load_theme, neutral_theme
from docla.theme.labels import token_paths

MUST_COME_FROM_BRAND = [f"colour.roles.{r}" for r in ("accent", "ink", "surface")] + [
    p
    for f in ("slides", "doc")
    for p in (
        f"type.scale.{f}.body.size",
        f"pages.{f}.width",
        f"pages.{f}.height",
        *(f"pages.{f}.margin.{s}" for s in ("top", "right", "bottom", "left")),
    )
]


class TokenSynthesis(BaseModel):
    labels: dict[ValueLabel, int]
    questions: list[str]
    inferred: list[str]


def mix(a: str, b: str, t: float) -> str:
    return "#" + "".join(f"{round(t * int(a[i : i + 2], 16) + (1 - t) * int(b[i : i + 2], 16)):02X}" for i in (1, 3, 5))


def _get(data: dict[str, Any], path: str) -> Any:
    for part in path.split("."):
        data = data[part]
    return data


def _set(data: dict[str, Any], path: str, value: Any) -> None:
    parts = path.split(".")
    for part in parts[:-1]:
        data = data.setdefault(part, {})
    data[parts[-1]] = value


def _neutral() -> dict[str, Any]:
    theme = neutral_theme()
    raw = yaml.safe_load((theme.root / "tokens.yaml").read_text())
    for fmt in ("slides", "doc"):
        page = theme.tokens.pages[fmt]
        raw["pages"][fmt] = {"width": page.width, "height": page.height, "margin": page.margin.model_dump()}
        if fmt == "doc":
            raw["pages"][fmt].update(columns=page.columns, gutter=page.gutter)
    return raw


def _font_files(brand: Path, name: str) -> list[str]:
    path = brand / "theme/ingest/fonts.json"
    report = FontReport.model_validate_json(path.read_text()) if path.exists() else None
    files = next((v for k, v in report.typefaces.items() if k.casefold() == name.casefold()), []) if report else []
    if not files or any(not (brand / "theme/fonts" / f).is_file() for f in files):
        qid = "font.missing." + re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")
        add_questions(
            brand, [BrandQuestion(id=qid, kind="font", text=f"Please supply the font files and licence for {name}.")]
        )
        raise BrandError(f"No checked font files for {name}: {qid}")
    return files


def synthesise_tokens(brand: Path) -> TokenSynthesis:
    reconciliation = load_reconciliation(brand)
    neutral = _neutral()
    data: dict[str, Any] = {"schema": 1, **{k: {} for k in ("colour", "type", "pages", "spacing", "imagery")}}
    entries: dict[str, Any] = {}
    theme = brand / "theme"
    token_file, prov_file, info_file = (theme / n for n in ("tokens.yaml", "provenance.yaml", "theme.yaml"))
    old_prov = yaml.safe_load(prov_file.read_text()) or {} if prov_file.exists() else {}
    if token_file.exists() and prov_file.exists():
        old_tokens = yaml.safe_load(token_file.read_text())
        for path, entry in old_prov.get("tokens", {}).items():
            if entry["label"] == "answered":
                _set(data, path, _get(old_tokens, path))
                entries[path] = entry

    def put(path: str, value: Any, label: str, source: dict[str, Any]) -> None:
        if path not in entries:
            _set(data, path, value)
            entries[path] = {"label": label, "source": source}

    def inferred(path: str, value: Any, note: str = "docla's neutral default") -> None:
        put(path, value, "inferred", {"note": note})

    def derived(path: str, value: Any, paths: list[str]) -> None:
        put(path, value, "derived", {"from": paths})

    for item in reconciliation.values:
        value = (
            item.value.upper() if item.path.startswith("colour.roles.") and isinstance(item.value, str) else item.value
        )
        put(item.path, value, "measured", item.provenance.source.model_dump(by_alias=True, exclude_defaults=True))
    text_path = "type.families.text.name"
    if text_path not in entries:
        raise BrandError("No text typeface is known")
    derived("type.families.display.name", _get(data, text_path), [text_path])
    for family in ("text", "display"):
        name = _get(data, f"type.families.{family}.name")
        files = _font_files(brand, name)
        put(
            f"type.families.{family}.files",
            files,
            "measured",
            {"files": [f"materials/fonts/{f}" for f in files], "role": "fonts"},
        )

    questions = []
    for path in MUST_COME_FROM_BRAND:
        if path not in entries:
            value = _get(neutral, path)
            inferred(path, value, "No source gives this value; docla's neutral value until answered")
            questions.append(
                BrandQuestion(
                    id="token." + path,
                    kind="token",
                    format=path_format(path),
                    text=f"What is {path.replace('.', ' ')}?",
                    recommended="a",
                    options=[
                        QuestionOption(
                            id="a", label=f"Use {value}", effects=[SetToken(kind="set-token", path=path, value=value)]
                        )
                    ],
                )
            )

    ink, surface = (_get(data, f"colour.roles.{r}") for r in ("ink", "surface"))
    for role, value in neutral["colour"]["roles"].items():
        path = f"colour.roles.{role}"
        if role in ("dark", "on-dark"):
            source = "ink" if role == "dark" else "surface"
            derived(path, _get(data, f"colour.roles.{source}"), [f"colour.roles.{source}"])
        elif role in ("ink-soft", "muted", "hairline", "surface-alt"):
            derived(
                path,
                mix(ink, surface, {"ink-soft": 0.75, "muted": 0.6, "hairline": 0.2, "surface-alt": 0.05}[role]),
                ["colour.roles.ink", "colour.roles.surface"],
            )
        else:
            inferred(path, value)
    for chart, roles in (
        ("sequence", ("ink", "ink-soft", "muted", "hairline")),
        ("categorical", ("accent", "ink", "ink-soft", "muted")),
    ):
        paths = [f"colour.roles.{r}" for r in roles]
        derived(f"colour.chart.{chart}", [_get(data, p) for p in paths], paths)
    for role, value in neutral["colour"]["usage"].items():
        inferred(f"colour.usage.{role}", value, "docla's default use of the roles")
    inferred("colour.contrast_min", 4.5, "WCAG AA")
    for fmt in ("slides", "doc"):
        scale = neutral["type"]["scale"][fmt]
        body_path = f"type.scale.{fmt}.body.size"
        sizes = []
        for role, values in scale.items():
            if role == "min_size":
                continue
            prefix = f"type.scale.{fmt}.{role}"
            size_path = prefix + ".size"
            derived(
                size_path, round(2 * _get(data, body_path) * values["size"] / scale["body"]["size"]) / 2, [body_path]
            )
            sizes.append(size_path)
            for key, value in values.items():
                if key != "size":
                    inferred(prefix + "." + key, value)
        derived(f"type.scale.{fmt}.min_size", min(_get(data, p) for p in sizes), sizes)
    for path in token_paths(neutral):
        if path.startswith(("pages.", "spacing.", "imagery.")):
            inferred(path, _get(neutral, path))
    add_questions(brand, questions)
    drop_open_questions(brand, ["token." + p for p in MUST_COME_FROM_BRAND if entries[p]["label"] != "inferred"])
    info = yaml.safe_load(info_file.read_text())
    info["labelled"] = True
    files = (token_file, prov_file, info_file)
    previous = [p.read_bytes() if p.exists() else None for p in files]
    provenance = {"tokens": dict(sorted(entries.items()))}
    if "rubric" in old_prov:
        provenance["rubric"] = old_prov["rubric"]
    for path, value in zip(files, (data, provenance, info), strict=True):
        path.write_text(yaml.safe_dump(value, sort_keys=False, allow_unicode=True))
    try:
        load_theme(theme)
    except ThemeError:
        for path, content in zip(files, previous, strict=True):
            if content is None:
                path.unlink(missing_ok=True)
            else:
                path.write_bytes(content)
        raise
    counts = Counter(entry["label"] for entry in entries.values())
    return TokenSynthesis(
        labels=dict(counts),
        questions=[q.id for q in open_questions(brand) if q.id.startswith("token.")],
        inferred=sorted(p for p, e in entries.items() if e["label"] == "inferred"),
    )
