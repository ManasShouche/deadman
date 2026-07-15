from deadman.detectors import detect_hung_process
from deadman.domain import DetectorConfig, ProcessObservation, SignalKind


def _observation(**overrides: object) -> ProcessObservation:
    values = {
        "evidence_id": "proc_001",
        "root_pid": 100,
        "pid": 101,
        "parent_pid": 100,
        "command_line": ("sleep", "999"),
        "is_running": True,
        "is_descendant": True,
        "observed_at": 0.0,
        "last_stdout_at": 10.0,
        "last_stderr_at": None,
        "listening_ports": (),
        "ready_pattern_matched": False,
    }
    values.update(overrides)
    return ProcessObservation.model_validate(values)


def test_detect_hung_process_emits_signal_for_owned_idle_descendant() -> None:
    signal = detect_hung_process(
        [_observation()],
        now=75.0,
        config=DetectorConfig(hung_timeout_seconds=60.0),
    )

    assert signal is not None
    assert signal.kind == SignalKind.HUNG_PROCESS
    assert signal.evidence_ids == ("proc_001",)
    assert signal.details["pid"] == 101
    assert signal.details["idle_seconds"] == 65.0


def test_detect_hung_process_waits_until_timeout() -> None:
    signal = detect_hung_process(
        [_observation(last_stdout_at=50.0)],
        now=75.0,
        config=DetectorConfig(hung_timeout_seconds=60.0),
    )

    assert signal is None


def test_detect_hung_process_ignores_unowned_or_persistent_processes() -> None:
    config = DetectorConfig(hung_timeout_seconds=60.0)

    assert (
        detect_hung_process([_observation(is_descendant=False)], now=100.0, config=config)
        is None
    )
    assert detect_hung_process([_observation(is_running=False)], now=100.0, config=config) is None
    assert (
        detect_hung_process([_observation(listening_ports=(8000,))], now=100.0, config=config)
        is None
    )
    assert (
        detect_hung_process(
            [_observation(ready_pattern_matched=True)],
            now=100.0,
            config=config,
        )
        is None
    )
