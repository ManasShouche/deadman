import os
from pathlib import Path

import pytest

from deadman.config import load_openai_credentials


def test_load_openai_credentials_reads_project_env(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "")
    (tmp_path / ".env").write_text("OPENAI_API_KEY=sk-project-test\n", encoding="utf-8")

    status = load_openai_credentials(tmp_path)

    assert status.available is True
    assert status.source == "project .env"
    assert status.env_file == str(tmp_path / ".env")


def test_load_openai_credentials_does_not_override_environment(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "sk-environment-test")
    (tmp_path / ".env").write_text("OPENAI_API_KEY=sk-project-test\n", encoding="utf-8")

    status = load_openai_credentials(tmp_path)

    assert status.source == "environment"
    assert status.available is True
    assert os.environ["OPENAI_API_KEY"] == "sk-environment-test"
