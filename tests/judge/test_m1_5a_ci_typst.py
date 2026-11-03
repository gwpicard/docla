# Intent: CI installs the pinned Typst 0.15.1 on both runners via scripts/install_typst.py, checking the digest.
import importlib.util
import io
import re
import stat
import tarfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "install_typst.py"
WORKFLOW = ROOT / ".github" / "workflows" / "ci.yml"

INSTALL_LINE = 'uv run python scripts/install_typst.py --dest "$RUNNER_TEMP/typst" >> "$GITHUB_PATH"'

LINUX = (
    "typst-x86_64-unknown-linux-musl.tar.xz",
    "a6d077d0a95eed5a2eba715b2dae06be954f624ccbf85758a03f389ded33118c",
)
MACOS = (
    "typst-aarch64-apple-darwin.tar.xz",
    "48f62ed034aa3a7978309579ac6ca00045e2ef0da73114e8af27cfd8e74dc05a",
)


def _load():
    if not SCRIPT.is_file():
        return None
    spec = importlib.util.spec_from_file_location("install_typst_under_test", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


install_typst = _load()


def _subject():
    assert install_typst is not None, "scripts/install_typst.py must exist"
    return install_typst


def _make_archive(path: Path, asset: str, payload: bytes) -> str:
    import hashlib

    stem = asset[: -len(".tar.xz")]
    with tarfile.open(path, "w:xz") as tar:
        info = tarfile.TarInfo(f"{stem}/typst")
        info.size = len(payload)
        info.mode = 0o644
        tar.addfile(info, io.BytesIO(payload))
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _jobs() -> dict[str, list[str]]:
    assert WORKFLOW.is_file(), ".github/workflows/ci.yml must exist"
    lines = WORKFLOW.read_text(encoding="utf-8").splitlines()
    start = next((i for i, line in enumerate(lines) if re.fullmatch(r"jobs:\s*", line)), None)
    assert start is not None, "ci.yml must define jobs:"
    jobs: dict[str, list[str]] = {}
    current: list[str] | None = None
    for line in lines[start + 1 :]:
        header = re.fullmatch(r"  ([A-Za-z0-9_-]+):\s*", line)
        if header:
            current = jobs.setdefault(header.group(1), [])
        elif current is not None:
            current.append(line)
    return jobs


def _runs(job: list[str]) -> list[str]:
    return [m.group(1).strip() for line in job if (m := re.match(r"\s*-?\s*run:\s*(.*)$", line))]


def test_D1_checks_job_installs_typst_between_sync_and_pytest():
    runs = _runs(_jobs()["checks"])
    assert INSTALL_LINE in runs
    assert runs.index("uv sync") < runs.index(INSTALL_LINE) < runs.index("uv run python -m pytest")
    assert runs.count(INSTALL_LINE) == 1


def test_D1_no_other_job_installs_typst():
    for name, job in _jobs().items():
        if name != "checks":
            assert not any("install_typst" in line for line in job), name


def test_D2_version_and_assets_are_pinned():
    module = _subject()
    assert module.VERSION == "0.15.1"
    assert module.ASSETS == {
        "linux-x86_64": LINUX,
        "macos-arm64": MACOS,
    }


def test_D3_install_rejects_digest_mismatch(tmp_path):
    module = _subject()
    archive = tmp_path / "a.tar.xz"
    found = _make_archive(archive, LINUX[0], b"binary")
    expected = "0" * 64
    dest = tmp_path / "out"
    with pytest.raises(ValueError) as caught:
        module.install(archive, dest, expected)
    assert expected in str(caught.value)
    assert found in str(caught.value)
    assert not (dest / "typst").exists()


def test_D3_main_rejects_mismatched_archive(tmp_path, capsys):
    module = _subject()
    archive = tmp_path / "a.tar.xz"
    _make_archive(archive, LINUX[0], b"binary")
    dest = tmp_path / "out"
    code = module.main(["--dest", str(dest), "--platform", "linux-x86_64", "--archive", str(archive)])
    captured = capsys.readouterr()
    assert code != 0
    assert captured.out == ""
    assert captured.err != ""
    assert not (dest / "typst").exists()


def test_D4_install_extracts_executable(tmp_path):
    module = _subject()
    archive = tmp_path / "a.tar.xz"
    digest = _make_archive(archive, MACOS[0], b"#!/bin/sh\necho typst\n")
    dest = tmp_path / "out"
    dest.mkdir()
    result = module.install(archive, dest, digest)
    assert Path(result) == dest
    target = dest / "typst"
    assert target.read_bytes() == b"#!/bin/sh\necho typst\n"
    assert target.stat().st_mode & stat.S_IXUSR


def test_D5_main_rejects_unknown_platform(tmp_path, capsys):
    module = _subject()
    archive = tmp_path / "a.tar.xz"
    _make_archive(archive, LINUX[0], b"binary")
    code = module.main(["--dest", str(tmp_path / "out"), "--platform", "windows-x86_64", "--archive", str(archive)])
    captured = capsys.readouterr()
    assert code != 0
    assert captured.out == ""
    assert "linux-x86_64" in captured.err
    assert "macos-arm64" in captured.err
