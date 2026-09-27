"""Bob orchestration layer for API contract drift remediation.

Layer boundary
--------------
This module is the **only** file in the codebase that knows Bob exists.

It contains three public functions:

``build_file_brief(affected_file, context)``
    Pure text builder.  Takes an AffectedFile and a RemediationContext and
    returns a structured plain-text string that becomes Bob's per-file
    instruction.  No I/O, no Bob calls, fully testable in isolation.

``verify_remediation(expected_path, actual_path, repo_path, prior_changes, test_cmd)``
    Pure Python.  Re-runs the deterministic drift-detection pipeline after
    Bob edits a file and diffs the results against the changes that were
    present before.  Optionally runs a test command and captures the output.
    Returns a ``VerificationResult``.  No Bob dependency.

``run_bob_remediation(context, plan_path)``
    **The Bob integration boundary.**  This function is called *by Bob* from
    the agent conversation — Bob reads the remediation plan, iterates over
    affected files, uses its own tools (read_file, write_file, apply_diff,
    execute_command) to apply fixes, calls ``verify_remediation`` after each
    file, and updates the plan with the outcome.

    This function does NOT call Bob's agent tools programmatically.  Python
    cannot import or invoke ``spawn_subagent``, ``start_subtask``,
    ``apply_diff``, or ``execute_command`` — those are Bob's tools, not a
    Python API.  Instead, this function:

    1. Writes the plan and one brief per affected file to disk (so Bob can
       read them with its ``read_file`` tool).
    2. Returns a structured dict describing exactly what Bob should do next,
       file by file.  Bob reads that dict and executes the steps itself.

    The caller (Bob the agent) is responsible for actually editing files and
    running tests.  This module provides the scaffolding and verification.
"""

from __future__ import annotations

import json
import subprocess
import textwrap
from pathlib import Path

from drift_engine.changes import DriftChange, Severity
from drift_engine.models import Operation, Parameter, RequestBody, Response, Schema
from drift_engine.remediation_context import build_remediation_context
from drift_engine.remediation_models import (
    ActionStatus,
    AffectedFile,
    RemediationContext,
    VerificationResult,
)
from agents.remediation_workflow import RemediationPlan, serialize_plan, write_plan


# ── Brief builder ─────────────────────────────────────────────────────────────


def build_file_brief(affected_file: AffectedFile, context: RemediationContext) -> str:
    """Build a scoped plain-text brief for one affected file.

    The returned string is the complete instruction set for Bob when remediating
    a single file.  It is self-contained: Bob does not need to look elsewhere to
    understand the contract, the drift, or the required fix.

    Args:
        affected_file: The file to remediate, with source text and matches.
        context:       The full RemediationContext for the current run.

    Returns:
        A multi-line plain-text string.  Sections are separated by ``---``.
    """

    # Collect only the OperationDiffs that have matches in this file.
    file_endpoints = {m.related_drift_change.endpoint for m in affected_file.matches}
    relevant_diffs = [
        d for d in context.operation_diffs if d.endpoint in file_endpoints
    ]

    lines: list[str] = []

    # ── Header ────────────────────────────────────────────────────────────
    lines.append(f"=== REMEDIATION BRIEF: {affected_file.file_path} ===")
    lines.append("")
    lines.append(f"LANGUAGE: {affected_file.language}")
    lines.append(f"FILE:     {affected_file.file_path}")
    lines.append("")

    # ── Contract comparison per relevant endpoint ─────────────────────────
    for diff in relevant_diffs:
        lines.append("---")
        lines.append(f"ENDPOINT: {diff.method} {diff.endpoint}")
        lines.append("")

        if diff.expected_operation is not None:
            lines.append("  EXPECTED CONTRACT (documented baseline):")
            lines.extend(_format_operation(diff.expected_operation, indent="    "))
        else:
            lines.append("  EXPECTED CONTRACT: (endpoint not present in documented contract)")

        lines.append("")

        if diff.actual_operation is not None:
            lines.append("  ACTUAL CONTRACT (current implementation):")
            lines.extend(_format_operation(diff.actual_operation, indent="    "))
        else:
            lines.append("  ACTUAL CONTRACT: (endpoint absent from implementation)")

        lines.append("")

        lines.append("  DRIFT CHANGES:")
        for i, change in enumerate(diff.drift_changes, start=1):
            marker = "BREAKING" if change.severity is Severity.BREAKING else change.severity.value.upper()
            lines.append(f"  [{i}] {marker}  {change.change_type.value}")
            lines.append(f"      {change.explanation}")
            if change.expected_value is not None:
                lines.append(f"      Expected: {change.expected_value}")
            if change.actual_value is not None:
                lines.append(f"      Actual:   {change.actual_value}")
        lines.append("")

    # ── Affected lines ────────────────────────────────────────────────────
    lines.append("---")
    lines.append("AFFECTED LINES:")
    lines.append("")

    # Group matches by line number so each line appears once.
    by_line: dict[int, list] = {}
    for match in affected_file.matches:
        by_line.setdefault(match.line_number, []).append(match)

    for line_num in sorted(by_line):
        source_line = affected_file.source_lines[line_num - 1]
        lines.append(f"  Line {line_num}:  {source_line}")
        for match in by_line[line_num]:
            change = match.related_drift_change
            severity_tag = (
                "BREAKING" if change.severity is Severity.BREAKING
                else change.severity.value.upper()
            )
            lines.append(
                f"           ↳ [{severity_tag}] matches '{match.matched_reference}' "
                f"({change.change_type.value})"
            )
            # Proposed change, wrapped to 80 chars and indented.
            from agents.remediation_workflow import _propose
            proposal = _propose(change.change_type, match.matched_reference, change)
            wrapped = textwrap.fill(proposal, width=72, subsequent_indent="              ")
            lines.append(f"           → {wrapped}")
        lines.append("")

    # ── Full file content ─────────────────────────────────────────────────
    lines.append("---")
    lines.append("FULL FILE CONTENT:")
    lines.append("")
    for i, source_line in enumerate(affected_file.source_lines, start=1):
        lines.append(f"  {i:>4}: {source_line}")
    lines.append("")

    # ── Instructions ──────────────────────────────────────────────────────
    lines.append("---")
    lines.append("INSTRUCTIONS FOR BOB:")
    lines.append("")
    lines.append(f"  You may ONLY edit the file: {affected_file.file_path}")
    lines.append("  Do NOT modify any other file.")
    lines.append("")
    lines.append("  For each affected line listed above:")
    lines.append("    1. Explain the intended change in plain English before editing.")
    lines.append("    2. Apply the minimal safe edit that resolves the drift.")
    lines.append(
        "    3. If you cannot safely determine the correct fix for a line,\n"
        "       leave it unchanged and mark that action UNRESOLVED with a reason."
    )
    lines.append("")
    lines.append("  After all edits:")
    lines.append("    4. Run the test suite:")
    lines.append("         pytest tests/ -v")
    lines.append("    5. Call verify_remediation() to confirm drift is resolved.")
    lines.append(
        "    6. Return one status per action: RESOLVED, UNRESOLVED, or VERIFICATION_FAILED."
    )
    lines.append("")

    return "\n".join(lines)


