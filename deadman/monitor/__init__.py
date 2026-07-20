"""Process-tree and output-liveness observations."""

from deadman.monitor.descendants import (
    DescendantTracker,
    executable_name,
    is_baseline_descendant,
    live_descendant_pids,
    looks_like_user_command,
    observe_descendant,
)
from deadman.monitor.process import PROTECTED_PIDS, ProcessMonitor
from deadman.monitor.workspace import workspace_progress_fingerprint

__all__ = [
    "PROTECTED_PIDS",
    "DescendantTracker",
    "ProcessMonitor",
    "executable_name",
    "is_baseline_descendant",
    "live_descendant_pids",
    "looks_like_user_command",
    "observe_descendant",
    "workspace_progress_fingerprint",
]
