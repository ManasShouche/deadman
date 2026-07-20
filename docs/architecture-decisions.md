# Architecture decisions

## ADR-001: Attach mode is observe-only

Persisted Codex events identify a session and repository but do not prove which live PID owns that session. `deadman watch` may ingest and report those events, but it may not signal processes, resume sessions, or execute recovery. Destructive actions remain available only when Deadman launched and registered the process tree.

## ADR-002: Schema v2 is non-destructive

Session-scoped `sessions`, `event_sources`, and `events` tables are added beside the original evidence tables. Existing raw evidence is copied into a synthetic `legacy-unscoped` session and is not deleted. Legacy tables remain readable during the compatibility period.

## ADR-003: Preserve the current recovery action names

The current recovery enum remains unchanged for the foundation milestone to avoid destabilizing managed recovery and replay fixtures. Renaming actions to the expanded roadmap union requires an explicit compatibility migration for fixtures, stored diagnoses, and reports and is deferred to the recovery expansion milestone.

## ADR-004: No package-wide reorganization

The persisted-session adapter is added to the existing adapter boundary and watch orchestration is kept small. Moving every module to the proposed long-term directory layout provides no behavioral value for this milestone and would obscure safety-relevant changes.
