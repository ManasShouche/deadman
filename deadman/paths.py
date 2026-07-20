"""Path helpers shared by CLI entry points."""

from __future__ import annotations

from pathlib import Path


def project_root(path: Path) -> Path:
    """Return the nearest Git root, falling back to the resolved path."""

    current = path.resolve()
    if current.is_file():
        current = current.parent
    for candidate in (current, *current.parents):
        if (candidate / ".git").exists():
            return candidate
    return current


def default_database_path(path: Path) -> Path:
    """Return Deadman's default SQLite path for a workspace."""

    return project_root(path) / ".deadman" / "deadman.sqlite"
