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
- Interactive TUI recovery tracks owned descendant process age separately from Codex status chatter, ignores known Codex helper processes, and terminates the proven owned process subtree when recovery is approved.
- Observe-only pairing with an existing interactive CLI session through `deadman watch`.
- Active recovery of a Codex session started in another terminal through `deadman attach`: Deadman discovers the live Codex process by repository, proves the root PID through the OS process table, and runs the same detect → diagnose → policy → terminate → verify → record loop as managed mode.
- A single shared recovery and incident pipeline behind `run`, `agent`, and `attach`, so every mode records an auditable incident (signal, diagnosis, policy, action, verification, report), not just a silent action.

`deadman run` is for `codex exec --json` and other non-interactive commands. When `--hung-timeout` is supplied, it also monitors the live process tree for a proven stuck descendant. `--auto-recover` is off by default; without that flag, Deadman records the diagnosis and blocks at the approval boundary. Add `--auto-recover` only when you want policy-approved recovery actions to execute automatically. Add `--resume-after-recovery` when you want Deadman to resume a recovered session with evidence-grounded guidance. Automatic resume requires the original Codex command to specify `--sandbox read-only` or `--sandbox workspace-write`; Deadman retains that sandbox, forces JSONL output, and escalates unless the resumed turn emits a completion event. If Codex exits while reporting an unfinished background command, `--auto-recover` uses the same guarded resume path with cleanup guidance. Diagnosis defaults to `auto`: an existing `OPENAI_API_KEY` wins, then Deadman loads the current repository's `.env`, otherwise it visibly uses the deterministic fixture fallback. Use `--diagnosis openai` to require live GPT-5.6 and fail fast when no key is configured. `deadman agent` is for the interactive Codex CLI; it runs the TUI inside a pseudo-terminal, preserves normal terminal dimensions, prints periodic monitoring status, and monitors child processes in the background.

## Prerequisites

- Python 3.11 or later
- A locally authenticated Codex CLI for the adapter compatibility capture

## Fresh clone quick start

After cloning, enter the repo first. The clone URL is not a shell command by itself.

```bash
git clone https://github.com/ManasShouche/deadman
cd deadman
./scripts/deadman config check
```

`./scripts/deadman` creates `.venv`, installs Deadman in editable mode, and then forwards your arguments to the real CLI. For the isolated interactive Codex TUI supervision smoke test:

```bash
./scripts/live-tui-smoke
```

The smoke script runs Codex in `/private/tmp/deadman-codex-tui-test`, keeps the test isolated from this repository, and enables `--auto-recover` so Deadman can terminate a proven hung descendant. To install the contributor tools for tests and linting:

```bash
./scripts/setup --dev
```

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
.venv/bin/deadman attach --auto-recover --hung-timeout 20
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

The no-argument `deadman` command reports the baseline status. `deadman replay` performs the offline pipeline without Codex, an OpenAI key, or network access. `deadman run -- <command>` records a completed supervised command and writes `.deadman/deadman.sqlite` at the Git repository root by default, not necessarily the current shell directory. Deadman prints the resolved SQLite path and auto-recover state on startup. Add `--hung-timeout <seconds>` to enable live hung-child detection; add `--auto-recover` only when you want policy-approved recovery actions to execute automatically. Add `--resume-after-recovery` to continue a recovered Codex session with evidence-grounded guidance.

Automatic process recovery requires proven process ownership. Deadman proves it two ways: by launching the supervised process itself (`deadman run -- codex exec --json ...` for non-interactive JSONL runs, `deadman agent -- codex ...` for the interactive TUI), or by discovering a Codex process you started independently and matching it to the repository through the live OS process table (`deadman attach`). When a watched user command is stuck, Deadman terminates the proven owned descendant subtree, not just the first detected PID, so inner sleepers started by a background terminal are cleaned up too.

`deadman watch` reads persisted interactive Codex events from `$CODEX_HOME/sessions`. It requires explicit session pairing, enforces an exact repository match, and is observe-only because persisted events do not prove process ownership. Use `deadman watch` in a terminal to select a matching session, or pass `--session <id>` explicitly. `--once` ingests the available stream and exits.

### `deadman attach` — recover a Codex session from another terminal

`deadman attach` supervises a Codex session you started yourself in a separate terminal, in the same repository, and can actively recover it. Where `deadman watch` is limited to observation because a persisted session file cannot prove ownership of a running process, `deadman attach` instead discovers the **live** Codex process through the OS process table and matches it to the repository. A live-process match proves the root PID, so Deadman may terminate a proven hung descendant of that Codex process — the same bounded, policy-gated action managed mode uses.

Run Codex in one terminal at your repository root, then in a second terminal at the same repository run:

```bash
# Approval mode: detect and report a hung child, but do not act.
.venv/bin/deadman attach

# Act on it: terminate the proven hung descendant and record the incident.
.venv/bin/deadman attach --auto-recover --hung-timeout 20
```

Deadman lists the Codex processes it found in the repository, auto-selects when there is exactly one (pass `--pid <pid>` to choose explicitly), and then supervises until the Codex process exits or you press Ctrl-C. `--auto-recover` is required before any termination; without it Deadman opens an `AWAITING_APPROVAL` incident and leaves the process untouched. It never signals the Codex process itself, only proven hung descendants of it, and never a protected PID. Diagnosis honors the same `--diagnosis auto|fake|openai` and `--model` flags as `deadman run`.

Because attach mode uses no pseudo-terminal and no pipe polling — only `psutil` process inspection — it is the most portable path and runs on macOS, Linux, and Windows. (`deadman agent` and the `--hung-timeout` streaming path in `deadman run` rely on Unix pseudo-terminals and `select`, so they target macOS and Linux.)

For a self-contained, credential-free proof of the whole attach pipeline (isolated repo, stand-in Codex process, real Deadman recovery and incident record):

```bash
./scripts/live-attach-smoke
```

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
.venv/bin/deadman agent --hung-timeout 20 --auto-recover -- codex --no-alt-screen --sandbox workspace-write
./scripts/live-tui-smoke
.venv/bin/deadman watch --session <session-id>
```

Live attach against a real Codex session (two terminals, same repository):

```bash
# Terminal 1 — start Codex yourself and give it a task that blocks on a child:
codex --sandbox workspace-write
#   then ask it, e.g.: "Run a shell command that sleeps for 300 seconds."

# Terminal 2 — attach from the same repository and recover the hung child:
.venv/bin/deadman attach --auto-recover --hung-timeout 20

# Or verify the full attach pipeline with no Codex and no key:
./scripts/live-attach-smoke
```

Expected demo output:

```text
hung-process: HUNG_PROCESS -> TERMINATE_DESCENDANT_PROCESS -> RESOLVED
repeated-failure: REPEATED_FAILURE -> CANCEL_AND_RESUME -> RESOLVED
session-handoff: SESSION_BUDGET_RISK -> CHECKPOINT_AND_RESPAWN -> RESOLVED
```

## Codex and GPT-5.6

Codex is used to build and review Deadman. GPT-5.6 will be used at runtime only for constrained diagnosis and checkpoint handoff after a deterministic incident signal opens. The collaboration record is in [`CODEX_LOG.md`](CODEX_LOG.md).
