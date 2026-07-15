"""Pure HUNG_PROCESS detector."""

from __future__ import annotations

import hashlib
from collections.abc import Iterable

from deadman.domain import DetectorConfig, ProcessObservation, Severity, Signal, SignalKind


def detect_hung_process(
    observations: Iterable[ProcessObservation],
    *,
    now: float,
    config: DetectorConfig | None = None,
) -> Signal | None:
    """Detect an owned child process with no output activity for the timeout."""

    threshold = (config or DetectorConfig()).hung_timeout_seconds
    for observation in observations:
        if not _eligible(observation):
            continue

        last_activity = _last_activity_at(observation)
        idle_seconds = now - last_activity
        if idle_seconds < threshold:
            continue

        return Signal(
            kind=SignalKind.HUNG_PROCESS,
            severity=Severity.CRITICAL,
            evidence_ids=(observation.evidence_id,),
            fingerprint=_fingerprint(observation),
            details={
                "pid": observation.pid,
                "root_pid": observation.root_pid,
                "idle_seconds": idle_seconds,
                "timeout_seconds": threshold,
            },
        )

    return None


def _eligible(observation: ProcessObservation) -> bool:
    return (
        observation.is_running
        and observation.is_descendant
        and not observation.ready_pattern_matched
        and not observation.listening_ports
    )


def _last_activity_at(observation: ProcessObservation) -> float:
    activity_times = [
        timestamp
        for timestamp in (observation.last_stdout_at, observation.last_stderr_at)
        if timestamp is not None
    ]
    if not activity_times:
        return observation.observed_at
    return max(activity_times)


def _fingerprint(observation: ProcessObservation) -> str:
    command = "\x00".join(observation.command_line)
    digest = hashlib.sha256(
        f"{observation.root_pid}:{observation.pid}:{command}".encode("utf-8")
    ).hexdigest()
    return f"HUNG_PROCESS:{digest[:16]}"
