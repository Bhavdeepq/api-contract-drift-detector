"""Assembles a RemediationContext from the three existing pipeline steps."""

from __future__ import annotations

from pathlib import Path

from .detector import compare_contracts
from .impact import analyze_repository_impacts
from .impact_models import ImpactMatch
from .models import ApiContract, Operation
from .parser import parse_openapi_contract
from .remediation_models import AffectedFile, OperationDiff, RemediationContext


def build_remediation_context(
    expected_path: str | Path,
    actual_path: str | Path,
    repository_path: str | Path,
) -> RemediationContext:
    """Parse both contracts, detect drift, scan for consumer impact, and assemble
    the complete context needed by the Bob remediation workflow.

    No existing pipeline function is modified — this is a pure coordinator that
    calls ``parse_openapi_contract``, ``compare_contracts``, and
    ``analyze_repository_impacts`` in order and structures their outputs.

    Args:
        expected_path: Path to the documented/baseline OpenAPI contract file.
        actual_path:   Path to the observed/implementation OpenAPI contract file.
        repository_path: Root directory of the consumer repository to scan.

    Returns:
        A fully populated, immutable :class:`RemediationContext`.

    Raises:
        ContractParseError: If either contract file cannot be parsed.
        ValueError: If ``repository_path`` is not an existing directory.
    """

    repo_root = Path(repository_path).resolve()

    # ── Step 1 & 2: Parse both contracts ─────────────────────────────────
    expected_contract = parse_openapi_contract(expected_path)
    actual_contract = parse_openapi_contract(actual_path)

    # ── Step 3: Detect drift ──────────────────────────────────────────────
    all_drift_changes = compare_contracts(expected_contract, actual_contract)

    # ── Step 4: Scan for consumer impact ─────────────────────────────────
    all_impact_matches = analyze_repository_impacts(repo_root, all_drift_changes)

    # ── Step 5: Build OperationDiff per endpoint+method ──────────────────
    operation_diffs = _build_operation_diffs(
        expected_contract, actual_contract, all_drift_changes
    )

    # ── Step 6: Group matches by file and attach source text ──────────────
    affected_files = _build_affected_files(repo_root, all_impact_matches)

    return RemediationContext(
        expected_contract=expected_contract,
        actual_contract=actual_contract,
        all_drift_changes=all_drift_changes,
        operation_diffs=operation_diffs,
        all_impact_matches=all_impact_matches,
        affected_files=affected_files,
        repository_path=str(repo_root),
    )


# ── Internal helpers ──────────────────────────────────────────────────────────


def _index_operations(contract: ApiContract) -> dict[tuple[str, str], Operation]:
    """Return a {(path, method): Operation} mapping for every operation in a contract."""
    return {
        (op.path, op.method): op
        for endpoint in contract.endpoints
        for op in endpoint.operations
    }


def _build_operation_diffs(
    expected: ApiContract,
    actual: ApiContract,
    drift_changes: tuple,
) -> tuple[OperationDiff, ...]:
    """Build one OperationDiff per unique (endpoint, method) key found in drift_changes."""

    expected_ops = _index_operations(expected)
    actual_ops = _index_operations(actual)

    # Group drift changes by (endpoint, method).
    grouped: dict[tuple[str, str], list] = {}
    for change in drift_changes:
        key = (change.endpoint, change.method)
        grouped.setdefault(key, []).append(change)

    diffs: list[OperationDiff] = []
    for key in sorted(grouped):
        endpoint, method = key
        diffs.append(
            OperationDiff(
                endpoint=endpoint,
                method=method,
                expected_operation=expected_ops.get(key),
                actual_operation=actual_ops.get(key),
                drift_changes=tuple(grouped[key]),
            )
        )
    return tuple(diffs)


def _build_affected_files(
    repo_root: Path,
    all_impact_matches: tuple[ImpactMatch, ...],
) -> tuple[AffectedFile, ...]:
    """Group ImpactMatch records by file_path and attach full source text.

    Files are read once each.  Matches within a file are ordered by
    (line_number, matched_reference) — the same order as the sorted
    all_impact_matches tuple.
    """

    # Collect unique file paths that had at least one match, preserving order.
    seen_paths: dict[str, None] = {}
    for match in all_impact_matches:
        seen_paths.setdefault(match.file_path, None)

    affected: list[AffectedFile] = []
    for file_path in seen_paths:
        absolute = repo_root / file_path
        source_lines = tuple(
            absolute.read_text(encoding="utf-8", errors="replace").splitlines()
        )
        language = Path(file_path).suffix.lstrip(".").lower()
        file_matches = tuple(m for m in all_impact_matches if m.file_path == file_path)
        affected.append(
            AffectedFile(
                file_path=file_path,
                language=language,
                source_lines=source_lines,
                matches=file_matches,
            )
        )

    # Sort by file_path for deterministic output.
    return tuple(sorted(affected, key=lambda f: f.file_path))
