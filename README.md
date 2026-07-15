# Deadman

> The session died. The task didn't.

Deadman is a local recovery harness for Codex sessions. It will observe a supervised Codex process, detect bounded pathological states, obtain an evidence-grounded GPT-5.6 recommendation, enforce deterministic policy, and verify recovery.

## Current status

This repo now has the deterministic offline MVP path:

- Codex JSONL parsing with conservative capability detection.
- SQLite evidence persistence for raw events, normalized events, capabilities, process observations, and signals.
- Process ownership/liveness observations and pure detectors for `HUNG_PROCESS`, `REPEATED_FAILURE`, `NO_PROGRESS`, and `SESSION_BUDGET_RISK`.
- Evidence-bound fake diagnosis, deterministic policy checks, fixture execution simulation, verification, and terminal reports.
- Rich terminal panels for `deadman run`, `deadman demo`, `deadman replay`, and `deadman report`.

`deadman run` supervises a completed command, captures JSONL stdout evidence, retains stderr, and persists the adapter evidence to SQLite. The terminal surface now shows panel/table output instead of raw summary lines. Real-time stuck-process intervention and live OpenAI Responses API calls remain behind the tested core boundaries.

## Prerequisites

- Python 3.11 or later
- A locally authenticated Codex CLI for the adapter compatibility capture

## Local setup

```bash
python3 -m venv .venv
.venv/bin/python -m pip install --upgrade pip
.venv/bin/python -m pip install -e ".[dev]"
.venv/bin/deadman
.venv/bin/deadman run -- python -c 'import json; print(json.dumps({"type":"thread.started","thread_id":"demo"})); print(json.dumps({"type":"item.completed","item":{"type":"agent_message"}}))'
.venv/bin/deadman replay scenarios/recordings/hung-process.jsonl
.venv/bin/deadman replay scenarios/recordings/repeated-failure.jsonl
.venv/bin/deadman replay scenarios/recordings/session-handoff.jsonl
.venv/bin/deadman demo
.venv/bin/deadman report repeated-failure
.venv/bin/python -m pytest
.venv/bin/ruff check .
.venv/bin/mypy .
```

The no-argument `deadman` command reports the baseline status. `deadman replay` performs the offline pipeline without Codex, an OpenAI key, or network access. `deadman run -- <command>` records a completed supervised command and writes `.deadman/deadman.sqlite` by default.

## Safety model

Deadman never gives a model shell access or direct process/session control. Deterministic code owns observation, policy enforcement, execution, and verification; GPT-5.6 can recommend only typed, evidence-bound actions.

## Adapter evidence

`scenarios/recordings/` holds replay fixtures and approved harmless compatibility captures. The capture's capability report documents only fields observed from the installed Codex CLI; it never assumes an undocumented event schema or hidden context-window telemetry.

Current replay fixtures:

```bash
.venv/bin/deadman replay scenarios/recordings/hung-process.jsonl
.venv/bin/deadman replay scenarios/recordings/repeated-failure.jsonl
.venv/bin/deadman replay scenarios/recordings/session-handoff.jsonl
```

Current live capture command shape:

```bash
.venv/bin/deadman run -- codex exec --json --sandbox workspace-write "Fix the failing test"
```

Expected demo output:

```text
hung-process: HUNG_PROCESS -> TERMINATE_DESCENDANT_PROCESS -> RESOLVED
repeated-failure: REPEATED_FAILURE -> CANCEL_AND_RESUME -> RESOLVED
session-handoff: SESSION_BUDGET_RISK -> CHECKPOINT_AND_RESPAWN -> RESOLVED
```

## Codex and GPT-5.6

Codex is used to build and review Deadman. GPT-5.6 will be used at runtime only for constrained diagnosis and checkpoint handoff after a deterministic incident signal opens. The collaboration record is in [`CODEX_LOG.md`](CODEX_LOG.md).
