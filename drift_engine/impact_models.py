"""Structured repository references associated with contract drift."""

from dataclasses import dataclass
from enum import Enum

from .changes import DriftChange


class ImpactConfidence(str, Enum):
    HIGH = "high"


@dataclass(frozen=True)
class ImpactMatch:
    """An exact source-code reference that may be affected by one drift change."""

    file_path: str
    line_number: int
    matched_reference: str
    related_drift_change: DriftChange
    confidence: ImpactConfidence
    reason: str
