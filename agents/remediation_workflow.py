"""Bob remediation workflow entry point.

This module is Step 5 of the planned six-step IBM Bob workflow described in
agents/README.md.  It produces a structured remediation plan from a
RemediationContext without modifying any files or calling an external model.

Layer boundary
--------------
``run_remediation`` is deterministic Python — no Bob dependency.
``serialize_plan`` converts the plan to a JSON-serialisable dict so that the
Bob orchestration layer (``agents/bob_orchestrator``) can write it to disk and
read it back as the hand-off artefact between the two layers.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from drift_engine.changes import ChangeType, Severity
from drift_engine.remediation_models import AffectedFile, RemediationContext


# ── Result model ─────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class RemediationAction:
    """A single proposed change to one location in one source file.

    This is the atomic unit of the remediation plan.  Each action describes
    exactly what needs to change, why, and where — without yet making the edit.
    """

    file_path: str
    """POSIX-relative path from the repository root."""

    line_number: int
    """1-based line number of the affected reference."""

    matched_reference: str
    """The exact token (endpoint path, field name, or parameter name) that was matched."""

    endpoint: str
    """The API endpoint path this action relates to, e.g. '/users/{userId}'."""

    method: str
    """The HTTP method this action relates to, e.g. 'GET'."""

    severity: Severity
    """Severity of the originating drift change."""

    change_type: ChangeType
    """The category of drift that produced this action."""

    affected_code: str
    """The source line as it currently reads (the line to be changed)."""

    proposed_change: str
    """Human-readable description of the edit that should be made."""

    reason: str
    """Why this change is required; drawn from the DriftChange explanation."""


@dataclass(frozen=True)
class RemediationPlan:
    """The complete output of one ``run_remediation`` call.

    Contains every proposed action across all affected files, ordered
    deterministically by (file_path, line_number, matched_reference).

    This is a *plan*, not an execution: no files are modified when this is
    created.  Pass it to a Bob invocation (or a human reviewer) to apply
    the changes.
    """

    actions: tuple[RemediationAction, ...]
    """All proposed actions, sorted by (file_path, line_number, matched_reference)."""

    @property
    def breaking_action_count(self) -> int:
        """Number of actions caused by BREAKING drift changes."""
        return sum(1 for a in self.actions if a.severity is Severity.BREAKING)

    @property
    def affected_file_paths(self) -> tuple[str, ...]:
        """Deduplicated, sorted file paths that have at least one action."""
        return tuple(sorted({a.file_path for a in self.actions}))


# ── Serialisation (Python layer → Bob layer hand-off) ────────────────────────


def serialize_plan(plan: RemediationPlan) -> list[dict]:
    """Convert a RemediationPlan to a JSON-serialisable list of dicts.

    Each dict contains only plain Python types (str, int) so the result can be
    passed directly to ``json.dumps``.  No Bob-specific fields are included —
    this is pure data serialisation.

    Intended use::

        plan = run_remediation(context)
        with open("remediation_plan.json", "w") as fh:
            json.dump(serialize_plan(plan), fh, indent=2)

    Args:
        plan: A :class:`RemediationPlan` produced by :func:`run_remediation`.

    Returns:
        A list of dicts, one per :class:`RemediationAction`, ordered
        identically to ``plan.actions``.
    """
    return [
        {
            "file_path": action.file_path,
            "line_number": action.line_number,
            "matched_reference": action.matched_reference,
            "endpoint": action.endpoint,
            "method": action.method,
            "severity": action.severity.value,
            "change_type": action.change_type.value,
            "affected_code": action.affected_code,
            "proposed_change": action.proposed_change,
            "reason": action.reason,
        }
        for action in plan.actions
    ]


def write_plan(plan: RemediationPlan, path: str | Path) -> None:
    """Serialise a RemediationPlan to a JSON file at ``path``.

    Creates parent directories if they do not exist.  Overwrites any existing
    file at the same path.

    Args:
        plan: A :class:`RemediationPlan` produced by :func:`run_remediation`.
        path: Destination file path (typically ``remediation_plan.json``).
    """
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(
        json.dumps(serialize_plan(plan), indent=2),
        encoding="utf-8",
    )


# ── Workflow entry point ──────────────────────────────────────────────────────


def run_remediation(context: RemediationContext) -> RemediationPlan:
    """Produce a structured remediation plan from a RemediationContext.

    Inspects every affected file and every drift change to determine what
    action is needed at each matched source location.  Does not modify files,
    does not call an external model, and makes no network requests.

    This is the Bob integration boundary: when IBM Bob 2.0 is connected,
    replace the body of this function with a Bob invocation that receives the
    same ``context`` and returns actions in the same ``RemediationPlan`` shape.

    Args:
        context: A fully assembled RemediationContext from
                 ``build_remediation_context()``.

    Returns:
        A :class:`RemediationPlan` describing every proposed edit.
    """

    actions: list[RemediationAction] = []
    for affected_file in context.affected_files:
        actions.extend(_actions_for_file(affected_file))

    actions.sort(key=lambda a: (a.file_path, a.line_number, a.matched_reference))
    return RemediationPlan(actions=tuple(actions))


# ── Internal helpers ──────────────────────────────────────────────────────────


def _actions_for_file(affected_file: AffectedFile) -> list[RemediationAction]:
    """Build one RemediationAction per ImpactMatch in this file."""
    actions: list[RemediationAction] = []
    for match in affected_file.matches:
        change = match.related_drift_change
        current_line = affected_file.source_lines[match.line_number - 1]
        actions.append(
            RemediationAction(
                file_path=affected_file.file_path,
                line_number=match.line_number,
                matched_reference=match.matched_reference,
                endpoint=change.endpoint,
                method=change.method,
                severity=change.severity,
                change_type=change.change_type,
                affected_code=current_line,
                proposed_change=_propose(change.change_type, match.matched_reference, change),
                reason=change.explanation,
            )
        )
    return actions


def _propose(change_type: ChangeType, reference: str, change) -> str:
    """Return a human-readable proposed action description for a change type.

    Keeps the mapping explicit and exhaustive so adding a new ChangeType
    surfaces as an unhandled case rather than a silent fallback.
    """

    expected = change.expected_value
    actual = change.actual_value

    if change_type is ChangeType.REMOVED_FIELD:
        return (
            f"Remove or guard all reads of '{reference}': "
            f"this response field no longer exists in the actual contract."
        )
    if change_type is ChangeType.ADDED_FIELD:
        return (
            f"Update consumer code to handle the new field '{reference}' "
            f"({actual}) now present in the contract."
        )
    if change_type is ChangeType.FIELD_TYPE_CHANGED:
        return (
            f"Update usages of '{reference}' from type '{expected}' to '{actual}': "
            f"add a type cast or coercion where needed."
        )
    if change_type is ChangeType.REQUIRED_TO_OPTIONAL:
        return (
            f"Add a null/undefined guard for '{reference}': "
            f"it changed from required to optional and may now be absent."
        )
    if change_type is ChangeType.OPTIONAL_TO_REQUIRED:
        return (
            f"Ensure '{reference}' is always provided: "
            f"it changed from optional to required."
        )
    if change_type is ChangeType.ADDED_PARAMETER:
        return (
            f"Add the '{reference}' parameter ({actual}) to all call sites for "
            f"{change.method} {change.endpoint}."
        )
    if change_type is ChangeType.REMOVED_PARAMETER:
        return (
            f"Remove the '{reference}' parameter from call sites: "
            f"it is no longer accepted by {change.method} {change.endpoint}."
        )
    if change_type is ChangeType.PARAMETER_TYPE_CHANGED:
        return (
            f"Update the '{reference}' parameter from type '{expected}' to '{actual}' "
            f"at all call sites for {change.method} {change.endpoint}."
        )
    if change_type is ChangeType.REMOVED_ENDPOINT:
        return (
            f"Remove or replace all references to {change.method} {change.endpoint}: "
            f"the endpoint no longer exists in the actual contract."
        )
    if change_type is ChangeType.ADDED_ENDPOINT:
        return (
            f"Consider integrating the new endpoint "
            f"{change.method} {change.endpoint} into consumer code."
        )
    if change_type is ChangeType.REMOVED_RESPONSE_STATUS:
        return (
            f"Remove handling for HTTP {expected} from {change.method} {change.endpoint}: "
            f"the implementation no longer returns this status."
        )
    if change_type is ChangeType.ADDED_RESPONSE_STATUS:
        return (
            f"Add handling for the new HTTP {actual} response from "
            f"{change.method} {change.endpoint}."
        )
    if change_type is ChangeType.REMOVED_REQUEST_BODY:
        return (
            f"Remove the '{reference}' request body content-type from call sites: "
            f"it is no longer accepted."
        )
    if change_type is ChangeType.ADDED_REQUEST_BODY:
        return (
            f"Update call sites to supply the '{actual}' request body "
            f"now required by {change.method} {change.endpoint}."
        )
    if change_type is ChangeType.REMOVED_RESPONSE_CONTENT:
        return (
            f"Remove consumer handling for '{expected}' response content: "
            f"the server no longer provides it."
        )
    if change_type is ChangeType.ADDED_RESPONSE_CONTENT:
        return (
            f"Consumer may now handle the new '{actual}' response content "
            f"from {change.method} {change.endpoint}."
        )
    # Exhaustive — should never reach here with a valid ChangeType.
    return f"Review usage of '{reference}' in response to: {change.explanation}"
