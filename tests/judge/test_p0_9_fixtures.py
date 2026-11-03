# Intent: every seeded-defect rule needs a failing and a passing fixture, and incomplete pairs are reported.
import subprocess
import sys
from pathlib import Path

import pytest

try:
    from support import fixtures
except ImportError as error:
    if error.name != "support" and not str(error.name).startswith("support."):
        raise
    fixtures = None

REPO = Path(__file__).resolve().parents[2]
FIXTURES = REPO / "tests" / "fixtures"


def _require() -> None:
    assert fixtures is not None, "tests/support/fixtures.py must exist and be importable as support.fixtures"
    for name in ("fixtures_root", "fixture_path", "missing_pairs"):
        assert hasattr(fixtures, name), f"support.fixtures.{name} must exist"


@pytest.mark.parametrize("folder", ["slides", "doc", "seeded-defects"])
def test_D1_fixture_folders_have_readme(folder):
    path = FIXTURES / folder
    assert path.is_dir(), f"{path} must be a folder"
    readme = path / "README.md"
    assert readme.is_file(), f"{readme} must exist"
    assert readme.read_text().strip() != "", "README.md must state what goes in the folder"


def test_D2_fixture_path_returns_existing_folder():
    _require()
    assert Path(fixtures.fixture_path("slides")).resolve() == (FIXTURES / "slides").resolve()
    assert Path(fixtures.fixture_path("seeded-defects", "README.md")).resolve() == (
        FIXTURES / "seeded-defects" / "README.md"
    ).resolve()


def test_D2_fixture_path_missing_raises_naming_path():
    _require()
    with pytest.raises(FileNotFoundError) as excinfo:
        fixtures.fixture_path("nope")
    assert "nope" in str(excinfo.value)


def test_D2_fixtures_root_is_tests_fixtures():
    _require()
    assert Path(fixtures.fixtures_root()).resolve() == FIXTURES.resolve()


def test_D3_missing_pairs_reports_rule_without_fail(tmp_path):
    _require()
    (tmp_path / "a" / "pass").mkdir(parents=True)
    (tmp_path / "a" / "fail").mkdir()
    (tmp_path / "b" / "pass").mkdir(parents=True)
    assert fixtures.missing_pairs(tmp_path) == ["b/fail"]


def test_D3_missing_pairs_sorted_and_covers_both_sides(tmp_path):
    _require()
    (tmp_path / "z" / "pass").mkdir(parents=True)
    (tmp_path / "b" / "fail").mkdir(parents=True)
    (tmp_path / "c").mkdir()
    (tmp_path / "ok" / "pass").mkdir(parents=True)
    (tmp_path / "ok" / "fail").mkdir()
    assert fixtures.missing_pairs(tmp_path) == ["b/pass", "c/fail", "c/pass", "z/fail"]


def test_D3_complete_pairs_give_empty_list(tmp_path):
    _require()
    for rule in ("a", "b"):
        (tmp_path / rule / "pass").mkdir(parents=True)
        (tmp_path / rule / "fail").mkdir()
    assert fixtures.missing_pairs(tmp_path) == []


def test_D4_empty_root_gives_empty_list(tmp_path):
    _require()
    assert fixtures.missing_pairs(tmp_path) == []


def test_D4_missing_root_gives_empty_list(tmp_path):
    _require()
    assert fixtures.missing_pairs(tmp_path / "does-not-exist") == []


def test_D5_standing_test_exists_and_passes():
    standing = REPO / "tests" / "test_fixture_pairs.py"
    assert standing.is_file(), "tests/test_fixture_pairs.py must exist"
    result = subprocess.run(
        [sys.executable, "-m", "pytest", str(standing), "-q", "-p", "no:cacheprovider"],
        cwd=REPO,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "passed" in result.stdout
