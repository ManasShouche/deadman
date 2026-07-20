from deadman.verify import verify_fixture_recovery


def test_verify_fixture_recovery_can_fail_without_success_signal() -> None:
    result = verify_fixture_recovery(
        before_fingerprint="before",
        after_fingerprint="after",
        success_signal=None,
    )

    assert result.resolved is False
    assert result.changed_progress_fingerprint is True
    assert result.reason == "missing verification evidence"


def test_verify_fixture_recovery_can_fail_without_progress_change() -> None:
    result = verify_fixture_recovery(
        before_fingerprint="same",
        after_fingerprint="same",
        success_signal="target command succeeded",
    )

    assert result.resolved is False
    assert result.changed_progress_fingerprint is False
    assert result.reason == "missing verification evidence"
