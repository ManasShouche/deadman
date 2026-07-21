# Deadman

> The session died. The task did not.

Deadman is a local recovery supervisor for Codex sessions. It watches a Codex process or recorded session evidence, detects bounded failure states, requests a typed diagnosis, applies only policy-approved recovery actions, verifies the result, and stores an auditable incident record.

It is not a replacement for Codex and it never gives a model shell, process-control, filesystem-write, or session-control tools. Deterministic code owns observation, policy, recovery, and verification.

## What Can I Run?

| Need | Command | Can recover? | Best use |
| --- | --- | --- | --- |
| Supervise a non-interactive command that Deadman launches | `deadman run -- <command>` | Yes, with `--auto-recover` | `codex exec --json` and scripts |
| Launch and supervise the interactive Codex TUI | `deadman agent -- codex ...` | Yes, with `--auto-recover` | A new interactive Codex session |
| Supervise a Codex TUI already running in another terminal | `deadman attach` | Yes, with `--auto-recover` | Real two-terminal recovery |
| Read one persisted Codex session | `deadman watch` | No | Investigation and evidence only |
| Run credential-free shipped scenarios | `deadman replay <trace>` | Simulated only | Judge and offline testing |
| Run the three replay scenarios together | `deadman demo` | Simulated only | Fast offline smoke test |

`--auto-recover` is **off by default** for every command. Without it, Deadman records the signal, diagnosis, and policy result at the approval boundary instead of performing a recovery action.

## Judge Quickstart

```bash
git clone https://github.com/ManasShouche/deadman
cd deadman
./scripts/deadman config check
./scripts/live-attach-smoke
```

`./scripts/deadman` creates `.venv`, installs Deadman in editable mode, and forwards its arguments to the real CLI. The attach smoke is isolated, credential-free, and exercises live process discovery, hung-child detection, recovery, verification, and SQLite persistence.

For offline scenarios without Codex or an API key:

```bash
./scripts/deadman demo
./scripts/deadman replay scenarios/recordings/hung-process.jsonl
./scripts/deadman report repeated-failure
```

## Real Two-Terminal Recovery

This is the main live scenario. It uses a real interactive Codex TUI and Deadman attaches from a second terminal.

Terminal 1, in an isolated repository:

```bash
mkdir -p /private/tmp/deadman-real-attach
cd /private/tmp/deadman-real-attach
git init

codex --no-alt-screen --sandbox workspace-write --ask-for-approval never \
  "Do not edit files. Run this exact command and wait for it:\n+python3 -c 'import subprocess; raise SystemExit(subprocess.Popen([\"sleep\", \"600\"]).wait())'\nDo not interrupt it yourself."
```

Wait until Codex reports that the background command is running. Then open Terminal 2 in the same repository:

```bash
cd /private/tmp/deadman-real-attach

/path/to/deadman/.venv/bin/deadman attach \
  --hung-timeout 20 \
  --auto-recover \
  --diagnosis fake
```

Replace `/path/to/deadman` with your clone path. Use `--diagnosis openai` only when `OPENAI_API_KEY` is configured and a live GPT-5.6 diagnosis is required. `fake` keeps this process-recovery test deterministic while still using the real Codex CLI and real OS process tree.

Expected result after about 20 seconds:

```text
Status       recovered
Signal       HUNG_PROCESS
Hung pid     <owned python or sleep pid>
Action       terminated descendant process tree (...)
Verification resolved
Final state  RESOLVED
```

Codex should stay open. Deadman never signals the selected Codex process itself; it can signal only a freshly proven descendant.

Inspect the recorded incident from Terminal 2:

```bash
sqlite3 .deadman/deadman.sqlite 'select id, state from incidents;'
sqlite3 .deadman/deadman.sqlite 'select count(*) from signals; select count(*) from diagnoses; select count(*) from action_results; select count(*) from verification_results;'
```

## Command Reference

All commands resolve the default database to `<git-root>/.deadman/deadman.sqlite`, not the shell's current directory. Startup always prints the resolved SQLite path and whether auto recovery is on.

### `deadman run`

Use `run` when Deadman should start the command itself. It is the supported surface for non-interactive `codex exec --json` sessions.

```bash
deadman run [OPTIONS] -- <command> [command arguments]
```

Examples:

