"""Map brand material pages to components."""

from pathlib import Path

import yaml  # type: ignore[import-untyped]
from pydantic import BaseModel, Field

from docla.brand.changes import ChangeRecord, Evidence, begin_change, record_change
from docla.brand.intake import Manifest, MaterialEntry
from docla.brand.pages import load_manifest, load_pages
from docla.brand.workspace import BrandError
from docla.model.source import Format
from docla.render.components import all_manifests

ROLES = Path("theme/ingest/roles.yaml")
MAPPABLE = ("examples", "guidelines", "templates")


class RoleMapping(BaseModel):
    file: str
    page: int
    format: Format
    component: str
    sha256: str
    person: str
    note: str | None = None


class RoleMap(BaseModel):
    schema_version: int = 1
    mappings: list[RoleMapping] = Field(default_factory=list)


def load_roles(brand: Path) -> RoleMap:
    path = brand / ROLES
    if not path.exists():
        return RoleMap()
    result = RoleMap.model_validate(yaml.safe_load(path.read_text(encoding="utf-8")))
    result.mappings.sort(key=lambda item: (item.file, item.page))
    return result


def check_mapping(manifest: Manifest, file: str, page: int, component: str) -> MaterialEntry:
    entry = next((item for item in manifest.files if item.path == file), None)
    if entry is None:
        raise BrandError(f"File not in manifest: {file}")
    if entry.unread:
        raise BrandError(f"Unread file: {file}: {entry.unread}")
    if entry.role not in MAPPABLE:
        raise BrandError(f"Cannot map {entry.role}: {file}")
    if entry.format is None:
        raise BrandError(f"No format for {file}")
    if entry.pages is None or page < 1 or page > entry.pages:
        raise BrandError(f"Invalid page {page} for {file}")
    components = all_manifests()
    if component not in components:
        raise BrandError(f"Unknown component: {component}")
    if components[component].format != entry.format:
        raise BrandError(f"Component {component} has the wrong format for {file}")
    return entry


def _prepare(
    brand: Path,
    manifest: Manifest,
    mapped: list[tuple[str, int, str]],
    unmapped: list[tuple[str, int]],
    person: str,
    note: str | None,
) -> RoleMap:
    entries = [check_mapping(manifest, file, page, component) for file, page, component in mapped]
    current = {(item.file, item.page): item for item in load_roles(brand).mappings}
    for file, page in unmapped:
        if (file, page) not in current:
            raise BrandError(f"Page {page} of {file} is not mapped")
        del current[(file, page)]
    for (file, page, component), entry in zip(mapped, entries, strict=True):
        assert entry.format is not None
        current[(file, page)] = RoleMapping(
            file=file,
            page=page,
            format=entry.format,
            component=component,
            sha256=entry.sha256,
            person=person,
            note=note,
        )
    return RoleMap(mappings=sorted(current.values(), key=lambda item: (item.file, item.page)))


def set_roles(
    brand: Path,
    mapped: list[tuple[str, int, str]],
    unmapped: list[tuple[str, int]] | None = None,
    *,
    person: str = "owner",
    note: str | None = None,
) -> RoleMap:
    result = _prepare(brand, load_manifest(brand), mapped, unmapped or [], person, note)
    path = brand / ROLES
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(result.model_dump(mode="json"), sort_keys=False), encoding="utf-8")
    return result


def examples_for(brand: Path, component: str) -> list[RoleMapping]:
    return [item for item in load_roles(brand).mappings if item.component == component]


def page_png(brand: Path, file: str, page: int) -> Path:
    try:
        index = load_pages(brand)
    except BrandError as error:
        raise BrandError(f"No image for {file} page {page}; run docla brand parse") from error
    for entry in index.pages:
        if (entry.file, entry.page) == (file, page):
            return brand / entry.png
    raise BrandError(f"No image for {file} page {page}; run docla brand parse")


def stale_roles(brand: Path, manifest: Manifest) -> list[RoleMapping]:
    hashes = {entry.path: entry.sha256 for entry in manifest.files}
    return [item for item in load_roles(brand).mappings if hashes.get(item.file) != item.sha256]


def record_roles(
    brand: Path,
    mapped: list[tuple[str, int, str]],
    unmapped: list[tuple[str, int]] | None = None,
    *,
    person: str = "owner",
    note: str | None = None,
) -> ChangeRecord:
    manifest = load_manifest(brand)
    removed = unmapped or []
    _prepare(brand, manifest, mapped, removed, person, note)
    previous = {(item.file, item.page): item for item in load_roles(brand).mappings}
    formats = {check_mapping(manifest, file, page, component).format for file, page, component in mapped}
    formats.update(previous[key].format for key in removed)
    evidence = [Evidence(file=file, page=page, note=component) for file, page, component in mapped]
    evidence += [Evidence(file=file, page=page, note="unmapped") for file, page in removed]
    begin_change(brand, "roles")
    set_roles(brand, mapped, removed, person=person, note=note)
    return record_change(
        brand,
        what="Map example pages to components",
        why="Each component's look cites the brand pages it came from",
        evidence=evidence,
        before=[],
        after=[],
        formats=sorted(fmt for fmt in formats if fmt is not None),
        person=person,
    )
