"""Offline detector replay for recorded fixture events."""

from __future__ import annotations

import json
from pathlib import Path

from pydantic import ValidationError

from deadman.detectors import detect_hung_process
from deadman.domain import DetectorConfig, ProcessObservation, Signal


def replay_hung_process_fixture(path: Path, *, now: float | None = None) -> Signal | None:
    """Replay process observations from a fixture and return the first hung signal."""

    observations = _load_process_observations(path)
    if not observations:
        return None

    replay_now = _default_replay_now(observations) if now is None else now
    return detect_hung_process(
        observations,
        now=replay_now,
        config=DetectorConfig(),
    )


def _load_process_observations(path: Path) -> list[ProcessObservation]:
    observations: list[ProcessObservation] = []
    for line in path.read_text().splitlines():
        if not line.strip():
            continue
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(event, dict) or event.get("type") != "process.observed":
            continue
        try:
            observations.append(ProcessObservation.model_validate(event))
        except ValidationError:
            continue
    return observations


def _default_replay_now(observations: list[ProcessObservation]) -> float:
    latest_activity = max(_last_activity_at(observation) for observation in observations)
    return latest_activity + DetectorConfig().hung_timeout_seconds + 5.0


def _last_activity_at(observation: ProcessObservation) -> float:
    activity_times = [
        timestamp
        for timestamp in (observation.last_stdout_at, observation.last_stderr_at)
        if timestamp is not None
    ]
    if not activity_times:
        return observation.observed_at
    return max(activity_times)