```bash
# Capture a normal JSONL Codex run.
deadman run -- codex exec --json --sandbox workspace-write "Fix the failing test"

# Detect a hung owned child after 20 seconds and recover it automatically.
deadman run --hung-timeout 20 --auto-recover -- \
  codex exec --json --sandbox workspace-write \
  "Run a command that starts a child process and waits forever"

# After verified recovery, resume the Codex exec session with grounded guidance.
deadman run --hung-timeout 60 --auto-recover --resume-after-recovery -- \
  codex exec --json --sandbox workspace-write "Fix the fixture task"
```

| Option | Meaning |
| --- | --- |
| `--database PATH` | Override the SQLite database path. |
| `--timeout SECONDS` | Stop the supervised command after this duration. |
| `--hung-timeout SECONDS` | Enable live hung-descendant detection after this idle time. |
| `--auto-recover` | Permit policy-approved recovery actions. Off by default. |
| `--diagnosis auto|fake|openai` | Use configured OpenAI, deterministic fixture diagnosis, or require OpenAI. |
| `--model MODEL` | Model for `--diagnosis openai`; default `gpt-5.6`. |
| `--resume-after-recovery` | Resume a verified recovered `codex exec` session. Requires an explicit safe Codex sandbox. |

The terminal summary includes: `Status`, `Return code`, raw and normalized event counts, session ID when available, diagnosis backend, signal, recommended action, policy result, verification verdict, optional resume fields, and SQLite path.

### `deadman agent`

Use `agent` when Deadman should launch the interactive Codex TUI inside a supervised PTY.

```bash
deadman agent [OPTIONS] -- codex [codex arguments]
```

Example:

```bash
deadman agent --hung-timeout 20 --auto-recover -- \
  codex --no-alt-screen --sandbox workspace-write
```

| Option | Meaning |
| --- | --- |
| `--database PATH` | Override the SQLite database path. |
| `--hung-timeout SECONDS` | Idle duration before an owned descendant is considered hung; default `60`. |
| `--auto-recover` | Permit termination of a proven hung descendant. Off by default. |

While Codex runs, Deadman prints periodic status such as:

```text
[deadman] monitoring 1 owned descendant(s); ignored baseline=3
[deadman] HUNG_PROCESS detected for pid 12345
[deadman] recovered: terminated descendant process tree (2 processes)
```

Codex itself and known Codex helper processes are baseline processes, never recovery targets. The interactive `agent` surface currently uses deterministic fixture diagnosis; live `--diagnosis openai` options are available on `run` and `attach`.

### `deadman attach`

Use `attach` in a second terminal when Codex was launched independently. Deadman discovers live Codex processes whose working directory is inside the current Git repository. If one process matches, it selects it; if several match, it displays candidates or accepts `--pid`.

```bash
deadman attach [OPTIONS]
```

Examples:

```bash
# Observe a live Codex process but do not act.
deadman attach

# Recover an owned hung descendant of the selected Codex process.
deadman attach --auto-recover --hung-timeout 20

# Select a known candidate and require live GPT-5.6 diagnosis.
deadman attach --pid 12345 --hung-timeout 60 --auto-recover \
  --diagnosis openai --model gpt-5.6
```

| Option | Meaning |
| --- | --- |
| `--pid PID` | Select a specific discovered Codex root. |
| `--database PATH` | Override the SQLite database path. |
| `--hung-timeout SECONDS` | Idle duration before a descendant is considered hung; default `60`. |
| `--auto-recover` | Permit recovery of a proven owned descendant. Off by default. |
| `--diagnosis auto|fake|openai` | Diagnosis backend. `auto` uses OpenAI only when a key is configured. |
| `--model MODEL` | Model for live OpenAI diagnosis; default `gpt-5.6`. |
| `--poll-interval SECONDS` | Process observation interval; default `0.5`. |

`attach` proves the live process root and can recover descendants of that root. It does not yet establish an exact one-to-one link between the chosen process and a persisted Codex session file when several sessions use the same repository.

### `deadman watch`

Use `watch` to inspect one persisted interactive Codex session. It reads append-only session events under `$CODEX_HOME/sessions`, enforces an exact repository match, and never performs process control.

```bash
deadman watch [OPTIONS]
```

Examples:

```bash
# Choose from matching sessions interactively.
deadman watch

# Read one known session once and exit.
deadman watch --session <session-id> --once

# Tail a known session every second.
deadman watch --session <session-id> --poll-interval 1
```

