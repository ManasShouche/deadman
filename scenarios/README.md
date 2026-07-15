# Scenario fixtures

All demo scenarios begin as raw traces and controlled fixture inputs. A scenario is not demo-ready until its trace activates exactly one intended detector and passes the same offline `deadman replay` pipeline used by the live path.

| Scenario | Required evidence | D0 state |
| --- | --- | --- |
| Hung child process | Owned child process with no I/O activity | Placeholder |
| Repeated failure | Three identical failures with unchanged workspace and test summary | Placeholder |
| Session handoff | Usage threshold fixture or manual checkpoint | Placeholder |