# ── Verification ──────────────────────────────────────────────────────────────


def verify_remediation(
    expected_path: str | Path,
    actual_path: str | Path,
    repository_path: str | Path,
    prior_changes: tuple[DriftChange, ...],
    test_cmd: list[str] | None = None,
) -> VerificationResult:
    """Re-run drift detection and optional tests; diff against prior changes.

    Call this after Bob has edited a file to determine whether the targeted
    drift changes have been eliminated.

    Args:
        expected_path:    Path to the documented/baseline OpenAPI contract.
        actual_path:      Path to the actual/implementation OpenAPI contract.
        repository_path:  Root of the consumer repository (same as the original scan).
        prior_changes:    The ``all_drift_changes`` tuple from the RemediationContext
                          that was built *before* Bob edited any files.  Used as the
                          baseline to diff against.
        test_cmd:         Optional shell command to run (e.g. ``["pytest", "tests/",
                          "-v"]``).  If ``None``, tests are skipped and
                          ``tests_passed`` is set to ``True``.

    Returns:
        A :class:`VerificationResult` describing which changes were resolved,
        which remain, and whether the test suite passed.
    """

    # Re-run the deterministic pipeline.
    new_context = build_remediation_context(expected_path, actual_path, repository_path)
    new_changes = set(new_context.all_drift_changes)
    prior_set = set(prior_changes)

    resolved = tuple(sorted(
        (c for c in prior_set if c not in new_changes),
        key=lambda c: (c.endpoint, c.method, c.change_type.value),
    ))
    remaining = tuple(sorted(
        (c for c in prior_set if c in new_changes),
        key=lambda c: (c.endpoint, c.method, c.change_type.value),
    ))

    # Optionally run the test suite.
    if test_cmd is None:
        return VerificationResult(
            resolved_changes=resolved,
            remaining_changes=remaining,
            tests_passed=True,
            test_output="",
        )

    result = subprocess.run(
        test_cmd,
        capture_output=True,
        text=True,
    )
    test_output = (result.stdout or "") + (result.stderr or "")
    return VerificationResult(
        resolved_changes=resolved,
        remaining_changes=remaining,
        tests_passed=result.returncode == 0,
        test_output=test_output,
    )


# ── Bob integration entry point ───────────────────────────────────────────────


