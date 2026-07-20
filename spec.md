# Deadman — Final Build Specification

**OpenAI Build Week 2026 · Developer Tools · Solo MVP**
**Status:** Build-ready
**Public product name and CLI:** `Deadman` / `deadman`
**Submission deadline:** July 21, 2026, 5:00 PM PT (July 22, 5:30 AM IST)
**Internal ship target:** July 21, 2026, 9:00 PM IST

## 1. Product decision

### One-line pitch

> Deadman is a local recovery harness for Codex sessions: it detects evidence of a stuck run, asks GPT-5.6 to select a bounded recovery, verifies the outcome, and leaves an auditable incident record.

### Tagline

> **The session died. The task didn't.**

### User and job

The first user is a developer who runs Codex on a local repository and cannot continuously supervise it. Deadman helps that developer recover from a reproducible bad run without giving a second model unrestricted control of their machine.

The end-to-end product loop is deliberately narrow:

```text
Observe -> Detect -> Diagnose -> Recover -> Verify -> Report
```

Deadman is not a general agent platform, a hosted observability product, a replacement for Codex, or an autonomous code editor.

## 2. Product boundary and architecture law

**Architecture law — copy verbatim into `AGENTS.md`:**

> Deterministic code observes events, detects pathological states, authorizes actions, executes approved actions, and verifies outcomes. GPT-5.6 receives a compact evidence packet and recommends only a typed action. The model never receives arbitrary shell, process, filesystem-write, or session-control tools.

The product has three layers:

| Layer | Responsibility | Must not do |
| --- | --- | --- |
| Deterministic supervisor | Spawn/observe Codex, track the process tree, persist evidence, run detectors, enforce policy, execute and verify | Infer intent from prose or let an untrusted model command run |
| GPT-5.6 diagnostician | Classify ambiguous evidence, select a typed recovery, write grounded guidance or a handoff | Call shell tools, edit files, choose a PID, or override policy |
| Deterministic verifier | Decide whether objective recovery evidence exists; otherwise escalate | Mark recovery successful because the model says it is |

The initial product is a **terminal wrapper**, not a Codex plugin. A wrapper owns the launched process tree and works even when the supervised Codex session cannot call an MCP tool. A Codex plugin/MCP companion is roadmap-only.

### Current delivery slice: foundation and watch

The current incremental slice preserves managed recovery and adds session-scoped evidence plus `deadman watch` for explicitly paired persisted interactive CLI sessions. Persisted session metadata does not prove process ownership, so watch mode is observe-only: it cannot terminate a PID, resume Codex, or execute another recovery action. The observed compatibility contract is recorded in `docs/codex-event-contract.md`.

The MVP implementation remains Python. Rust is a strong future option for a native wrapper/TUI and process-supervision shell, but it is not part of the Build Week MVP rewrite. If Rust is added later, it should start as a thin `clap` + `ratatui`/`crossterm` frontend around the existing JSON/SQLite contract rather than replacing the tested detector, policy, and diagnosis core immediately.

## 3. Evidence model and compatibility gates

### Runtime invocation

```bash
deadman run -- codex exec --json --sandbox workspace-write "<task>"
```

Deadman launches `codex exec`, captures stdout as JSON Lines, preserves stderr separately, and records a local SQLite trace. The current local Codex CLI exposes `codex exec --json` and `codex exec resume <session-id> <prompt>`; nevertheless, **event fields are not a stable application contract until verified against the installed version**.

### Gate A — prove the adapter before building detectors

Run one harmless, persisted Codex task and save the raw JSONL. The adapter must report which of these capabilities it observed:

| Capability | If present | If absent |
| --- | --- | --- |
| Persisted session ID | Enable guided resume | Disable automatic resume and show the limitation |
| Command/tool completion events | Enable loop and error-signature detectors | Use process observations plus replay fixtures only |
| Usage/token fields | Enable session-budget telemetry | Display `unknown`; never estimate a model context percentage |
| File-change events | Enrich progress evidence | Use Git status/diff fingerprints |

Do not claim to know Codex's internal context-window percentage from transcript size or character count. The product can track a **Deadman session budget** only when usage telemetry is actually available. Otherwise, context handoff is manual/replay-only.

