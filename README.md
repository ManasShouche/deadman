# Deadman

> The session died. The task didn't.

Deadman is a local recovery harness for Codex sessions. It will observe a supervised Codex process, detect bounded pathological states, obtain an evidence-grounded GPT-5.6 recommendation, enforce deterministic policy, and verify recovery.

## Current status

This repo now has the D1 detection baseline:

- Codex JSONL parsing with conservative capability detection.
- SQLite evidence persistence for raw events, normalized events, capabilities, process observations, and signals.
- Process ownership/liveness observations.
- A pure `HUNG_PROCESS` detector with an offline replay fixture.

Recovery actions, GPT-5.6 diagnosis, live supervision, reports, and the remaining detectors are not implemented yet.

## Prerequisites

- Python 3.11 or later
- A locally authenticated Codex CLI for the adapter compatibility capture

## Local setup

```bash
python3 -m venv .venv
.venv/bin/python -m pip install --upgrade pip
.venv/bin/python -m pip install -e ".[dev]"
.venv/bin/deadman
.venv/bin/deadman replay scenarios/recordings/hung-process.jsonl
.venv/bin/python -m pytest
.venv/bin/ruff check .
.venv/bin/mypy .
```

The no-argument `deadman` command still reports the baseline status. `deadman replay` currently supports the deterministic hung-process fixture and performs detection only; it does not recover or call OpenAI.

## Safety model

Deadman never gives a model shell access or direct process/session control. Deterministic code owns observation, policy enforcement, execution, and verification; GPT-5.6 can recommend only typed, evidence-bound actions.

## Adapter evidence

`scenarios/recordings/` holds replay fixtures and approved harmless compatibility captures. The capture's capability report documents only fields observed from the installed Codex CLI; it never assumes an undocumented event schema or hidden context-window telemetry.

Current replay fixture:

```bash
.venv/bin/deadman replay scenarios/recordings/hung-process.jsonl
```

Expected output:

```text
HUNG_PROCESS proc_001 pid=101 idle_seconds=65.0
```

## Codex and GPT-5.6

Codex is used to build and review Deadman. GPT-5.6 will be used at runtime only for constrained diagnosis and checkpoint handoff after a deterministic incident signal opens. The collaboration record is in [`CODEX_LOG.md`](CODEX_LOG.md).
