"""Offline detector replay for recorded fixture events."""

from __future__ import annotations

import json
from pathlib import Path
from typing import cast

from pydantic import ValidationError

from deadman.detectors import (
    detect_hung_process,
    detect_no_progress,
    detect_repeated_failure,
    detect_session_budget_risk,
)
from deadman.diagnosis import FakeDiagnosisClient
from deadman.domain import (
    AttemptObservation,
    DetectorConfig,
    ProcessObservation,
    ReplayIncident,
    Signal,
    UsageObservation,
)
from deadman.policy import PolicyEngine
from deadman.verify import verify_fixture_recovery


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


def replay_fixture(path: Path, *, auto_recover: bool = True) -> ReplayIncident | None:
    """Run the offline replay pipeline for one fixture file."""

    loaded = _load_fixture(path)
    signal = _detect_fixture_signal(loaded)
    if signal is None:
        return None

    diagnosis = FakeDiagnosisClient().diagnose(signal)
    policy = PolicyEngine(
        auto_recover=auto_recover,
        available_session_id=bool(loaded["session_id"]),
    ).evaluate(
        diagnosis,
        signal,
        action_fingerprint=f"action:{signal.fingerprint}",
        known_evidence_ids=signal.evidence_ids,
    )
    verification = verify_fixture_recovery(
        before_fingerprint=str(loaded["before_fingerprint"]),
        after_fingerprint=str(loaded["after_fingerprint"]),
        success_signal=cast(str | None, loaded["success_signal"]),
    )
    if not policy.allowed:
        verification = verification.model_copy(
            update={"resolved": False, "reason": f"policy blocked: {policy.reason}"}
        )

    return ReplayIncident(
        incident_id=path.stem,
        signal=signal,
        diagnosis=diagnosis,
        policy=policy,
        verification=verification,
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


def _load_fixture(path: Path) -> dict[str, object]:
    process_observations: list[ProcessObservation] = []
    attempts: list[AttemptObservation] = []
    usage_observations: list[UsageObservation] = []
    run_active = False
    before_fingerprint = "before"
    after_fingerprint = "before"
    success_signal: str | None = None
    session_id = ""

    for line in path.read_text().splitlines():
        if not line.strip():
            continue
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(event, dict):
            continue

        event_type = event.get("type")
        if event_type == "process.observed":
            process_observations.append(ProcessObservation.model_validate(event))
        elif event_type == "attempt.completed":
            attempts.append(AttemptObservation.model_validate(event))
        elif event_type == "usage.observed":
            usage_observations.append(UsageObservation.model_validate(event))
        elif event_type == "run.state":
            run_active = bool(event.get("active"))
            session_id = str(event.get("session_id", ""))
        elif event_type == "verification.snapshot":
            before_fingerprint = str(event.get("before_fingerprint", before_fingerprint))
            after_fingerprint = str(event.get("after_fingerprint", after_fingerprint))
            raw_success = event.get("success_signal")
            success_signal = str(raw_success) if raw_success else None

    return {
        "process_observations": process_observations,
        "attempts": attempts,
        "usage_observations": usage_observations,
        "run_active": run_active,
        "before_fingerprint": before_fingerprint,
        "after_fingerprint": after_fingerprint,
        "success_signal": success_signal,
        "session_id": session_id,
    }


def _detect_fixture_signal(loaded: dict[str, object]) -> Signal | None:
    process_observations = loaded["process_observations"]
    if isinstance(process_observations, list) and process_observations:
        process_signal = detect_hung_process(
            process_observations,
            now=_default_replay_now(process_observations),
        )
        if process_signal is not None:
            return process_signal

    attempts = loaded["attempts"]
    if isinstance(attempts, list):
        repeated = detect_repeated_failure(attempts)
        if repeated is not None:
            return repeated
        no_progress = detect_no_progress(attempts, run_active=bool(loaded["run_active"]))
        if no_progress is not None:
            return no_progress

    usage_observations = loaded["usage_observations"]
    if isinstance(usage_observations, list):
        return detect_session_budget_risk(usage_observations)

    return None


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
