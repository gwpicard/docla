from pathlib import Path
from typing import Any, Literal

import yaml  # type: ignore[import-untyped]
from pydantic import BaseModel, Field, ValidationError, field_validator

from docla.render.kit import components_dir


class ManifestError(ValueError):
    """A component manifest is missing, malformed or does not match its component."""


class ComponentManifest(BaseModel):
    name: str
    format: Literal["slides", "doc"]
    label: str
    intents: list[str] = Field(min_length=1)
    capacity: dict[str, tuple[int, int]]
    elements: list[str] = Field(min_length=1)

    @field_validator("label")
    @classmethod
    def _label_not_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("label must not be blank")
        return value

    @field_validator("capacity")
    @classmethod
    def _ranges_ordered(cls, value: dict[str, tuple[int, int]]) -> dict[str, tuple[int, int]]:
        for measure, (low, high) in value.items():
            if low > high:
                raise ValueError(f"capacity {measure} has min {low} above max {high}")
        return value

    def capacity_text(self) -> str:
        """Return the capacity as one line, measures sorted with `_` after letters."""
        measures = sorted(self.capacity, key=_measure_key)
        return "; ".join(f"{m} {self.capacity[m][0]} to {self.capacity[m][1]}" for m in measures)


def _measure_key(measure: str) -> str:
    return measure.replace("_", "~")


def load_manifests(folder: Path | None = None) -> dict[str, ComponentManifest]:
    """Read the manifest beside each component in folder (default the package components)."""
    root = components_dir() if folder is None else folder
    _check_pairs(root)
    manifests = {}
    for path in sorted(root.glob("*.yaml")):
        manifests[path.stem] = _read_manifest(path)
    return manifests


def _check_pairs(root: Path) -> None:
    typ = {path.stem for path in root.glob("*.typ")}
    manifest = {path.stem for path in root.glob("*.yaml")}
    if typ - manifest:
        stem = min(typ - manifest)
        raise ManifestError(f"{stem}.typ: component has no manifest {stem}.yaml")
    if manifest - typ:
        stem = min(manifest - typ)
        raise ManifestError(f"{stem}.yaml: manifest has no component {stem}.typ")


def _read_manifest(path: Path) -> ComponentManifest:
    try:
        data: Any = yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as error:
        raise ManifestError(f"{path.name}: not valid YAML: {error}") from error
    try:
        manifest = ComponentManifest.model_validate(data)
    except ValidationError as error:
        raise ManifestError(f"{path.name}: not valid: {error}") from error
    if manifest.name != path.stem:
        raise ManifestError(f"{path.name}: name {manifest.name!r} differs from the file stem {path.stem!r}")
    return manifest
