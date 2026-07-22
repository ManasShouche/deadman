# Deadman

> The session died. The task didn't.

A local safety supervisor that watches an autonomous coding agent from outside the session, recovers only what it can prove is safe to touch, and records every intervention.

## Inspiration

Autonomous coding agents can work for long periods, but a single silent child process, wedged development server, or unbounded retry loop can stop all useful progress. The agent may still appear active while it is only waiting. Developers then return to a stalled session, wasted time, and no trustworthy way to recover it without killing the entire agent.

We built Deadman around one question: how can an independent supervisor detect that an autonomous coding loop is genuinely stuck, recover only what is safe to recover, and prove that the intervention worked?

## What it does

Deadman is a local safety supervisor for Codex coding sessions. Its control loop is:

**Observe -> Detect -> Diagnose -> Recover -> Verify -> Report**

Deterministic code watches session events and operating-system process trees. When a detector finds a supported failure, Deadman sends GPT-5.6 a compact evidence packet. The model can recommend one typed action, but it receives no shell, filesystem, process-control, or session-control tools.

Every recommendation must pass deterministic policy and process-ownership checks. Deadman can then terminate only a freshly proven descendant process, verify that the failure was resolved, and store the complete evidence chain in SQLite. If ownership or verification is uncertain, it refuses the action and escalates instead.

Deadman supports several workflows:

- `deadman run` launches and supervises a non-interactive command such as `codex exec --json`.
- `deadman agent` launches an interactive Codex TUI inside a supervised PTY on macOS and Linux.
- `deadman attach` discovers and supervises a Codex TUI already running in another terminal in the same repository.
- `deadman watch` reads persisted Codex session evidence without controlling processes.
- `deadman replay`, `deadman demo`, and `deadman report` provide deterministic, credential-free evaluation paths.

Automatic recovery is off by default. It must be explicitly enabled with `--auto-recover`.

## How we built it

We used Codex throughout both product design and implementation. A Codex web planning thread helped us explore the failure model, reject unsafe plugin-style control, and choose an independent supervisor architecture. The main Codex implementation thread then helped build and repeatedly test the adapters, detectors, typed diagnosis schema, policy engine, process executor, verification gates, SQLite incident state machine, CLI modes, replay fixtures, reports, and cross-platform behavior.

The system is written in Python using Typer for the CLI, Rich for terminal output, Pydantic for strict model-response validation, SQLite for durable evidence, and `psutil` for process ownership and recovery. Live diagnosis uses the OpenAI Responses API with GPT-5.6. Deterministic replay and fixture diagnosis keep the core evaluation path usable without credentials.

The architecture deliberately separates intelligence from authority. GPT-5.6 interprets bounded evidence and recommends an action. Deterministic code decides whether that action is permitted, executes it, and verifies the result.

## Challenges we ran into

The hardest problem was safe process identity. Early process classification could mistake the Codex root for a Python-related target when the prompt itself contained the word `Python`. We fixed this by classifying executable identity and proving ancestry from the live Codex root instead of relying on command text.

Process ownership can also change between detection and recovery. A child may exit, become a zombie, or be reparented before Deadman acts. Deadman therefore rechecks ownership immediately before intervention. This occasionally produces an escalation instead of a recovery, but that is the correct outcome when safety cannot be proven.

Interactive terminal supervision introduced additional challenges: PTY sizing, ANSI output, nested process trees, terminal passthrough, and keeping the Codex TUI alive after recovering its hung tool process. We also had to distinguish persisted session evidence from live process ownership. A session file is useful for observation, but it is not sufficient authority to terminate a process.

Cross-platform support required a clear boundary. The core data model, replay, reporting, `watch`, `attach`, and managed `run` workflows support macOS, Linux, and Windows. The PTY-backed `agent` command remains macOS/Linux-only because Windows requires a separate ConPTY implementation.

## Accomplishments that we're proud of

We demonstrated a real two-terminal recovery against a live Codex TUI. Codex started a silent Python parent and sleeping child. Deadman attached from another terminal, detected the hung process, obtained a typed diagnosis, proved ownership, terminated the two-process descendant tree, verified resolution, and recorded the incident while the Codex TUI remained open.

We are equally proud of the refusal path. During a live package-install test, the target changed before intervention. Deadman refused to terminate it because it was no longer a proven descendant and recorded an escalated incident. Safe refusal is a product feature, not a failed demo.

Other completed work includes:

- Strict evidence-reference validation and typed GPT-5.6 output.
- Automatic recovery disabled by default.
- Verification that can fail and force escalation.
- Durable incident timelines and terminal reports.
- Credential-free replay and demo workflows for judges.
- Live supervision of Codex sessions launched either by Deadman or independently.
- A test suite covering detection, policy, ownership, recovery, verification, persistence, CLI behavior, and platform boundaries.

## What we learned

An agent saying that it is working is not the same as measurable progress. Reliable supervision must use independent evidence from events, time thresholds, and the operating-system process tree.

We also learned that diagnosis and authority should remain separate. A model is useful for interpreting evidence and selecting among constrained recovery strategies, but deterministic policy must retain control of every side effect.

Finally, escalation is a valid recovery outcome. A supervisor that always acts is dangerous. A trustworthy supervisor must be able to say, "I detected a problem, but I cannot prove that this action is safe."

## What's next for Deadman

The next version will add a dedicated progress ledger and live monitor UI for multiple concurrent Codex sessions, with signal thresholds, policy decisions, verification state, and incident timelines visible in one place. We also plan workload-aware timeout policies so long installs and builds are not treated like silent synthetic hangs.

Further work includes committed failed-verification scenarios, richer postmortem generation, prevention-rule proposals after verified recovery, budget controls for long autonomous runs, and native Windows ConPTY support for interactive supervision.

The long-term goal is for Deadman to become a dependable local control layer for long-running autonomous coding workflows: independent of the agent, conservative about authority, and accountable for every intervention.

## Try it (judge quickstart)

No hosted service, account, or credentials are required for the judge path. Deadman is a local CLI developer tool; the deterministic demo and the live process-supervision smoke test run without Codex or an OpenAI API key.

**Supported platforms:** macOS and Linux are fully supported, including the PTY-backed `agent` command. On Windows, the data model plus the `replay`, `demo`, `report`, `watch`, `attach`, and managed `run` paths work; only the interactive `agent` PTY is unsupported.

**Credential-free quick test:**

```bash
git clone https://github.com/ManasShouche/deadman
cd deadman
./scripts/deadman config check      # environment readiness; no secret values are shown
./scripts/deadman demo              # three recorded failure -> recovery scenarios, all RESOLVED
./scripts/live-attach-smoke         # live process discovery, hung detection, recovery, verification
```

Expected: `demo` prints three scenarios ending in `RESOLVED`; `live-attach-smoke` ends with one `RESOLVED` incident and `signals / diagnoses / action_results / verification_results = 1`. `./scripts/deadman` bootstraps a virtual environment on first run.

Deterministic, offline replay of a single incident:

```bash
./scripts/deadman replay scenarios/recordings/hung-process.jsonl
```

**Optional live GPT-5.6 diagnosis** (uses the judge's own key, never Codex's authentication):

```bash
cp .env.example .env         # add OPENAI_API_KEY=sk-...
./scripts/deadman config check
```

Then add `--diagnosis openai --model gpt-5.6` to `deadman run` or `deadman attach`. Without a key, Deadman visibly falls back to deterministic fixture diagnosis, so every path above still runs.
