"""Install the pinned Typst release into a folder, checking the archive's sha256 digest first."""

import argparse
import hashlib
import platform
import sys
import tarfile
import tempfile
import urllib.request
from pathlib import Path

VERSION = "0.15.1"
ASSETS: dict[str, tuple[str, str]] = {
    "linux-x86_64": (
        "typst-x86_64-unknown-linux-musl.tar.xz",
        "a6d077d0a95eed5a2eba715b2dae06be954f624ccbf85758a03f389ded33118c",
    ),
    "macos-arm64": (
        "typst-aarch64-apple-darwin.tar.xz",
        "48f62ed034aa3a7978309579ac6ca00045e2ef0da73114e8af27cfd8e74dc05a",
    ),
}
RELEASE_URL = f"https://github.com/typst/typst/releases/download/v{VERSION}/"
SUFFIX = ".tar.xz"


def sha256_of(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 16), b""):
            digest.update(chunk)
    return digest.hexdigest()


def read_executable(archive: Path) -> bytes:
    """Return the bytes of the `<asset stem>/typst` member of the archive."""
    with tarfile.open(archive, "r:xz") as tar:
        for member in tar.getmembers():
            parts = member.name.split("/")
            if member.isfile() and len(parts) == 2 and parts[1] == "typst":
                handle = tar.extractfile(member)
                if handle is not None:
                    return handle.read()
    raise ValueError(f"{archive} holds no <asset stem>/typst file")


def install(archive: Path, dest: Path, sha256: str) -> Path:
    """Check the archive's digest, then write its typst executable to dest/typst."""
    found = sha256_of(archive)
    if found != sha256:
        raise ValueError(f"sha256 mismatch for {archive}: expected {sha256}, found {found}")
    payload = read_executable(archive)
    dest.mkdir(parents=True, exist_ok=True)
    target = dest / "typst"
    target.write_bytes(payload)
    target.chmod(0o755)
    return dest


def detect_platform() -> str:
    system = {"Linux": "linux", "Darwin": "macos"}.get(platform.system(), platform.system().lower())
    machine = {"aarch64": "arm64", "AMD64": "x86_64"}.get(platform.machine(), platform.machine())
    return f"{system}-{machine}"


def download(asset: str, folder: Path) -> Path:
    archive = folder / asset
    with urllib.request.urlopen(RELEASE_URL + asset) as response, archive.open("wb") as handle:
        while chunk := response.read(1 << 16):
            handle.write(chunk)
    return archive


def run(key: str, dest: Path, archive: Path | None) -> Path:
    asset, sha256 = ASSETS[key]
    if archive is not None:
        return install(archive, dest, sha256)
    with tempfile.TemporaryDirectory() as folder:
        return install(download(asset, Path(folder)), dest, sha256)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=f"Install Typst {VERSION}.")
    parser.add_argument("--dest", type=Path, required=True)
    parser.add_argument("--platform", default=None)
    parser.add_argument("--archive", type=Path, default=None)
    args = parser.parse_args(argv)
    key = args.platform or detect_platform()
    if key not in ASSETS:
        print(f"unsupported platform {key}; supported: {', '.join(sorted(ASSETS))}", file=sys.stderr)
        return 2
    try:
        dest = run(key, args.dest, args.archive)
    except (OSError, ValueError, tarfile.TarError) as error:
        print(error, file=sys.stderr)
        return 1
    print(dest)
    return 0


if __name__ == "__main__":
    sys.exit(main())