def run_bob_remediation(
    context: RemediationContext,
    plan: RemediationPlan,
    output_dir: str | Path = ".",
) -> dict:
    """Prepare all artefacts Bob needs and return a structured work order.

    **This function does not call Bob's agent tools.**  Python cannot import or
    invoke ``spawn_subagent``, ``start_subtask``, ``apply_diff``, or
    ``execute_command`` — those are Bob's tools, not a Python API.

    What this function does:

    1. Writes the serialised plan to ``<output_dir>/remediation_plan.json``.
    2. Writes one plain-text brief per affected file to
       ``<output_dir>/briefs/<file_path>.brief.txt``.
    3. Returns a ``work_order`` dict that tells Bob exactly what to do, file by
       file.

    Bob reads the work order and executes each step using its own tools:
    - ``read_file`` to load a brief
    - ``apply_diff`` or ``write_file`` to make the edit
    - ``execute_command`` to run ``pytest``
    - ``verify_remediation()`` to confirm the drift is resolved

    Args:
        context:    The RemediationContext for this run.
        plan:       The RemediationPlan produced by run_remediation(context).
        output_dir: Directory where plan JSON and brief files are written.
                    Defaults to the current working directory.

    Returns:
        A dict with two keys:
        ``"plan_path"``   — absolute path to the written plan JSON.
        ``"file_tasks"``  — list of per-file task dicts, each containing:
            ``"file_path"``    — POSIX-relative path of the file to edit.
            ``"brief_path"``   — absolute path to the plain-text brief.
            ``"action_count"`` — number of RemediationActions for this file.
            ``"has_breaking"`` — True if any action is BREAKING severity.
            ``"verify_cmd"``   — the pytest command Bob should run after editing.
            ``"instructions"`` — human-readable summary for Bob.
    """

    out = Path(output_dir).resolve()
    briefs_dir = out / "briefs"
    briefs_dir.mkdir(parents=True, exist_ok=True)

    # Write the serialised plan.
    plan_path = out / "remediation_plan.json"
    write_plan(plan, plan_path)

    # Build per-file tasks.
    file_tasks: list[dict] = []
    for affected_file in context.affected_files:
        brief_text = build_file_brief(affected_file, context)

        # Safe filename: replace path separators.
        safe_name = affected_file.file_path.replace("/", "__").replace("\\", "__")
        brief_path = briefs_dir / f"{safe_name}.brief.txt"
        brief_path.write_text(brief_text, encoding="utf-8")

        file_actions = [a for a in plan.actions if a.file_path == affected_file.file_path]
        has_breaking = any(a.severity is Severity.BREAKING for a in file_actions)

        # Build the pytest command.  Run from the repo root.
        verify_cmd = ["pytest", "tests/", "-v"]

        file_tasks.append({
            "file_path": affected_file.file_path,
            "brief_path": str(brief_path),
            "action_count": len(file_actions),
            "has_breaking": has_breaking,
            "verify_cmd": verify_cmd,
            "instructions": (
                f"Read '{brief_path}' for full context.\n"
                f"Edit ONLY '{affected_file.file_path}'.\n"
                f"Run: {' '.join(verify_cmd)}\n"
                f"Call verify_remediation() and report RESOLVED/UNRESOLVED/"
                f"VERIFICATION_FAILED for each of the {len(file_actions)} action(s)."
            ),
        })

    return {
        "plan_path": str(plan_path),
        "file_tasks": file_tasks,
    }


# ── Internal schema formatters ────────────────────────────────────────────────


def _format_operation(operation: Operation, indent: str = "  ") -> list[str]:
    """Format an Operation as indented plain text lines."""
    lines: list[str] = []

    if operation.path_parameters:
        lines.append(f"{indent}Path parameters:")
        for p in operation.path_parameters:
            lines.append(f"{indent}  {p.name}: {p.schema.type}  (required)")

    if operation.query_parameters:
        lines.append(f"{indent}Query parameters:")
        for p in operation.query_parameters:
            req = "required" if p.required else "optional"
            lines.append(f"{indent}  {p.name}: {p.schema.type}  ({req})")

    if operation.request_bodies:
        lines.append(f"{indent}Request body:")
        for body in operation.request_bodies:
            req = "required" if body.required else "optional"
            lines.append(f"{indent}  [{body.content_type}]  ({req})")
            lines.extend(_format_schema(body.schema, indent + "    "))

    if operation.responses:
        lines.append(f"{indent}Responses:")
        for response in operation.responses:
            lines.append(f"{indent}  {response.status_code}:")
            for content_type, schema in response.schemas:
                lines.append(f"{indent}    [{content_type}]")
                lines.extend(_format_schema(schema, indent + "      "))

    return lines


def _format_schema(schema: Schema, indent: str = "  ") -> list[str]:
    """Format a Schema as indented plain text lines."""
    lines: list[str] = []
    if schema.type == "array" and schema.items:
        lines.append(f"{indent}type: array of {schema.items.type}")
        if schema.items.fields:
            lines.extend(_format_schema(schema.items, indent + "  "))
    elif schema.fields:
        for f in schema.fields:
            req = "required" if f.required else "optional"
            fmt = f"  format={f.format}" if f.format else ""
            lines.append(f"{indent}{f.name}: {f.type}{fmt}  ({req})")
            if f.schema and f.schema.fields:
                lines.extend(_format_schema(f.schema, indent + "  "))
    else:
        lines.append(f"{indent}type: {schema.type}")
    return lines
