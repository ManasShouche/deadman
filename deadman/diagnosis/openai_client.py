"""OpenAI Responses API diagnosis client."""

from __future__ import annotations

import json
from typing import Any, Protocol

from pydantic import ValidationError

from deadman.domain import Diagnosis, RecoveryAction, Signal, SignalKind


class ResponsesClient(Protocol):
    """Subset of the OpenAI SDK client used by Deadman."""

    @property
    def responses(self) -> Any:
        """Responses API resource."""
        ...


class OpenAIDiagnosisClient:
    """Call GPT with structured output and validate the typed recommendation."""

    def __init__(self, *, client: ResponsesClient, model: str = "gpt-5.6") -> None:
        self.client = client
        self.model = model

    def diagnose(self, signal: Signal) -> Diagnosis:
        response = self.client.responses.create(
            model=self.model,
            input=_diagnosis_prompt(signal),
            tools=[],
            text={"format": _diagnosis_text_format()},
            reasoning={"effort": "medium"},
        )
        return parse_diagnosis_response(response)


def build_default_openai_diagnosis_client(*, model: str = "gpt-5.6") -> OpenAIDiagnosisClient:
    """Build the real OpenAI client lazily so tests do not need the SDK object."""

    from openai import OpenAI

    return OpenAIDiagnosisClient(client=OpenAI(), model=model)


def parse_diagnosis_response(response: object) -> Diagnosis:
    """Extract and validate structured JSON from a Responses API result."""

    output_text = getattr(response, "output_text", None)
    if not isinstance(output_text, str):
        raise ValueError("Responses API result did not include output_text")

    try:
        payload = json.loads(output_text)
    except json.JSONDecodeError as exc:
        raise ValueError("Responses API result was not valid JSON") from exc

    try:
        return Diagnosis.model_validate(payload)
    except ValidationError as exc:
        raise ValueError("Responses API result did not match Diagnosis schema") from exc


def _diagnosis_prompt(signal: Signal) -> str:
    packet = signal.model_dump(mode="json")
    return (
        "You are Deadman's bounded diagnostician. "
        "Select only one typed recovery action from the schema. "
        "Use only the evidence IDs in this packet. "
        "Do not request tools, shell, filesystem writes, PIDs, or session control.\n\n"
        f"Evidence packet:\n{json.dumps(packet, sort_keys=True)}"
    )


def _diagnosis_text_format() -> dict[str, object]:
    return {
        "type": "json_schema",
        "name": "deadman_diagnosis",
        "strict": True,
        "schema": _diagnosis_schema(),
    }


def _diagnosis_schema() -> dict[str, Any]:
    """Strict Responses-API JSON schema derived from the Diagnosis model.

    OpenAI strict structured outputs require every object to set
    `additionalProperties: false`, list all properties in `required`, and omit
    numeric/format constraints (e.g. `minimum`). Pydantic's generated schema
    violates all three, so the schema is built directly from the typed enums.
    Pydantic still validates the response after parsing, including the
    confidence range.
    """

    properties = {
        "classification": {"type": "string", "enum": [kind.value for kind in SignalKind]},
        "confidence": {"type": "number"},
        "recommended_action": {
            "type": "string",
            "enum": [action.value for action in RecoveryAction],
        },
        "rationale": {"type": "string"},
        "evidence_ids": {"type": "array", "items": {"type": "string"}},
        "guidance": {"type": "string"},
        "requires_human_approval": {"type": "boolean"},
    }
    return {
        "type": "object",
        "additionalProperties": False,
        "properties": properties,
        "required": list(properties),
    }
