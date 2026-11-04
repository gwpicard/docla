import json
import tempfile
from pathlib import Path

from docla.render.typst import run_typst

TOKENS_SOURCE = '#import "/lib/theme.typ": tokens; #metadata(tokens) <docla-tokens>\n'
TOKENS_QUERY = "query(<docla-tokens>).first().value"


def lib_dir() -> Path:
    """Return the folder that holds the Typst kit, `marks.typ` and `theme.typ`."""
    return Path(__file__).parent / "lib"


def components_dir() -> Path:
    """Return the folder that holds the Typst slide components."""
    return Path(__file__).parent / "components"


def library_dir() -> Path:
    """Return the folder that holds additional Typst components."""
    return Path(__file__).parent / "library"


def read_tokens(root: Path) -> dict[str, str]:
    """Return the colour tokens of `root/lib/theme.typ`, each as upper-case `#RRGGBB`."""
    with tempfile.TemporaryDirectory(dir=root) as folder:
        source = Path(folder) / "tokens.typ"
        source.write_text(TOKENS_SOURCE)
        output = run_typst(["eval", TOKENS_QUERY, "--in", str(source)], root)
    return {name: str(value).upper() for name, value in json.loads(output).items()}
