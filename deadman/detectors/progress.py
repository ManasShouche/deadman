"""Pure progress and budget detectors."""

from __future__ import annotations

import hashlib
from collections import Counter
from collections.abc import Iterable

from deadman.domain import (
    AttemptObservation,
    DetectorConfig,
    Severity,
    Signal,
    SignalKind,
    UsageObservation,
)


def detect_repeated_failure(
    attempts: Iterable[AttemptObservation],
    *,
    config: DetectorConfig | None = None,
) -> Signal | None:
    """Detect the same failure with unchanged workspace and test evidence."""

    threshold = (config or DetectorConfig()).repeated_failure_threshold
    completed = list(attempts)
    counts = Counter(
        (
            attempt.failure_signature,
            attempt.workspace_fingerprint,
            attempt.test_summary,
        )
        for attempt in completed
        if attempt.failure_signature
    )
    for key, count in counts.items():
        if count < threshold:
            continue

        failure_signature, workspace_fingerprint, test_summary = key
        matching = [
            attempt
            for attempt in completed
            if (
                attempt.failure_signature,
                attempt.workspace_fingerprint,
                attempt.test_summary,
            )
            == key
        ]
        return Signal(
            kind=SignalKind.REPEATED_FAILURE,
            severity=Severity.WARNING,
            evidence_ids=tuple(attempt.evidence_id for attempt in matching[:threshold]),
            fingerprint=_fingerprint("REPEATED_FAILURE", *(str(value) for value in key)),
            details={
                "failure_signature": failure_signature,
                "workspace_fingerprint": workspace_fingerprint,
                "test_summary": test_summary,
                "count": count,
                "threshold": threshold,
            },
        )
    return None


def detect_no_progress(
    attempts: Iterable[AttemptObservation],
    *,
    run_active: bool,
    config: DetectorConfig | None = None,
) -> Signal | None:
    """Detect completed attempts without workspace or test-summary progress."""

    if not run_active:
        return None

    threshold = (config or DetectorConfig()).no_progress_attempt_threshold
    completed = list(attempts)
    if len(completed) < threshold:
        return None

    tail = completed[-threshold:]
    workspace_fingerprints = {attempt.workspace_fingerprint for attempt in tail}
    test_summaries = {attempt.test_summary for attempt in tail}
    hypotheses = {attempt.assistant_hypothesis for attempt in tail if attempt.assistant_hypothesis}
    if len(workspace_fingerprints) != 1 or len(test_summaries) != 1 or len(hypotheses) > 1:
        return None

    workspace_fingerprint = tail[0].workspace_fingerprint
    test_summary = tail[0].test_summary
    return Signal(
        kind=SignalKind.NO_PROGRESS,
        severity=Severity.WARNING,
        evidence_ids=tuple(attempt.evidence_id for attempt in tail),
        fingerprint=_fingerprint("NO_PROGRESS", workspace_fingerprint, test_summary),
        details={
            "workspace_fingerprint": workspace_fingerprint,
            "test_summary": test_summary,
            "attempt_count": len(tail),
            "threshold": threshold,
        },
    )


def detect_session_budget_risk(
    observations: Iterable[UsageObservation],
    *,
    config: DetectorConfig | None = None,
) -> Signal | None:
    """Detect explicit checkpoint requests or observed budget threshold crossings."""

    threshold = (config or DetectorConfig()).session_budget_threshold
    for observation in observations:
        if not observation.manual_checkpoint_requested and observation.used_units < threshold:
            continue

        return Signal(
            kind=SignalKind.SESSION_BUDGET_RISK,
            severity=Severity.INFO,
            evidence_ids=(observation.evidence_id,),
            fingerprint=_fingerprint(
                "SESSION_BUDGET_RISK",
                str(observation.budget_units),
                str(observation.manual_checkpoint_requested),
            ),
            details={
                "used_units": observation.used_units,
                "budget_units": observation.budget_units,
                "threshold": threshold,
                "manual_checkpoint_requested": observation.manual_checkpoint_requested,
            },
        )
    return None


def _fingerprint(kind: str, *parts: str) -> str:
    digest = hashlib.sha256("\x00".join((kind, *parts)).encode("utf-8")).hexdigest()
    return f"{kind}:{digest[:16]}"
