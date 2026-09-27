"""Deterministic source scanning for potential API-contract drift consumers."""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

from .changes import DriftChange
from .impact_models import ImpactConfidence, ImpactMatch

_SOURCE_SUFFIXES = {".py", ".js", ".jsx", ".ts", ".tsx"}
_IGNORED_DIRECTORIES = {".git", "node_modules", "venv", ".venv", "__pycache__", "build", "dist"}
_NAMED_REFERENCE = re.compile(r"(?:field|parameter) '([^']+)'")
_IDENTIFIER_CHARACTER = r"A-Za-z0-9_$"


@dataclass(frozen=True)
class _Reference:
    value: str
    kind: str


def analyze_repository_impacts(repository_path: str | Path, drift_changes: Iterable[DriftChange]) -> tuple[ImpactMatch, ...]:
    """Find exact endpoint, field, and parameter references in supported source files.

    Paths in returned matches are relative to ``repository_path`` and use POSIX
    separators. This function performs textual, not semantic, analysis: each match
    is a high-confidence exact reference and is intentionally ready for later
    enrichment by a separate workflow.
    """

    root = Path(repository_path)
    if not root.is_dir():
        raise ValueError(f"Repository path must be an existing directory: '{root}'.")

    changes = tuple(sorted(drift_changes, key=_drift_key))
    matches: list[ImpactMatch] = []
    for source_file in _source_files(root):
        relative_path = source_file.relative_to(root).as_posix()
        lines = source_file.read_text(encoding="utf-8", errors="replace").splitlines()
        for change in changes:
            for reference in _references_for(change):
                for line_number, line in enumerate(lines, start=1):
                    if _contains_reference(line, reference):
                        matches.append(ImpactMatch(
                            file_path=relative_path,
                            line_number=line_number,
                            matched_reference=reference.value,
                            related_drift_change=change,
                            confidence=ImpactConfidence.HIGH,
                            reason=f"Exact {reference.kind} reference matched in supported source code.",
                        ))
    return tuple(sorted(matches, key=_match_key))


def _source_files(root: Path) -> tuple[Path, ...]:
    files: list[Path] = []
    for directory, directories, filenames in os.walk(root):
        directories[:] = sorted(name for name in directories if name.casefold() not in _IGNORED_DIRECTORIES)
        directory_path = Path(directory)
        files.extend(directory_path / name for name in sorted(filenames) if Path(name).suffix.casefold() in _SOURCE_SUFFIXES)
    return tuple(files)


def _references_for(change: DriftChange) -> tuple[_Reference, ...]:
    references = [_Reference(change.endpoint, "endpoint path")]
    match = _NAMED_REFERENCE.search(change.explanation)
    if match:
        # Nested fields are represented as e.g. profile.email. Match the field
        # token used by source code as well as the full, dotted contract path.
        full_name = match.group(1)
        references.append(_Reference(full_name, "field or parameter"))
        leaf_name = re.split(r"[.\[\]]", full_name)[-1]
        if leaf_name and leaf_name != full_name:
            references.append(_Reference(leaf_name, "field or parameter"))
    unique = {(reference.value, reference.kind): reference for reference in references if reference.value}
    return tuple(sorted(unique.values(), key=lambda reference: (reference.value, reference.kind)))


def _contains_reference(line: str, reference: _Reference) -> bool:
    if reference.kind == "endpoint path":
        return re.search(rf"(?<![A-Za-z0-9_/{{]){re.escape(reference.value)}(?![A-Za-z0-9_/{{])", line) is not None
    return re.search(rf"(?<![{_IDENTIFIER_CHARACTER}]){re.escape(reference.value)}(?![{_IDENTIFIER_CHARACTER}])", line) is not None


def _drift_key(change: DriftChange) -> tuple[str, str, str, str, str, str]:
    return (change.endpoint, change.method, change.location, change.change_type.value,
            change.expected_value or "", change.actual_value or "")


def _match_key(match: ImpactMatch) -> tuple[str, int, str, tuple[str, str, str, str, str, str]]:
    return (match.file_path, match.line_number, match.matched_reference, _drift_key(match.related_drift_change))
