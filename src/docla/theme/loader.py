from pathlib import Path
from typing import Any

import yaml  # type: ignore[import-untyped]
from pydantic import BaseModel, ValidationError

from docla.theme.models import Theme, ThemeInfo, Tokens

LICENCES = "LICENSES.txt"


class ThemeError(ValueError):
    """A theme on disk is missing, malformed or inconsistent."""


def load_theme(root: Path) -> Theme:
    """Read theme.yaml and tokens.yaml under root, check them against each other and the fonts folder."""
    tokens = _read_model(root / "tokens.yaml", Tokens)
    info = _read_model(root / "theme.yaml", ThemeInfo)
    _check_usage(tokens)
    _check_families(tokens)
    _check_formats(info, tokens)
    theme = Theme(root=root, info=info, tokens=tokens)
    _check_fonts(theme)
    if info.labelled:
        from docla.theme.labels import check_token_labels

        check_token_labels(theme)
    return theme


def _read_model[M: BaseModel](path: Path, model: type[M]) -> M:
    if not path.is_file():
        raise ThemeError(f"{path.name}: file is missing from {path.parent}")
    try:
        data: Any = yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as error:
        raise ThemeError(f"{path.name}: not valid YAML: {error}") from error
    try:
        return model.model_validate(data)
    except ValidationError as error:
        raise ThemeError(f"{path.name}: not valid: {error}") from error


def _check_usage(tokens: Tokens) -> None:
    roles = tokens.colour.roles
    for use, names in tokens.colour.usage.items():
        for name in names:
            if name not in roles:
                raise ThemeError(f"tokens.yaml: colour.usage.{use} names unknown colour role {name!r}")


def _check_families(tokens: Tokens) -> None:
    families = tokens.type.families
    for fmt, scale in tokens.type.scale.items():
        for role_name, role in scale.roles.items():
            if role.family not in families:
                raise ThemeError(f"tokens.yaml: type.scale.{fmt}.{role_name} names unknown family {role.family!r}")


def _check_formats(info: ThemeInfo, tokens: Tokens) -> None:
    for fmt in info.formats:
        if fmt not in tokens.pages:
            raise ThemeError(f"tokens.yaml: format {fmt!r} from theme.yaml has no pages entry")
        if fmt not in tokens.type.scale:
            raise ThemeError(f"tokens.yaml: format {fmt!r} from theme.yaml has no type.scale entry")


def _check_fonts(theme: Theme) -> None:
    recorded = _licensed_files(theme.fonts_dir / LICENCES)
    for family in theme.tokens.type.families.values():
        for name in family.files:
            if not (theme.fonts_dir / name).is_file():
                raise ThemeError(f"tokens.yaml: font file {name!r} of {family.name} is missing from fonts/")
            if name not in recorded:
                raise ThemeError(f"fonts/{LICENCES}: font file {name!r} has no 'file: {name}' licence record")


def _licensed_files(path: Path) -> set[str]:
    if not path.is_file():
        return set()
    files = set()
    for line in path.read_text(encoding="utf-8").splitlines():
        key, _, value = line.partition(":")
        if key.strip() == "file" and value.strip():
            files.add(value.strip())
    return files