### Gate B — prove each demo fixture before implementing recovery

Every scenario must emit a deterministic fixture trace that triggers exactly one target detector. A scenario is not demo-ready until it also passes through `deadman replay` without a live model or API key.

## 4. MVP: four signals, three recovery paths

The scope below is final. Anything outside it is roadmap work.

### 4.1 Signals

Each detector produces a typed `Signal` containing a severity, evidence references, detector configuration, and a stable fingerprint. Detectors may open one incident; they must not execute recovery directly.

| Signal | Trigger rule | Guard against false positives |
| --- | --- | --- |
| `HUNG_PROCESS` | A proven descendant of the launched Codex process is alive, has no stdout/stderr activity for the configured timeout (default 60 s), and has not exited | Classify a process as likely persistent when a configured port is listening or its output matches a user-configured ready/watch pattern; default to escalation when uncertain |
| `REPEATED_FAILURE` | The same normalized command/tool failure signature occurs at least 3 times with an unchanged workspace fingerprint and unchanged test summary | Do not fire when a new diff, a changed test result, or a new assistant hypothesis is observed |
| `NO_PROGRESS` | At least 4 completed attempts show no workspace-fingerprint or test-summary change while the run remains active | Use it only when the adapter can identify completed attempts; otherwise replay-only |
| `SESSION_BUDGET_RISK` | Available usage telemetry crosses a **user-defined** session budget threshold, or a manual checkpoint is requested | This is not a claim about the model's hidden context window; it is disabled without telemetry |

`RUNAWAY_TOOL_LOOP`, period-cycle detection, token-rate anomaly detection, and cross-tool error spirals are explicitly deferred. They are useful extensions but would weaken the deadline-critical recovery path.

### 4.2 Recovery actions

```text
RecoveryAction =
  | OBSERVE
  | TERMINATE_DESCENDANT_PROCESS
  | CANCEL_AND_RESUME
  | CHECKPOINT_AND_RESPAWN
  | HALT_AND_ESCALATE
```

All actions are auditable and idempotent per incident/action fingerprint. No automatic Git rollback is in scope.

| Action | What deterministic code does | Approval default |
| --- | --- | --- |
| `OBSERVE` | Records the diagnosis; takes no action | Automatic |
| `TERMINATE_DESCENDANT_PROCESS` | Sends a bounded termination sequence only to a live PID proven to descend from the supervised root; waits for the parent run to react | User approval in normal mode; automatic only with explicit `--auto-recover` |
| `CANCEL_AND_RESUME` | Stops the supervised Codex run, then resumes the persisted session with GPT-5.6 guidance grounded in evidence | User approval in normal mode; automatic only with `--auto-recover` and a known session ID |
| `CHECKPOINT_AND_RESPAWN` | Writes an untracked handoff under `.deadman/handoffs/`, stops the current run, and starts a **fresh** Codex session with the original task plus the handoff | User approval in normal mode; automatic only with `--auto-recover` |
| `HALT_AND_ESCALATE` | Stops attempting recovery and prints the incident report and next recommended action | Automatic |

`--auto-recover` is opt-in and prominently shown in the TUI. A fresh install runs in observe/approval mode. This is a safety requirement, not a missing feature.

### 4.3 Recovery and verification contract

An incident follows this state machine:

```text
OPEN -> DIAGNOSING -> AWAITING_APPROVAL? -> RECOVERING -> VERIFYING
                                                         |-> RESOLVED
                                                         `-> ESCALATED