| Option | Meaning |
| --- | --- |
| `--session ID` | Explicit persisted Codex session ID. |
| `--database PATH` | Override the SQLite database path. |
| `--poll-interval SECONDS` | Session-file read interval; default `0.5`. |
| `--once` | Ingest available events, render one snapshot, then exit. |

The watch panel reports mode, session ID, workspace, turn state, event counts, latest event, observed capabilities, active signals, and `ownership=unproven`. Use `attach` when active process recovery is needed.

### `deadman replay`, `demo`, and `report`

These commands are deterministic and do not need Codex, network access, or an API key.

```bash
# Run one fixture through normalizer, detector, diagnosis fixture, policy,
# simulated action, verifier, and renderer.
deadman replay scenarios/recordings/hung-process.jsonl

# Run all shipped fixtures.
deadman demo

# Render the report for one shipped replay incident.
deadman report repeated-failure
```

Shipped replay scenarios:

| Fixture | Signal | Recovery outcome |
| --- | --- | --- |
| `hung-process.jsonl` | `HUNG_PROCESS` | `TERMINATE_DESCENDANT_PROCESS -> RESOLVED` |
| `repeated-failure.jsonl` | `REPEATED_FAILURE` | `CANCEL_AND_RESUME -> RESOLVED` |
| `session-handoff.jsonl` | `SESSION_BUDGET_RISK` | `CHECKPOINT_AND_RESPAWN -> RESOLVED` |

### `deadman config check`

```bash
deadman config check
```

This displays whether OpenAI credentials are available, their source without revealing a secret, the project `.env` path, the resolved SQLite path, offline replay readiness, and the fact that Codex TUI authentication is never read by Deadman.

## Evidence and Incident Fields

Each incident is stored in SQLite. The relevant records are:

| Record | What it contains |
| --- | --- |
| Raw events | Original adapter evidence, including malformed or unknown JSONL. |
| Normalized events | Stable event types used by detectors and reports. |
| Process observations | Root PID, PID, parent PID, command line, descendant proof, observation time, and output activity fields. |
| Signals | Detector kind, severity, evidence IDs, fingerprint, threshold details, and target PID. |
| Diagnosis | Typed recommended action, confidence, citations, and guidance. |
| Policy decision | Allowed or rejected action and reason. |
| Action result | Attempted action, success state, evidence IDs, and bounded executor message. |
| Verification result | `resolved`, progress-fingerprint status, success signal, and reason. |
| Incident transitions | Timestamp, state, actor, reason, evidence IDs, and action fingerprint. |
| Report | Human-readable timeline and prevention guidance. |

The main terminal statuses are:

| Status | Meaning |
| --- | --- |
| `completed` | The supervised run ended with completion evidence. |
| `awaiting_approval` | A signal was found, but recovery was not permitted. |
| `recovered` | A bounded recovery action was verified. |
| `recovered_and_resumed` | A recovered Codex exec session emitted verified completion after resume. |
| `escalated` | Recovery was unavailable, failed, or did not verify. |
| `timed_out` | The configured supervised-command timeout was reached. |

## Credentials and Safety

For live GPT-5.6 diagnosis, set `OPENAI_API_KEY` in the environment or in the ignored project `.env`:

```bash
cp .env.example .env
# Add OPENAI_API_KEY to .env
deadman config check
```

`--diagnosis auto` prefers an existing environment key, then the repository `.env`, then visibly falls back to deterministic fixture diagnosis. `--diagnosis openai` fails fast if no key is available. Deadman never reads, copies, displays, or persists Codex TUI authentication state.

Recovery is bounded by process ownership and policy:

- Deadman never signals its own process, its parent, PID 1, or another protected PID.
- A target is re-checked as a descendant immediately before signalling.
- `watch` is always observe-only.
- `attach` can act only on descendants of the live selected Codex root.
- `--auto-recover` is required for automatic action execution.

## Development

```bash
./scripts/setup --dev
.venv/bin/python -m pytest
.venv/bin/ruff check .
.venv/bin/mypy .
```

The project is a Python terminal wrapper using Typer, Rich, SQLite, Pydantic, `psutil`, and the OpenAI SDK. Rust and a Codex plugin/MCP companion are explicitly roadmap items; the external supervisor owns the failure domain for this MVP.

[`CODEX_LOG.md`](CODEX_LOG.md) records the implementation and validation history.
