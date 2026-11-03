# Intent: scanning tracked files for well-known secret shapes stops credentials reaching the repository.
import importlib.util
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
SCRIPT = REPO / "scripts" / "scan_secrets.py"

scan_secrets = None
if SCRIPT.exists():
    _spec = importlib.util.spec_from_file_location("scan_secrets", SCRIPT)
    scan_secrets = importlib.util.module_from_spec(_spec)
    _spec.loader.exec_module(scan_secrets)

# Built by concatenation so this file does not match its own patterns.
ANTHROPIC = "sk-ant-" + "abcdefghij0123456789_-XYZ"
AWS = "AKIA" + "ABCDEFGH01234567"
GITHUB = "ghp_" + "a1B2c3D4e5F6g7H8i9J0k1L2m3N4o5P6q7R8"
PEM = "-----BEGIN " + "RSA PRIVATE KEY-----"


def _require_interface():
    assert scan_secrets is not None, "scripts/scan_secrets.py must exist"
    assert hasattr(scan_secrets, "find_secrets"), "find_secrets must exist"


def test_D1_reports_each_kind_with_line_number():
    _require_interface()
    text = "\n".join(
        [
            "nothing here",
            f"key = {ANTHROPIC}",
            "filler",
            f"id: {AWS}",
            f"token={GITHUB}",
            PEM,
        ]
    )
    assert scan_secrets.find_secrets(text) == [
        (2, "anthropic-key"),
        (4, "aws-key-id"),
        (5, "github-token"),
        (6, "private-key"),
    ]


def test_D2_ordinary_text_yields_no_findings():
    _require_interface()
    text = "\n".join(
        [
            "Just some prose about keys.",
            "the word sk-ant alone",
            "short sk-ant-abc123 here",
            "AKIA" + "SHORT",
            "ghp_" + "tooshort",
            "-----BEGIN " + "CERTIFICATE-----",
        ]
    )
    assert scan_secrets.find_secrets(text) == []


def test_D3_allow_marker_skips_line():
    _require_interface()
    text = f"x = {ANTHROPIC}  # secret-scan: allow\ny = {AWS}"
    assert scan_secrets.find_secrets(text) == [(2, "aws-key-id")]


def _git(cwd, *args):
    subprocess.run(
        ["git", "-c", "user.name=t", "-c", "user.email=t@example.com", *args],
        cwd=cwd,
        check=True,
        capture_output=True,
    )


def test_D4_cli_exits_1_and_reports_location_without_secret(tmp_path):
    assert SCRIPT.exists(), "scripts/scan_secrets.py must exist"
    _git(tmp_path, "init")
    (tmp_path / "clean.txt").write_text("hello\n")
    (tmp_path / "leak.txt").write_text(f"first\nkey = {ANTHROPIC}\n")
    _git(tmp_path, "add", ".")
    _git(tmp_path, "commit", "-m", "init")
    result = subprocess.run([sys.executable, str(SCRIPT)], cwd=tmp_path, capture_output=True, text=True)
    output = result.stdout + result.stderr
    assert result.returncode == 1
    assert "leak.txt:2: anthropic-key" in output
    assert "clean.txt" not in output
    assert ANTHROPIC not in output
    assert "abcdefghij0123456789" not in output


def test_D5_cli_passes_on_this_repository():
    assert SCRIPT.exists(), "scripts/scan_secrets.py must exist"
    result = subprocess.run([sys.executable, str(SCRIPT)], cwd=REPO, capture_output=True, text=True)
    assert result.returncode == 0, result.stdout + result.stderr
