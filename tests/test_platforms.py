from pathlib import Path

import pytest

from deadman import agent
from deadman.platforms import supports_pty_supervision


def test_pty_capability_is_explicit() -> None:
    assert supports_pty_supervision("posix")
    assert not supports_pty_supervision("nt")


def test_agent_explains_windows_fallback(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(agent, "supports_pty_supervision", lambda: False)

    with pytest.raises(RuntimeError, match="use deadman attach"):
        agent.run_agent_cli(("codex",), workspace=tmp_path)
