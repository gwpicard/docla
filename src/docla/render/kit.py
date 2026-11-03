from pathlib import Path


def lib_dir() -> Path:
    """Return the folder that holds the Typst kit, `marks.typ` and `theme.typ`."""
    return Path(__file__).parent / "lib"


def components_dir() -> Path:
    """Return the folder that holds the Typst slide components."""
    return Path(__file__).parent / "components"
