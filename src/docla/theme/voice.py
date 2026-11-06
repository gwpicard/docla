from pydantic import BaseModel

from docla.model.source import Format
from docla.theme.loader import _read_model
from docla.theme.models import Theme

VOICE_FILE = "voice/terminology.yaml"


class Term(BaseModel):
    preferred: str
    avoid: list[str]


class Voice(BaseModel):
    summary: dict[Format, str] = {}
    banned: list[str] = []
    terminology: list[Term] = []


def load_voice(theme: Theme) -> Voice:
    """Read the theme's voice/terminology.yaml, or give an empty Voice when the file is absent."""
    path = theme.root / VOICE_FILE
    if not path.is_file():
        return Voice()
    return _read_model(path, Voice)
