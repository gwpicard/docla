"""Git operations confined to a brand workspace."""

import os
import subprocess
from pathlib import Path


class GitError(RuntimeError):
    """A brand git command failed."""


def run_git(repo: Path, *args: str) -> str:
    repo = repo.resolve()
    env = {key: value for key, value in os.environ.items() if not key.startswith("GIT_")}
    env.update(
        GIT_DIR=str(repo / ".git"),
        GIT_WORK_TREE=str(repo),
        GIT_CEILING_DIRECTORIES=str(repo.parent),
        GIT_CONFIG_NOSYSTEM="1",
        GIT_TERMINAL_PROMPT="0",
        GIT_MERGE_AUTOEDIT="no",
    )
    command = [
        "git",
        "-c",
        "user.name=docla",
        "-c",
        "user.email=docla@localhost",
        "-c",
        "commit.gpgsign=false",
        "-c",
        f"core.hooksPath={repo / '.git' / 'no-hooks'}",
        *args,
    ]
    try:
        return subprocess.run(command, cwd=repo, env=env, text=True, capture_output=True, check=True).stdout
    except subprocess.CalledProcessError as error:
        raise GitError(f"{' '.join(command)}: {error.stderr.strip()}") from error


def init_repo(repo: Path) -> None:
    run_git(repo, "init", "-b", "main")
