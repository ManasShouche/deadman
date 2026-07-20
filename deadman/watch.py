"""Observe-only watch loop for explicitly paired persisted sessions."""

from __future__ import annotations

import time
from collections.abc import Iterator

from deadman.adapter import SessionCandidate, ingest_session
from deadman.domain import WatchSnapshot
from deadman.store import EvidenceStore


def iter_watch_snapshots(
    candidate: SessionCandidate,
    store: EvidenceStore,
    *,
    poll_interval_seconds: float,
) -> Iterator[WatchSnapshot]:
    """Yield the initial snapshot and subsequent snapshots containing new events."""

    if poll_interval_seconds <= 0:
        raise ValueError("poll interval must be greater than zero")

    yield ingest_session(candidate, store)
    while True:
        time.sleep(poll_interval_seconds)
        snapshot = ingest_session(candidate, store)
        if snapshot.new_event_count:
            yield snapshot
