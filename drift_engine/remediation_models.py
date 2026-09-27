"""Immutable context structures passed to the Bob remediation workflow."""

from __future__ import annotations

from dataclasses import dataclass

from .changes import DriftChange
from .impact_models import ImpactMatch
from .models import ApiContract, Operation


@dataclass(frozen=True)
class AffectedFile:
    """All drift-related hits inside one source file, with the full text for editing.

    ``source_lines`` is the complete file content split into lines (no trailing
    newline characters) and is 0-indexed — index directly with
    ``source_lines[match.line_number - 1]`` to reach the matched line.
    """

    file_path: str
    """POSIX-relative path from the repository root; matches ImpactMatch.file_path."""

    language: str
    """Lowercased file extension without dot: 'py', 'ts', 'tsx', 'js', or 'jsx'."""

    source_lines: tuple[str, ...]
    """Complete file content as one string per line, without newline characters."""

    matches: tuple[ImpactMatch, ...]
    """All ImpactMatch records for this file, ordered by line_number then matched_reference."""


@dataclass(frozen=True)
class OperationDiff:
    """The full before/after Operation pair for one drifted endpoint+method.

    DriftChange carries only compressed display strings; this struct gives the
    remediation workflow the complete typed schemas on both sides so it can
    generate correct, language-aware fixes.

    Either ``expected_operation`` or ``actual_operation`` may be None:
    - ``expected_operation`` is None when ``change_type`` is ADDED_ENDPOINT
      (the operation did not exist in the documented contract).
    - ``actual_operation`` is None when ``change_type`` is REMOVED_ENDPOINT
      (the operation is absent from the actual implementation).
    """

    endpoint: str
    method: str
    expected_operation: Operation | None
    actual_operation: Operation | None
    drift_changes: tuple[DriftChange, ...]
    """All DriftChange records that apply to this endpoint+method, sorted deterministically."""


@dataclass(frozen=True)
class RemediationContext:
    """Complete, self-contained input for one Bob remediation workflow pass.

    Assembles everything the workflow needs in a single immutable value:
    the original and actual contracts, every classified drift, every affected
    source-file hit, and the full text of each affected file so edits can be
    proposed without additional I/O.

    Build this with ``build_remediation_context()`` from
    ``drift_engine.remediation_context`` — do not construct it directly.
    """

    # ── Contract identity ─────────────────────────────────────────────────
    expected_contract: ApiContract
    """The documented baseline contract (the source of truth)."""

    actual_contract: ApiContract
    """The observed implementation contract (what the server currently does)."""

    # ── Classified drift ──────────────────────────────────────────────────
    all_drift_changes: tuple[DriftChange, ...]
    """Every DriftChange from compare_contracts(), sorted deterministically."""

    operation_diffs: tuple[OperationDiff, ...]
    """One OperationDiff per affected endpoint+method, carrying full Operation objects.
    Sorted by (endpoint, method)."""

    # ── Consumer impact ───────────────────────────────────────────────────
    all_impact_matches: tuple[ImpactMatch, ...]
    """Every ImpactMatch from analyze_repository_impacts(), sorted deterministically."""

    affected_files: tuple[AffectedFile, ...]
    """ImpactMatch records grouped by file, each with full source text and language.
    Sorted by file_path."""

    # ── Scope ─────────────────────────────────────────────────────────────
    repository_path: str
    """Absolute path to the repository root that was scanned."""
