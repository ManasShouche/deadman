from pathlib import Path

from rich.console import Console

from deadman.detectors.replay import replay_fixture
from deadman.ui import render_demo_dashboard, render_replay_result


def test_render_demo_dashboard_contains_scenario_names() -> None:
    incidents = [
        replay_fixture(path)
        for path in (
            Path("scenarios/recordings/hung-process.jsonl"),
            Path("scenarios/recordings/repeated-failure.jsonl"),
            Path("scenarios/recordings/session-handoff.jsonl"),
        )
    ]
    console = Console(record=True, width=120)

    console.print(
        render_demo_dashboard([incident for incident in incidents if incident is not None])
    )
    rendered = console.export_text()

    assert "Deadman demo" in rendered
    assert "hung-process" in rendered
    assert "session-handoff" in rendered


def test_render_replay_result_has_title() -> None:
    incident = replay_fixture(Path("scenarios/recordings/hung-process.jsonl"))
    console = Console(record=True, width=100)

    assert incident is not None
    console.print(render_replay_result(incident))
    rendered = console.export_text()
    assert "Deadman replay" in rendered
    assert "HUNG_PROCESS" in rendered
