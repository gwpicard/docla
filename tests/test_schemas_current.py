from pathlib import Path

from docla.model.brief import export_brief_schema
from docla.model.schema import export_schemas

COMMITTED = Path(__file__).resolve().parents[1] / "docs" / "schemas"


def test_committed_schemas_match_fresh_export(tmp_path: Path) -> None:
    fresh = export_schemas(tmp_path)
    assert sorted(p.name for p in COMMITTED.glob("*.schema.json")) == [p.name for p in fresh]
    for path in fresh:
        assert (COMMITTED / path.name).read_bytes() == path.read_bytes(), path.name


def test_committed_brief_schema_matches_fresh_export(tmp_path: Path) -> None:
    fresh = export_brief_schema(tmp_path)
    assert (COMMITTED / "brief" / fresh.name).read_bytes() == fresh.read_bytes()
