# Codex collaboration log

This append-only log records how Codex and the developer built Deadman. It is deliberately factual: commands, outcomes, decisions, and links rather than retrospective claims.

## 2026-07-15 — D0 initialization

- **Goal:** establish the spec-driven Python skeleton and Codex compatibility baseline.
- **Human decisions:** use the D0 baseline; capture one harmless persisted `codex exec --json` trace; use `AGENTS.md` and this log instead of project-local hooks or profiles.
- **Codex contribution:** created the collaboration guidance, package/test/tooling skeleton, scenario placeholders, and Gate A evidence capture artifacts.
- **Validation:** Gate A capture completed; clean virtual-environment installation completed; `deadman`, 2 pytest tests, Ruff, and mypy pass.
- **Tooling note:** Ruflo instructions requested ToolSearch/MCP use for complex work, but ToolSearch exposed no Ruflo tools in this session.
- **Session ID:** `019f64d0-696b-7850-859b-5f15d6acc6e3`.
- **Commit links:** `3f0f781` D0 project baseline; `218d97d` Python package scaffold; `baeadf5` Gate A Codex JSONL evidence.

## 2026-07-15 — D1 detection baseline

- **Goal:** implement the first detector-ready pipeline slice without recovery actions.
- **Human decisions:** continue to the next phase, use parallel Codex agents, and make regular commits.
- **Codex contribution:** added runtime dependencies, typed domain records, Codex JSONL normalization, capability detection, SQLite evidence storage, process ownership observations, the pure `HUNG_PROCESS` detector, a Gate B hung-process fixture, and `deadman replay` for that fixture.
- **Validation:** `deadman`, `deadman replay scenarios/recordings/hung-process.jsonl`, pytest, Ruff, and mypy pass.
- **Tooling note:** attempted Ruflo ToolSearch again; no Ruflo MCP tools were exposed. Three requested sub-agents were spawned, but they produced no usable file output and were interrupted before local implementation continued.
- **Commit links:** `0a6f346` D1 dependencies; `a7afb15` JSONL evidence normalization; `79d1d0f` SQLite evidence persistence; `3b2f1a8` hung owned-process detection; `b10572b` hung fixture replay.

## 2026-07-15 — Offline MVP replay pipeline

- **Goal:** complete the judge-safe offline path through detect, diagnose, policy, simulated recovery, verify, and report.
- **Human decisions:** continue toward completion and keep making regular commits.
- **Codex contribution:** added the remaining pure detectors, fake evidence-bound diagnosis, deterministic policy validation, verification results, terminal reports, repeated-failure and session-handoff fixtures, `deadman demo`, and `deadman report`.
- **Validation:** `deadman`, all three `deadman replay` fixtures, `deadman demo`, `deadman report repeated-failure`, 29 pytest tests, Ruff, mypy, and `git diff --check` pass.
- **Remaining limitation:** live Codex supervision and real OpenAI Responses API diagnosis are still not wired; the completed path is deterministic offline replay.
- **Commit links:** `e79a115` progress and budget detectors; `8b98d8e` diagnosis policy decisions; `f163ce3` offline replay demo pipeline.

## 2026-07-15 — Backend recovery core

- **Goal:** continue core implementation while keeping app/CLI polish for last.
- **Human decisions:** continue implementation and defer app-facing work until the backend pieces are stronger.
- **Codex contribution:** added bounded recovery executors, checkpoint handoff writing under `.deadman/handoffs/`, subprocess JSONL capture with argument arrays, structured OpenAI Responses API diagnosis parsing, workspace progress fingerprinting, incident state transitions with a two-attempt cap, and expanded SQLite lifecycle persistence.
- **Validation:** `deadman demo`, 46 pytest tests, Ruff, mypy, and `git diff --check` pass.
- **Remaining limitation:** the CLI still exposes only replay/demo/report; live `deadman run` wiring is intentionally deferred until the app-facing slice.
- **Commit links:** `5366cc8` bounded recovery executors; `3f7739b` supervised subprocess JSONL capture; `c56c5f1` structured OpenAI diagnosis client; `c33c90b` workspace progress fingerprint; `d4b2de1` incident state machine; `44930ae` incident lifecycle persistence.

## 2026-07-15 — App-facing completion slice

