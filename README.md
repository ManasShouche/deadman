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
- Live hung-child detection and policy-gated descendant termination through `deadman run --hung-timeout ... --auto-recover -- <command>`.
- Optional guided Codex resume after verified recovery through `--resume-after-recovery`.
- Detection of Codex JSONL traces that finish while a `command_execution` item is still `in_progress`; with `--auto-recover`, Deadman resumes the Codex session with cleanup guidance.
- PTY supervision for the interactive Codex CLI through `deadman agent -- codex ...`.
- Observe-only pairing with an existing interactive CLI session through `deadman watch`.

`deadman run` is for `codex exec --json` and other non-interactive commands. When `--hung-timeout` is supplied, it also monitors the live process tree for a proven stuck descendant. Recovery actions require `--auto-recover`; without that flag, Deadman records the diagnosis and blocks at the approval boundary. Add `--resume-after-recovery` when you want Deadman to resume a recovered session with evidence-grounded guidance. Automatic resume requires the original Codex command to specify `--sandbox read-only` or `--sandbox workspace-write`; Deadman retains that sandbox, forces JSONL output, and escalates unless the resumed turn emits a completion event. If Codex exits while reporting an unfinished background command, `--auto-recover` uses the same guarded resume path with cleanup guidance. Diagnosis defaults to `auto`: an existing `OPENAI_API_KEY` wins, then Deadman loads the current repository's `.env`, otherwise it visibly uses the deterministic fixture fallback. Use `--diagnosis openai` to require live GPT-5.6 and fail fast when no key is configured. `deadman agent` is for the interactive Codex CLI; it runs the TUI inside a pseudo-terminal and monitors child processes in the background.

## Prerequisites

- Python 3.11 or later
- A locally authenticated Codex CLI for the adapter compatibility capture

## Local setup

```bash
python3 -m venv .venv
.venv/bin/python -m pip install --upgrade pip
.venv/bin/python -m pip install -e ".[dev]"
cp .env.example .env
.venv/bin/deadman config check
.venv/bin/deadman
.venv/bin/deadman run -- .venv/bin/python -c 'import json; print(json.dumps({"type":"thread.started","thread_id":"demo"})); print(json.dumps({"type":"item.completed","item":{"type":"agent_message"}}))'
.venv/bin/deadman run --hung-timeout 0.5 --auto-recover -- .venv/bin/python -c 'import json, subprocess, sys; child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"]); child.wait(); print(json.dumps({"type":"thread.started","thread_id":"live"})); print(json.dumps({"type":"item.completed","item":{"type":"agent_message"}}))'
.venv/bin/deadman agent --hung-timeout 20 --auto-recover -- codex --sandbox workspace-write
.venv/bin/deadman watch --session <session-id> --once
.venv/bin/deadman replay scenarios/recordings/hung-process.jsonl
.venv/bin/deadman replay scenarios/recordings/repeated-failure.jsonl
.venv/bin/deadman replay scenarios/recordings/session-handoff.jsonl
.venv/bin/deadman demo
.venv/bin/deadman report repeated-failure
.venv/bin/python -m pytest
.venv/bin/ruff check .
.venv/bin/mypy .
```

The no-argument `deadman` command reports the baseline status. `deadman replay` performs the offline pipeline without Codex, an OpenAI key, or network access. `deadman run -- <command>` records a completed supervised command and writes `.deadman/deadman.sqlite` by default. Add `--hung-timeout <seconds>` to enable live hung-child detection; add `--auto-recover` only when you want policy-approved recovery actions to execute automatically. Add `--resume-after-recovery` to continue a recovered Codex session with evidence-grounded guidance.

`deadman watch` reads persisted interactive Codex events from `$CODEX_HOME/sessions`. It requires explicit session pairing, enforces an exact repository match, and is observe-only because persisted events do not prove process ownership. Use `deadman watch` in a terminal to select a matching session, or pass `--session <id>` explicitly. `--once` ingests the available stream and exits.

For live GPT-5.6 diagnosis, set `OPENAI_API_KEY` in the shell or in the ignored project `.env`. Deadman never reads or copies Codex TUI authentication state, and it never prints the key. Offline replay needs no credentials.

## Safety model

Deadman never gives a model shell access or direct process/session control. Deterministic code owns observation, policy enforcement, execution, and verification; GPT-5.6 can recommend only typed, evidence-bound actions.

## Scope decisions

The MVP is a Python terminal wrapper. Rust is a future option for a native wrapper/TUI shell once the behavior is stable. A Codex plugin/MCP companion is also roadmap-only; it should not own recovery because it cannot supervise a Codex session that is already stuck.

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
.venv/bin/deadman run --hung-timeout 60 --auto-recover --diagnosis openai -- codex exec --json --sandbox workspace-write "Fix the fixture task"
.venv/bin/deadman run --hung-timeout 60 --auto-recover --resume-after-recovery -- codex exec --json --sandbox workspace-write "Fix the fixture task"
.venv/bin/deadman run --hung-timeout 20 --auto-recover -- codex exec --json --sandbox workspace-write "Run a command that starts a child process and waits forever"
.venv/bin/deadman agent --hung-timeout 20 --auto-recover -- codex --sandbox workspace-write
.venv/bin/deadman watch --session <session-id>
```

Expected demo output:

```text
hung-process: HUNG_PROCESS -> TERMINATE_DESCENDANT_PROCESS -> RESOLVED
repeated-failure: REPEATED_FAILURE -> CANCEL_AND_RESUME -> RESOLVED
session-handoff: SESSION_BUDGET_RISK -> CHECKPOINT_AND_RESPAWN -> RESOLVED
```

## Codex and GPT-5.6

Codex is used to build and review Deadman. GPT-5.6 will be used at runtime only for constrained diagnosis and checkpoint handoff after a deterministic incident signal opens. The collaboration record is in [`CODEX_LOG.md`](CODEX_LOG.md).