```

Every state transition records its timestamp, reason, actor, evidence IDs, and relevant action fingerprint.

Recovery is verified only when, within the configured verification window, Deadman observes both:

1. a changed progress fingerprint, **and**
2. one success signal: a reduced failing-test count, a successful target command, a clean agent completion, or an explicit user confirmation.

If the action fails, times out, or yields no verification evidence, Deadman transitions to `ESCALATED`. It must never retry an action indefinitely and must perform at most **two** recovery attempts for one incident.

Automatic Codex resume must retain an explicit `read-only` or `workspace-write` sandbox and request JSONL output. A zero exit code without an observed adapter completion event is not successful verification; Deadman must escalate it.

## 5. GPT-5.6 is load-bearing, bounded, and measurable

Deadman calls the OpenAI Responses API only after a deterministic signal opens an incident. Use the competition-required GPT-5.6 model family; start with `gpt-5.6` at `reasoning.effort: "medium"` and make model/effort configurable for evaluation. The model alias routes to the current flagship GPT-5.6 model; record the resolved model identifier returned by the API in every incident.

The call is load-bearing in two places:

1. **Diagnostician:** given compact evidence, select `OBSERVE`, `TERMINATE_DESCENDANT_PROCESS`, `CANCEL_AND_RESUME`, `CHECKPOINT_AND_RESPAWN`, or `HALT_AND_ESCALATE` and write grounding guidance.
2. **Handoff distiller:** when checkpointing, produce the fresh-session handoff: goal, completed work, verified facts, decisions, open questions, and the single next step.

Use strict structured output validated by Pydantic. The model receives no tools and cannot address raw PIDs or filesystem paths not already represented in the evidence object.

```json
{
  "classification": "HUNG_PROCESS",
  "confidence": 0.0,
  "recommended_action": "CANCEL_AND_RESUME",
  "rationale": "...",
  "evidence_ids": ["evt_017", "proc_004"],
  "guidance": "Stop rerunning the blocked command. Inspect ...",
  "requires_human_approval": true
}
```

The policy engine rejects a response when it names unknown evidence, an unavailable action, or an action prohibited by mode/policy. This makes GPT-5.6 meaningful without allowing it to control the workstation.

### Cost discipline

- No model call in a healthy session.
- At most one diagnostician call per incident, plus one handoff call only for an approved checkpoint.
- A cooldown prevents the same fingerprint from reopening immediately.
- Store API usage returned by the response and show it beside the estimated saved attempts; do not invent dollar savings.

### Shipped credential behavior

Live diagnosis checks an existing `OPENAI_API_KEY` first, then loads only the current repository's ignored `.env` without overriding the shell. Automatic mode visibly falls back to the deterministic fixture client when no key exists; explicit OpenAI mode fails fast. Deadman never reads Codex TUI authentication caches. `deadman config check` reports readiness without displaying secret values, and offline replay remains credential-free.

## 6. Technical design

### Stack

| Area | Choice | Reason |
| --- | --- | --- |
| Runtime | Python 3.11+ | Fastest path to safe process management and a single distributable CLI |
| CLI/TUI | Typer + Rich | Terminal-native command surface and readable live status |
| Domain validation | Pydantic | Typed, validated boundaries for event, signal, diagnosis, and policy data |
| Process inspection | `psutil` | Cross-platform process tree, liveness, and port inspection primitives |
| Persistence | SQLite (`sqlite3`) | Zero-infrastructure incident store and replay source |
| Model client | Official OpenAI Python SDK / Responses API | GPT-5.6 structured diagnosis and handoff generation |
| Tests | pytest | Fast unit, fixture, and scenario tests |
| Future native shell | Rust (`clap`, `ratatui`, `crossterm`) | Roadmap option for a single-binary wrapper/TUI after MVP behavior is stable |

No Docker, web dashboard, Postgres, background service, login system, cloud deployment, Slack integration, Rust rewrite, or Codex plugin belongs in the MVP.

### Components

```text
apps/cli               commands: run, agent, watch, demo, replay, report
deadman/adapter         subprocess and persisted-session event adapters
deadman/watch           observe-only persisted-session tail loop
deadman/monitor         process tree and output/liveness observations
deadman/domain          Pydantic models and incident state machine
deadman/detectors       four pure detectors
deadman/store           SQLite schema and evidence repository
deadman/diagnosis       Responses API client; strict schemas; fake client
deadman/policy          allowlist, approval gate, idempotency, limits
deadman/executor        safe termination, cancellation/resume, respawn
deadman/verify          progress and success-signal verification
scenarios/              source fixtures and recorded replay traces
tests/                  unit, integration, and replay tests
```

### Persisted records

SQLite stores raw events, normalized events, process observations, workspace snapshots, signals, incidents, transitions, diagnoses, actions, verification results, and reports. Every evidence-bearing record gets a stable ID. Raw JSONL is retained as an incident attachment, not treated as a schema promise.

### Workspace progress fingerprint

The fingerprint is a hash over:

- `git status --porcelain`;
- the names and content hashes of modified tracked files (not their contents);
- latest parsed test summary, when one is available; and
- the current target-command exit result, when one is available.

It is an input to detection and verification, not proof that a code change is correct.

## 7. CLI and judge path

```bash
# Observe a real Codex run. Default: asks before any intervention.
deadman run -- codex exec --json --sandbox workspace-write "Fix the failing test"