- **Goal:** install requirements and finish the user-facing command surface after the backend core.
- **Human decisions:** start with requirements installation and finish the app-facing slice last.
- **Codex contribution:** refreshed the editable install from `pyproject.toml`, added a supervised completed-run pipeline, and exposed `deadman run -- <command>` with SQLite evidence persistence and command-output reporting.
- **Validation:** focused CLI tests, real `deadman run` smoke command, and requirements install passed before final full validation.
- **Remaining limitation:** `deadman run` records completed JSONL runs; live streaming intervention during an actively stuck process remains future work.
- **Commit links:** `892ade6` supervised run pipeline; `67d284f` supervised run command.

## 2026-07-15 — Terminal app surface

- **Goal:** replace minimal CLI summary lines with a terminal product surface closer to the spec.
- **Human decisions:** user clarified that a print-only CLI demo was not enough.
- **Codex contribution:** added Rich panel/table renderers for demo, replay, report, and run output while preserving the existing backend pipeline.
- **Validation:** 52 pytest tests, Ruff, mypy, `deadman demo`, and `deadman run` smoke pass.
- **Commit links:** `6ec4484` Rich terminal app surface.

## 2026-07-15 — Scope finalization

- **Goal:** reconcile the spec with implementation decisions and final submission materials.
- **Human decisions:** keep Python for the MVP, defer Rust to a future native wrapper/TUI shell, and keep Codex plugin/MCP companion roadmap-only.
- **Codex contribution:** updated `spec.md` with the Rust decision and added MIT licensing material.
- **Validation:** editable install, 52 pytest tests, Ruff, mypy, `deadman demo`, and `deadman run` smoke pass.

## 2026-07-16 — Live hung-child recovery path

- **Goal:** close the main spec gap so local testing can exercise a live observe -> detect -> diagnose -> recover -> verify loop.
- **Human decisions:** complete the project enough for testing, while preserving the approval-by-default safety rule.
- **Codex contribution:** added `deadman run --hung-timeout` live process-tree monitoring, `--auto-recover` policy-gated descendant termination, optional `--diagnosis openai --model gpt-5.6`, richer run summaries, focused live recovery tests, and refreshed README/AGENTS status.
- **Validation:** focused run/CLI tests passed during implementation; full validation recorded at handoff.

## 2026-07-18 — Spec alignment and validation pass

- **Goal:** fold the Codex implementation plan into `spec.md` and validate the implementation against it.
- **Human decisions:** use the attached implementation plan as the completion checklist while preserving the current MVP safety boundary: watch mode is observe-only unless process ownership can be proven.
- **Codex contribution:** added a spec alignment section covering operating modes, detector priorities, action-name compatibility, checkpoint handoff shape, storage tables, implementation phases, required tests, CLI surface, report contents, and the MVP-complete checklist.
- **Validation:** `pytest` passed with 74 tests outside the sandbox because process-tree inspection is sandbox-blocked; Ruff and mypy passed; `deadman demo`, all three replay fixtures, and a live `deadman run --hung-timeout 0.2 --auto-recover` smoke passed.
- **Safety note:** a sandboxed test run failed process-tree cases because `psutil` and `ps` could not inspect child processes; the same focused and full suites passed with normal OS process-inspection permissions.

## 2026-07-17 — Guided resume after live recovery

- **Goal:** make the live recovery loop continue a recovered Codex session instead of stopping immediately after descendant termination.
- **Human decisions:** user live-tested a hung Codex prompt and asked why the run exited after recovery and did not resume with guidance.
- **Codex contribution:** added `--resume-after-recovery`, which runs `codex exec resume <session-id> <guidance>` after verified recovery when a session id is available, plus run-summary fields, terminal output rows, tests, and README usage.
- **Validation:** focused run/CLI tests, Ruff, and mypy passed during implementation; full validation recorded at handoff.

## 2026-07-17 — Lingering Codex command recovery

- **Goal:** handle live Codex runs that exit successfully while leaving a reported background terminal command running.
- **Human decisions:** user live-tested `codex exec --json` prompts that left `command_execution` items in progress and observed Deadman reported `completed` instead of recovery.
- **Codex contribution:** detect completed JSONL traces with `item.type == command_execution`, `status == in_progress`, and `exit_code == null`; in approval mode report `awaiting_approval`, and with `--auto-recover` resume the Codex session with cleanup guidance.
- **Validation:** focused run/CLI tests, Ruff, and mypy passed during implementation; full validation recorded at handoff.

## 2026-07-17 — Interactive Codex CLI supervision

