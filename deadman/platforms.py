"""Small platform capability checks for optional live supervision features."""

from __future__ import annotations

import os


def supports_pty_supervision(platform_name: str | None = None) -> bool:
    """Return whether the standard-library PTY supervisor is available."""

    return (platform_name or os.name) == "posix"

