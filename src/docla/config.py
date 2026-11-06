"""Project configuration and defaults."""

import tomllib
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field, ValidationError


class LoopConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    micro_attempts: int = 3
    best_of_n: int = 3
    macro_rounds: int = 2
    max_parallel_sections: int = 6
    act_on_uncorroborated: bool = False


class BudgetConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    max_usd_per_document: float = 5.0
    max_wall_seconds: int = 900
    warn_at_fraction: float = 0.7


class Price(BaseModel):
    model_config = ConfigDict(extra="forbid")

    input: float
    output: float
    cache_read: float = 0.0
    cache_write: float = 0.0


def _default_models() -> dict[str, str]:
    return {
        "writer": "claude-sonnet-5-5",
        "critic": "claude-opus-5-5",
        "diagnose": "claude-opus-5-5",
        "triage": "claude-haiku-4-5",
    }


class ProjectConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    loop: LoopConfig = Field(default_factory=LoopConfig)
    budget: BudgetConfig = Field(default_factory=BudgetConfig)
    models: dict[str, str] = Field(default_factory=_default_models)
    prices: dict[str, Price] = Field(default_factory=dict)


class ConfigError(Exception):
    """The project configuration is invalid."""


def load_project_config(directory: Path) -> ProjectConfig:
    path = directory / "docla.toml"
    if not path.exists():
        return ProjectConfig()
    try:
        with path.open("rb") as file:
            data = tomllib.load(file)
        if isinstance(data.get("models"), dict):
            data["models"] = _default_models() | data["models"]
        return ProjectConfig.model_validate(data)
    except (tomllib.TOMLDecodeError, ValidationError) as error:
        raise ConfigError(f"Invalid configuration in {path}: {error}") from error


def default_config_text() -> str:
    return """[loop]
micro_attempts = 3
best_of_n = 3
macro_rounds = 2
max_parallel_sections = 6
act_on_uncorroborated = false

[budget]
max_usd_per_document = 5.0
max_wall_seconds = 900
warn_at_fraction = 0.7

[models]
writer = "claude-sonnet-5-5"
critic = "claude-opus-5-5"
diagnose = "claude-opus-5-5"
triage = "claude-haiku-4-5"

# Prices are US dollars per million tokens and must be filled in before a live run.
[prices]
"""
