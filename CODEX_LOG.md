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
