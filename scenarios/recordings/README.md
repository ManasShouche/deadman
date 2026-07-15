# Recorded traces

This directory contains immutable, versioned JSONL evidence used for adapter compatibility and deterministic replay. Local exploratory traces use the `.local.jsonl` suffix and are ignored.

- `gate-a-codex-cli-0.144.4.jsonl` will contain the harmless persisted compatibility capture.
- The three scenario traces listed in `../README.md` will be added with their fixture metadata before recovery logic is implemented.

Raw records are retained even when they are malformed or have unknown event types. Future normalizers may derive structured records from them, but must not treat them as a stable Codex event-schema contract.
