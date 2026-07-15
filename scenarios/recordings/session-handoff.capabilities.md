# Session handoff fixture

- **Purpose:** Gate B fixture for the `SESSION_BUDGET_RISK` detector.
- **Expected detector:** exactly one `SESSION_BUDGET_RISK` signal from observed usage telemetry.
- **Recovery:** replay simulates `CHECKPOINT_AND_RESPAWN`.
- **Verification:** changed progress fingerprint plus handoff-written success evidence.
