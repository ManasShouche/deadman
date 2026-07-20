# Codex persisted event contract

Observed against `codex-cli 0.144.4` on 2026-07-18. These fields are capability evidence, not a stable upstream API.

## Session discovery

Interactive CLI rollouts are append-only JSONL files below `$CODEX_HOME/sessions/`. Deadman pairs only files whose `session_meta.payload.source` is `cli` and whose canonical `cwd` exactly matches the watched repository.

Observed `session_meta.payload` fields used by Deadman:

- `id`: persisted Codex session identifier.
- `cwd`: repository associated with the session.
- `source`: `cli`, `exec`, or another Codex surface.
- `cli_version`: emitting CLI version when present.

No observed persisted field proves a session-to-PID ownership relationship. Attach mode therefore remains observe-only.

## Normalized events

| Persisted shape | Deadman event |
| --- | --- |
| `session_meta` | `SESSION_STARTED` |
| `turn_context` | `TURN_CONTEXT` |
| `event_msg.task_started` | `TURN_STARTED` |
| `event_msg.task_complete` | `TURN_COMPLETED` |
| `event_msg.token_count` | `USAGE_UPDATED` |
| `event_msg.context_compacted` | `COMPACTION` |
| `event_msg.user_message` / `agent_message` | `MESSAGE` |
| `response_item.custom_tool_call` | `TOOL_CALL_STARTED` |
| `response_item.custom_tool_call_output` | `TOOL_CALL_COMPLETED` |

Unknown objects are stored as `UNKNOWN`. Malformed complete lines are stored as `MALFORMED`. An incomplete final line is not consumed until its newline arrives.

## Compatibility behavior

- Missing usage events disable context-budget conclusions.
- Missing tool events disable tool-history detectors.
- Missing completion events leave turn state as observing rather than completed.
- File replacement or truncation creates a new source generation.
- Event identifiers derive from source generation, byte offset, and raw content so rereads are idempotent.
- Raw local evidence may contain sensitive task content. Fixtures must be sanitized before commit.
