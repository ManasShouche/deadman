# Repeated failure fixture

- **Purpose:** Gate B fixture for the `REPEATED_FAILURE` detector.
- **Expected detector:** exactly one `REPEATED_FAILURE` signal after three unchanged failing attempts.
- **Recovery:** replay simulates a `CANCEL_AND_RESUME` approval with a known session id.
- **Verification:** changed progress fingerprint plus target-command success evidence.
