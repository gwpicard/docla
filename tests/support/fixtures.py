from pathlib import Path

SIDES = ("fail", "pass")


def fixtures_root() -> Path:
    return Path(__file__).resolve().parents[1] / "fixtures"


def fixture_path(*parts: str) -> Path:
    path = fixtures_root().joinpath(*parts)
    if not path.exists():
        raise FileNotFoundError(f"fixture not found: {path}")
    return path


def missing_pairs(root: Path | None = None) -> list[str]:
    base = Path(root) if root is not None else fixtures_root() / "seeded-defects"
    if not base.is_dir():
        return []
    missing = [
        f"{rule.name}/{side}"
        for rule in base.iterdir()
        if rule.is_dir()
        for side in SIDES
        if not (rule / side).is_dir()
    ]
    return sorted(missing)
