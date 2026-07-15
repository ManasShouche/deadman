import json
from dataclasses import dataclass
from typing import Any

import pytest

from deadman.diagnosis import OpenAIDiagnosisClient, parse_diagnosis_response
from deadman.domain import RecoveryAction, Severity, Signal, SignalKind


@dataclass(frozen=True)
class _Response:
    output_text: str


class _Responses:
    def __init__(self) -> None:
        self.kwargs: dict[str, Any] | None = None

    def create(self, **kwargs: Any) -> _Response:
        self.kwargs = kwargs
        return _Response(
            json.dumps(
                {
                    "classification": "HUNG_PROCESS",
                    "confidence": 0.91,
                    "recommended_action": "TERMINATE_DESCENDANT_PROCESS",
                    "rationale": "owned child is idle",
                    "evidence_ids": ["proc_001"],
                    "guidance": "terminate the proven descendant only",
                    "requires_human_approval": True,
                }
            )
        )


class _Client:
    def __init__(self) -> None:
        self.responses = _Responses()


def _signal() -> Signal:
    return Signal(
        kind=SignalKind.HUNG_PROCESS,
        severity=Severity.CRITICAL,
        evidence_ids=("proc_001",),
        fingerprint="hung:1",
    )


def test_openai_diagnosis_client_sends_structured_output_without_tools() -> None:
    fake = _Client()
    diagnosis = OpenAIDiagnosisClient(client=fake, model="gpt-5.6").diagnose(_signal())

    assert diagnosis.recommended_action == RecoveryAction.TERMINATE_DESCENDANT_PROCESS
    assert fake.responses.kwargs is not None
    assert fake.responses.kwargs["model"] == "gpt-5.6"
    assert fake.responses.kwargs["tools"] == []
    assert fake.responses.kwargs["text"]["format"]["type"] == "json_schema"
    assert fake.responses.kwargs["text"]["format"]["strict"] is True
    assert "proc_001" in fake.responses.kwargs["input"]


def test_parse_diagnosis_response_rejects_invalid_json() -> None:
    with pytest.raises(ValueError, match="not valid JSON"):
        parse_diagnosis_response(_Response("not-json"))


def test_parse_diagnosis_response_rejects_schema_mismatch() -> None:
    with pytest.raises(ValueError, match="Diagnosis schema"):
        parse_diagnosis_response(_Response(json.dumps({"classification": "HUNG_PROCESS"})))
