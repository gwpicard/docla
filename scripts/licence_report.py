"""Report the licence of every installed distribution and fail on AGPL."""

import sys
from importlib import metadata

MAX_LICENCE_FIELD = 100


def licence_of(meta) -> str:
    expression = meta.get("License-Expression")
    if expression:
        return expression.strip()
    field = (meta.get("License") or "").strip()
    if field and len(field) <= MAX_LICENCE_FIELD and "\n" not in field:
        return field
    for classifier in meta.get_all("Classifier") or []:
        if classifier.startswith("License ::"):
            return classifier.split("::")[-1].strip()
    return "unknown"


def is_agpl(licence: str) -> bool:
    text = licence.lower()
    return "agpl" in text or "affero" in text


def report(licences: dict[str, tuple[str, str]]) -> tuple[list[str], list[str]]:
    names = sorted(licences)
    lines = [f"{name} {licences[name][0]} {licences[name][1]}" for name in names]
    offenders = [name for name in names if is_agpl(licences[name][1])]
    return lines, offenders


def installed() -> dict[str, tuple[str, str]]:
    found: dict[str, tuple[str, str]] = {}
    for dist in metadata.distributions():
        name = dist.metadata.get("Name")
        if name and name not in found:
            found[name] = (dist.version or "unknown", licence_of(dist.metadata))
    return found


def main() -> int:
    lines, offenders = report(installed())
    for line in lines:
        print(line)
    for name in offenders:
        print(f"agpl: {name}")
    return 1 if offenders else 0


if __name__ == "__main__":
    sys.exit(main())
