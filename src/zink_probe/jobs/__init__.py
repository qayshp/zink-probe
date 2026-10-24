"""Portable single-job engine with no eager native Bluetooth imports.

The separate macos_probe CLI exposes read-only hardware checks, not submission.
"""

from .engine import JobEngine, JobResult
from .journal import JobJournal
from .model import JobSpec
from .transport import FramedSession

__all__ = ["FramedSession", "JobEngine", "JobJournal", "JobResult", "JobSpec"]