# Explicitly allow the policy-approved automatic actions for a controlled run.
deadman run --auto-recover -- codex exec --json "Fix the fixture task"

# Run all bundled deterministic demonstrations.
deadman demo

# Re-run an incident pipeline without Codex, an OpenAI key, or network access.
deadman replay scenarios/recordings/hung-process.jsonl

# Produce a self-contained terminal report; HTML is post-MVP.
deadman report <incident-id>
```

`deadman demo` contains three deterministic scenarios:

1. **Hung child process:** a controlled command blocks; Deadman proves descendant ownership, asks for or applies the allowed recovery, then verifies the fixture completes.
2. **Repeated failure without progress:** a controlled command returns the same failure while the workspace and test summary remain unchanged; Deadman resumes with evidence-grounded guidance.
3. **Session handoff:** a recorded usage-threshold fixture or manual checkpoint triggers GPT-5.6 handoff generation and a fresh seeded run. If the installed CLI exposes no usable usage field, the live threshold view is labelled unavailable and this scenario is demonstrated through replay/manual checkpoint only.

The replay path is the judge-safe contract. It must exercise the exact normalizer, detector, diagnosis fixture, policy, executor simulator, verifier, and report renderer used by the live path.

## 8. Safety and correctness requirements

- Spawn processes with argument arrays; never shell-interpolate user tasks or model text.
- Terminate only a PID freshly proven to be a descendant of the supervised root. Re-check immediately before signalling.
- Never signal the current Python process, its parent, PID 1, or a protected PID list.
- Use a graceful terminate timeout before a forced kill; record both attempts.
- Treat malformed JSONL and unknown event types as retained evidence, not fatal parser errors.
- Never let a diagnosis response invoke a process action directly.
- Never write `HANDOFF.md` into the user's tracked project root. Use `.deadman/handoffs/` and include it in `.gitignore` during demo setup.
- Cap incident recovery attempts at two and use an exponential cooldown for repeat fingerprints.
- Default to approval when a capability, process ownership, or policy condition is uncertain.

## 9. Definition of done

Deadman is submission-ready only when all of the following are true:

- `deadman demo` completes all three scenarios on the target machine.
- `deadman replay` completes all shipped traces offline, with deterministic expected outcomes.
- The live hung-process scenario demonstrates detection, a GPT-5.6 diagnosis, a bounded recovery, and deterministic verification.
- Tests cover every detector's positive and false-positive path, policy deny paths, idempotency, malformed JSONL, and process-ownership checks.
- A fresh clone can install and run replay using only the README.
- `pytest`, lint, and type checking pass from a clean environment.
- The README explains how Codex built the project and how Codex plus GPT-5.6 power it at runtime.
- The video shows only delivered behavior and includes the required spoken Codex and GPT-5.6 explanation.

## 10. Build plan — July 15–21

The build completes by Monday night. Tuesday is reserved for validation and submission; no new features.

| Day | Date | Deliverable and exit criterion |
| --- | --- | --- |
| D0 | Wed Jul 15 | Create repo, `AGENTS.md`, `SPEC.md`, package skeleton, and `CODEX_LOG.md`. Pass Gate A using a harmless persisted `codex exec --json` run. Create all three deterministic raw traces for Gate B. |
| D1 | Thu Jul 16 | Implement normalizer, capability report, SQLite evidence store, process ownership monitor, and the hung-process detector. Demo fixture 1 lights up live. |
| D2 | Fri Jul 17 | Implement incident state machine, fake/real GPT-5.6 diagnostician, strict schema validation, policy gate, and safe termination executor. Hung fixture reaches `RESOLVED` or a correct `ESCALATED` state. |
| D3 | Sat Jul 18 | Implement repeated-failure/no-progress detectors, `CANCEL_AND_RESUME`, workspace snapshots, and verification. Fixture 2 recovers end to end. Record an insurance screen capture. |
| D4 | Sun Jul 19 | Implement manual/session-budget checkpoint and fresh-session handoff. Build replay mode and terminal report. All three recordings replay offline. |
| D5 | Mon Jul 20 | Product polish, README, installation path, clean-clone rehearsal, final tests, and video recording/editing/upload. Freeze scope. |
| D6 | Tue Jul 21 | Fresh-clone verification, Devpost fields, `/feedback` session ID, final video/repo links, and submit by the internal target. |

### Cut order

If schedule slips, cut in this order:

1. Rich gauges/animation; keep clear plain terminal output.
2. Live session-budget telemetry; retain manual checkpoint + replay fixture.
3. Automated `CANCEL_AND_RESUME`; retain approval flow and report.
4. Polished HTML report; terminal report remains.

Never cut: process-ownership safety, evidence-bound GPT-5.6 diagnosis, policy enforcement, verification/escalation, or offline replay.

## 11. Demo and video contract

Target length: 2:40–2:55. Record against the deterministic demo; do not depend on a spontaneous live model failure.

| Time | Beat | Proof on screen |
| --- | --- | --- |
| 0:00–0:20 | Problem | A Codex task is blocked on a child process; developer has no trustworthy recovery loop. |
| 0:20–0:55 | Recovery 1 | Deadman shows process ownership and evidence, GPT-5.6 selects a policy-checked recovery, verification shows task progress. |
| 0:55–1:25 | Recovery 2 | Same failure, unchanged workspace, same test result -> evidence-grounded resume -> changed outcome. |
| 1:25–1:55 | Handoff | Session budget/manual checkpoint -> GPT-5.6 handoff -> fresh session starts from concrete state. State clearly when shown through replay. |
| 1:55–2:20 | Trust | Incident timeline, action policy, verification, and a concise prevention recommendation. |
| 2:20–2:55 | Required contribution | Say plainly: Codex built and reviewed Deadman; GPT-5.6 performs the constrained runtime diagnosis and handoff; judges can run `deadman replay` without credentials. |

Do not display unmeasured "tokens saved," a fabricated context percentage, an automatic recovery that actually used manual intervention, or a plugin that is not shipped.

## 12. Submission materials

- Public repository with MIT license and focused dated commits.
- README: install, prerequisites, `demo`, offline `replay`, safety model, troubleshooting, and a transparent Codex/GPT-5.6 collaboration log.
- `CODEX_LOG.md`: goals, session IDs, Codex contributions, human decisions, commands run, validation results, and commit links.
- `/feedback` session ID from the primary build session, captured before form submission.
- Public video under three minutes with audible explanation of both Codex and GPT-5.6.
- Devpost listing under Developer Tools, with the runnable/replay path front and centre.

## 13. Implementation plan alignment

This section incorporates the Codex implementation plan as the execution checklist for the current build. Where the plan is broader than the deadline-critical MVP, this spec keeps the safer narrowed behavior as the controlling requirement.

### Product lifecycle

The implementation plan names the lifecycle as:

```text
Detect -> Diagnose -> Recover -> Verify -> Prevent
```

The Build Week demo maps this to the product loop already defined above:

```text
Observe -> Detect -> Diagnose -> Recover -> Verify -> Report
```

`Prevent` is delivered as report guidance, handoff guidance, and documented safety recommendations. Automatic prevention-rule edits are roadmap-only.

### Operating modes

| Mode | Command | MVP requirement | Safety boundary |
| --- | --- | --- | --- |
| Managed mode | `deadman run -- <codex command>` | Launch and own the Codex process tree, capture JSONL evidence, detect an owned hung child, diagnose, recover, and verify | Destructive recovery is allowed only for proven descendants and only with policy approval or explicit `--auto-recover` |
| Interactive managed mode | `deadman agent -- <interactive command>` | Run an interactive coding-agent CLI inside a supervised PTY and observe its descendants | Can terminate only proven hung descendants when `--auto-recover` is set |
| Attach/watch mode | `deadman watch` | Pair with one persisted Codex CLI session, ingest append-only session events, and render observe-only status | Persisted events do not prove PID ownership, so watch mode cannot terminate, resume, or respawn |
| Replay mode | `deadman replay <trace>` | Run detector, diagnosis, policy, verification, and reporting offline without Codex, network, or OpenAI credentials | Must remain deterministic and judge-safe |

The broader plan allows attach-mode interventions when ownership is proven. The current observed Codex persisted-event contract does not prove that ownership, so this MVP intentionally falls back to observe-only watch behavior.

### Detector priorities

The implementation plan calls the no-progress loop the primary detector and names these failure classes:

1. no-progress loop;
2. repeated failure;
3. hung execution;
4. context continuity risk.

The shipped signal names remain:

```text
NO_PROGRESS
REPEATED_FAILURE
HUNG_PROCESS
SESSION_BUDGET_RISK
```

Repeated-error cycles, A-B-A-B loops, and richer no-progress features are valid detector extensions only when they have fixture evidence and false-positive tests.

### Recovery action compatibility

The implementation plan's action names map to the current typed enum as follows:

| Implementation-plan action | Current MVP action |
| --- | --- |
| `OBSERVE` | `OBSERVE` |
| `ALERT` | `HALT_AND_ESCALATE` or policy-blocked approval output |
| `RESUME_WITH_GUIDANCE` | `CANCEL_AND_RESUME` |
| `TERMINATE_OWNED_CHILD` | `TERMINATE_DESCENDANT_PROCESS` |
| `CHECKPOINT_AND_RESPAWN` | `CHECKPOINT_AND_RESPAWN` |
| `HALT_AND_ESCALATE` | `HALT_AND_ESCALATE` |

The enum is not renamed during the MVP because fixtures, stored diagnoses, tests, and report output already depend on the current names. Any rename requires a compatibility migration.

### Checkpoint handoff shape

`CHECKPOINT_AND_RESPAWN` must write an untracked handoff under `.deadman/handoffs/`. The target handoff structure is:

```markdown
# Deadman Handoff

