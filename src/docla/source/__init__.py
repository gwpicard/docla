from docla.source.parser import parse
from docla.source.serialiser import serialise

__all__ = ["parse", "serialise"]


def __getattr__(name: str):
    if name in {"RULES", "M2_RULES"}:
        from docla.checks import source

        return getattr(source, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
