# Hung process fixture

- **Purpose:** Gate B fixture for the `HUNG_PROCESS` detector.
- **Expected detector:** exactly one `HUNG_PROCESS` signal when evaluated at `now=75.0` with the default 60 second timeout.
- **Recovery:** not implemented in D1. This fixture proves detection only.
- **False-positive guards:** no listening port and no ready/watch pattern marker.
