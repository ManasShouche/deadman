"""Pure pathological-state detectors."""

from deadman.detectors.hung_process import detect_hung_process
from deadman.detectors.progress import (
    detect_no_progress,
    detect_repeated_failure,
    detect_session_budget_risk,
)

__all__ = [
    "detect_hung_process",
    "detect_no_progress",
    "detect_repeated_failure",
    "detect_session_budget_risk",
]
