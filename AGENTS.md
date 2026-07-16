# Deadman contributor guide

## Architecture law

> Deterministic code observes events, detects pathological states, authorizes actions, executes approved actions, and verifies outcomes. GPT-5.6 receives a compact evidence packet and recommends only a typed action. The model never receives arbitrary shell, process, filesystem-write, or session-control tools.

## Working rules

- Treat `spec.md` as the source of truth. Build only the current delivery slice.
- Keep model output evidence-bound and validated. A model recommendation is never permission to perform an action.
- Default to escalation when process ownership, adapter capability, evidence, or policy is uncertain.
- Never shell-interpolate task text or model output. Process launches use argument arrays.
- Preserve malformed or unknown adapter events as evidence; do not silently discard them.
- Make small changes with focused tests. Run `pytest`, `ruff check .`, and `mypy .` before handing work off.
- Add a concise entry to `CODEX_LOG.md` for material implementation, validation, and human decisions.

## Current status

The repository now includes the deterministic MVP core: adapter evidence capture, replay fixtures, pure detectors, policy checks, bounded recovery executors, verification, SQLite persistence, terminal reports, and a live `deadman run` hung-child recovery path. New intervention behavior still needs a fixture and focused tests before being treated as supported.
