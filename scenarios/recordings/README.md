# Recorded traces

This directory contains immutable, versioned JSONL evidence used for adapter compatibility and deterministic replay. Local exploratory traces use the `.local.jsonl` suffix and are ignored.

- `gate-a-codex-cli-0.144.4.jsonl` is the harmless managed `codex exec --json` compatibility capture.
- `codex-session-cli-0.144.4.jsonl` is a sanitized persisted interactive-session contract fixture.
- The hung-process, repeated-failure, and session-handoff traces drive deterministic replay.

Raw records are retained even when they are malformed or have unknown event types. Future normalizers may derive structured records from them, but must not treat them as a stable Codex event-schema contract.