## Original goal

## Work completed

## Current repository state

## Important decisions

## Failed approaches

## Active failure

## Open tasks

## Recommended next step

## Verification command
```

Every claim must be grounded in stored evidence, repository state, recent relevant transcript, or task metadata.

### Storage model

The canonical SQLite model includes:

```text
sessions
events
workspace_snapshots
process_observations
signals
incidents
incident_transitions
diagnoses
policy_decisions
actions
verifications
reports
```

Legacy tables may remain during compatibility migration, but new evidence should be session-scoped where practical. Every evidence reference used in diagnosis must resolve to a stored record or be rejected by policy/validation.

### Implementation phases

| Phase | Scope | MVP status target |
| --- | --- | --- |
| 0 | Verify Codex JSONL/session assumptions and document unsupported fields | Required |
| 1 | Event ingestion, normalization, malformed-line handling, SQLite persistence, fixtures | Required |
| 2 | Progress monitoring: Git fingerprint, command/test/error/process/usage observations | Required for replay; live use may be capability-gated |
| 3 | First detectors with thresholds, evidence, severity, false-positive tests, replay fixtures | Required |
| 4 | Incident lifecycle, transitions, duplicate handling, cooldowns, audit trail, limits | Required |
| 5 | GPT-5.6 diagnosis, compact evidence packet, structured output, validation, fake client | Required |
| 6 | Policy and recovery actions, including safe termination and checkpoint handoff | Required for selected MVP actions |
| 7 | Post-action verification, second-attempt limits, automatic escalation | Required |
| 8 | Attach/watch mode with explicit pairing and observe-only fallback | Required as observe-only |
| 9 | Replay/demo scenarios for hung process, repeated failure/no-progress, and checkpoint/context risk | Required |
| 10 | Companion MCP tools and recovery skill | Roadmap unless managed recovery, verification, and submission materials are already complete |

### Required tests

Unit and integration coverage should include:

- JSONL parsing, session-event normalization, malformed and unknown events;
- workspace fingerprint comparison and progress verification;
- detector thresholds and false-positive paths;
- repeated failure, no-progress, hung process, and session-budget/context-risk replay fixtures;
- process-ownership policy and unrelated-PID refusal;
- action idempotency, stale/duplicate action rejection, and intervention limits;
- incident state transitions and escalation;
- evidence-reference validation for model output;
- checkpoint generation;
- attach/watch observe-only behavior when ownership confidence is insufficient;
- replay equivalence without live Codex or OpenAI credentials.

### CLI surface

The first release should stay small:

```bash
deadman run -- <codex command>
deadman agent -- <interactive command>
deadman watch
deadman demo
deadman replay <scenario-or-trace>
deadman report <incident-id>
```

`deadman status`, `deadman incidents`, and `deadman config check` are useful follow-ons, but are not required for the Build Week submission unless the core demo is already frozen.

### Report contents

Incident reports should include the session/task when known, classification, timeline, detector evidence, diagnosis confidence, approved and rejected actions, recovery attempt, verification evidence, final outcome, and prevention recommendation. Estimated tokens or time avoided may be shown only when the estimate is labelled and the calculation is explained.

### Definition of MVP complete

The implementation-plan MVP is complete only when:

1. Deadman supervises a managed Codex run.
2. It detects at least three deterministic failure scenarios.
3. GPT-5.6 diagnoses an incident from compact cited evidence.
4. Policy code authorizes a typed action.
5. Deadman performs a real bounded recovery.
6. Verification proves whether progress resumed.
7. A failed recovery escalates safely.
8. A context-risk incident can create a usable handoff.
9. Judges can replay incidents without live credentials.
10. Attach mode can monitor one paired Codex TUI session from another terminal.
11. The README clearly distinguishes managed guarantees from attach-mode limitations.
12. The video shows only functionality that exists.

## 14. Roadmap (not part of the submission)

- A thin `deadman-mcp` companion exposing read-only status and a policy-gated checkpoint request.
- Additional adapter support for other coding-agent CLIs.
- Periodic tool-cycle and error-spiral detectors.
- A self-contained HTML report and team/CI integrations.
- Configurable prevention-rule suggestions for `AGENTS.md`; never auto-apply them in the MVP.

## Appendix A — decisions made while finalizing this spec

| Change | Decision | Why |
| --- | --- | --- |
| Naming | Finalize **Deadman**; remove alternatives | Preserves momentum and prevents branding churn. |
| Form factor | Local wrapper first; plugin/MCP deferred | The external supervisor owns the failure domain and is credible on the deadline. |
| Rust | Defer Rust to a future native shell | Rust is attractive for process supervision and distribution, but a rewrite would add deadline risk; Python remains fastest for the MVP core and OpenAI SDK integration. |
| Telemetry | Capability-gated; no transcript-byte context estimate | Avoids claiming hidden context-window data that may not be emitted by the CLI. |
| Detectors | Reduce from six to four | Prioritizes recovery, verification, and reproducible demos over taxonomy breadth. |
| Automation | Approval by default; auto-recovery requires explicit flag | Safer and more believable for process/session control. |
| Context story | Reframe as session-budget/manual checkpoint plus fresh handoff | Keeps the flagship narrative without relying on undocumented context telemetry. |
| Reports | Terminal report is MVP; HTML is roadmap | Protects the judge path and core reliability work. |
| Schedule | Freeze Monday; Tuesday only validates and submits | Removes date/day ambiguity and preserves submission margin. |

## Appendix B — sources to re-check before publishing

- [OpenAI Build Week](https://openai.com/build-week/) for high-level dates and judging framing.
- [OpenAI Build Week on Devpost](https://openai.devpost.com/) for the controlling rules, tracks, and required submission fields.
- [GPT-5.6 model guidance](https://developers.openai.com/api/docs/guides/latest-model.md) for current model aliases and Responses API guidance.
