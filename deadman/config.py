"""Local credential discovery without reading Codex authentication state."""

from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv
from pydantic import BaseModel, ConfigDict


class OpenAICredentialStatus(BaseModel):
    """Whether live diagnosis can initialize and where its key came from."""

    model_config = ConfigDict(frozen=True)

    available: bool
    source: str
    env_file: str


def load_openai_credentials(workspace: Path) -> OpenAICredentialStatus:
    """Load only the current repository's .env without overriding the shell."""

    env_file = workspace.resolve() / ".env"
    existing = bool(os.environ.get("OPENAI_API_KEY", "").strip())
    if not existing and env_file.is_file():
        os.environ.pop("OPENAI_API_KEY", None)
        load_dotenv(dotenv_path=env_file, override=False)

    available = bool(os.environ.get("OPENAI_API_KEY", "").strip())
    if existing:
        source = "environment"
    elif available:
        source = "project .env"
    else:
        source = "not configured"
    return OpenAICredentialStatus(
        available=available,
        source=source,
        env_file=str(env_file),
    )
