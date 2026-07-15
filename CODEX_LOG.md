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
