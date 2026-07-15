from deadman.detectors import (
    detect_no_progress,
    detect_repeated_failure,
    detect_session_budget_risk,
)
from deadman.domain import AttemptObservation, DetectorConfig, SignalKind, UsageObservation


def _attempt(index: int, **overrides: object) -> AttemptObservation:
    values = {
        "evidence_id": f"attempt_{index}",
        "attempt_id": str(index),
        "completed_at": float(index),
        "workspace_fingerprint": "ws-a",
        "test_summary": "1 failed",
        "failure_signature": "pytest:test_example",
        "assistant_hypothesis": "same idea",
    }
    values.update(overrides)
    return AttemptObservation.model_validate(values)


def test_repeated_failure_detects_same_signature_without_progress() -> None:
    signal = detect_repeated_failure([_attempt(1), _attempt(2), _attempt(3)])

    assert signal is not None
    assert signal.kind == SignalKind.REPEATED_FAILURE
    assert signal.evidence_ids == ("attempt_1", "attempt_2", "attempt_3")
    assert signal.details["failure_signature"] == "pytest:test_example"


def test_repeated_failure_ignores_changed_workspace_or_test_summary() -> None:
    attempts = [
        _attempt(1),
        _attempt(2, workspace_fingerprint="ws-b"),
        _attempt(3, test_summary="2 failed"),
    ]

    assert detect_repeated_failure(attempts) is None


def test_no_progress_detects_four_completed_attempts_while_active() -> None:
    signal = detect_no_progress(
        [_attempt(1), _attempt(2), _attempt(3), _attempt(4)],
        run_active=True,
    )

    assert signal is not None
    assert signal.kind == SignalKind.NO_PROGRESS
    assert signal.details["attempt_count"] == 4


def test_no_progress_ignores_inactive_run_or_new_hypothesis() -> None:
    attempts = [_attempt(1), _attempt(2), _attempt(3), _attempt(4)]

    assert detect_no_progress(attempts, run_active=False) is None
    assert (
        detect_no_progress(
            [*attempts[:3], _attempt(4, assistant_hypothesis="new idea")],
            run_active=True,
        )
        is None
    )


def test_session_budget_risk_uses_observed_usage_or_manual_checkpoint() -> None:
    config = DetectorConfig(session_budget_threshold=90)

    usage_signal = detect_session_budget_risk(
        [UsageObservation(evidence_id="usage_1", observed_at=1.0, used_units=95, budget_units=100)],
        config=config,
    )
    manual_signal = detect_session_budget_risk(
        [
            UsageObservation(
                evidence_id="usage_2",
                observed_at=2.0,
                used_units=10,
                budget_units=100,
                manual_checkpoint_requested=True,
            )
        ],
        config=config,
    )

    assert usage_signal is not None
    assert usage_signal.kind == SignalKind.SESSION_BUDGET_RISK
    assert manual_signal is not None
    assert manual_signal.details["manual_checkpoint_requested"] is True