- **Goal:** support the agentic interactive Codex CLI, not only `codex exec --json`.
- **Human decisions:** user clarified that Deadman must work with the interactive coding-agent CLI surface as well as the non-interactive exec surface.
- **Codex contribution:** added `deadman agent -- <interactive command>`, a PTY wrapper that passes through terminal input/output while monitoring the launched agent process tree and terminating proven hung descendants when `--auto-recover` is set.
- **Validation:** focused agent/CLI tests, Ruff, and mypy passed during implementation; full validation recorded at handoff.

## 2026-07-17 — Guarded resume verification

- **Goal:** prevent a zero-exit resume without adapter completion from being reported as resolved.
- **Human decisions:** user live-tested a resume that returned zero but produced only one event and asked for guarded resume behavior.
- **Codex contribution:** automatic resume now retains an explicit safe Codex sandbox, forces JSONL output, refuses missing or unsafe sandbox modes, and requires a completion event before reporting `recovered_and_resumed`.
- **Validation:** focused run and CLI tests cover safe argument construction and zero-exit unverified resume escalation; full validation recorded at handoff.

## 2026-07-18 — Session foundation and observe-only watch

- **Goal:** adopt the expanded Deadman roadmap incrementally without weakening the working managed recovery path.
- **Human decisions:** preserve existing functionality, make attach mode observe-only, and deliver the session/storage foundation plus watch before expanding detectors.
- **Codex contribution:** added non-destructive schema v2 migration, session-scoped raw and normalized events, managed capture registration, persisted CLI discovery and tailing, explicit repository-bound pairing, `deadman watch`, capability reporting, sanitized fixtures, and architecture/event-contract documentation.
- **Safety:** attach mode exposes no process-control or recovery option because persisted session files do not prove PID ownership.
- **Validation:** migration, adapter, partial-line, idempotency, truncation, CLI pairing, observe-only safety, managed lifecycle, and full repository gates recorded at handoff.

## 2026-07-18 — Judge-friendly diagnosis credentials

- **Goal:** minimize live-demo setup without accessing or shipping private Codex authentication state.
- **Human decisions:** judges should be able to provide one API key through the shell or project `.env`; TUI credentials remain separate.
- **Codex contribution:** added automatic project `.env` loading with environment precedence, visible automatic fallback, explicit live-mode failure, `.env.example`, `deadman config check`, and credential-source tests.
- **Safety:** `.env` files are ignored, existing environment values are never overridden, and no key value is displayed or persisted by Deadman.

## 2026-07-20 — Fresh clone setup simplification

- **Goal:** remove the hidden assumption that a fresh clone already has `.venv/bin/deadman`.
- **Human decisions:** optimize the isolated interactive Codex TUI test path for least friction.
- **Codex contribution:** added `./scripts/deadman` as a self-bootstrapping CLI wrapper, `./scripts/setup --dev` for contributor installs, `./scripts/live-tui-smoke` for the isolated Codex TUI supervision scenario, and README quick-start instructions.

## 2026-07-20 — Interactive recovery target safety

- **Goal:** ensure the interactive TUI supervisor cannot terminate Codex because task text resembles a shell command.
- **Evidence:** a live TUI incident selected the Codex PID after the prompt mentioned Python, then terminated its descendant subtree.
- **Codex contribution:** classify Codex and known helper executables from argv structure, and identify recoverable user commands from their executable and flags rather than arbitrary prompt text.

## 2026-07-21 — Workflow-first README

- **Goal:** make the shipped CLI usable without reading implementation code or inferring which supervision mode applies.
- **Codex contribution:** rewrote the README around mode selection, real two-terminal recovery, per-command options, expected output, persisted evidence fields, status meanings, and the approval and ownership boundaries.

## 2026-07-21 — README validation and Codex narrative

- **Goal:** make the trust claim and Codex contribution legible to judges without fabricating production metrics or a feedback session ID.
- **Validation:** one isolated live attach recovery smoke completed; three healthy supervised controls produced zero signals and zero recovery actions.
- **Codex contribution:** documented the build, adversarial process-safety review, and runtime GPT boundary; the README instructs the submitter to capture the actual `/feedback` ID from the core-functionality thread.

## 2026-07-21 — Cross-platform supervision boundary

- **Goal:** prevent Unix-only PTY and pipe-polling code from breaking the complete CLI on Windows.
- **Codex contribution:** made POSIX PTY imports optional, kept `agent` explicitly macOS/Linux-only, and replaced `run --hung-timeout` pipe polling with reader threads so managed live supervision has a Windows-compatible I/O path. Added platform-focused tests and a Windows/macOS/Linux CI matrix; process actions still fail closed when ownership inspection is unavailable.
