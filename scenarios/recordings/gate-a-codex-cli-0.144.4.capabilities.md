# Gate A capability report

- **Captured:** 2026-07-15
- **CLI version:** `codex-cli 0.144.4`
- **Invocation:** `codex exec --json --sandbox read-only --color never` with a harmless response-only prompt
- **Persisted session ID:** observed in `thread.started` as `019f64d0-696b-7850-859b-5f15d6acc6e3`; guided resume may be enabled after the adapter persists this field.
- **Completion events:** an `item.completed` event with an `agent_message` item was observed; no command or tool completion event was observed, so loop/error-signature detectors remain capability-gated.
- **Usage telemetry:** `turn.completed.usage` was observed with input, cached-input, output, and reasoning-output token fields; a Deadman session budget can use only fields verified by the eventual adapter.
- **File-change events:** none observed; progress evidence must initially use Git status/diff fingerprints.

This capture is evidence for this installed CLI version, not a stable application event-schema contract.
