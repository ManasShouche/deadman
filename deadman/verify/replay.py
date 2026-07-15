"""Deterministic replay verification."""

from __future__ import annotations

from deadman.domain import VerificationResult


def verify_fixture_recovery(
    *,
    before_fingerprint: str,
    after_fingerprint: str,
    success_signal: str | None,
) -> VerificationResult:
    """Verify recovery using the spec's two required evidence checks."""

    changed = before_fingerprint != after_fingerprint
    resolved = changed and success_signal is not None
    reason = (
        "verified progress and success evidence"
        if resolved
        else "missing verification evidence"
    )
    return VerificationResult(
        resolved=resolved,
        changed_progress_fingerprint=changed,
        success_signal=success_signal,
        reason=reason,
    )
