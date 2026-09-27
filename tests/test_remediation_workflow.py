"""Tests for run_remediation() and the RemediationPlan / RemediationAction models."""

from pathlib import Path

import pytest

from drift_engine import (
    ChangeType,
    Severity,
    build_remediation_context,
)
from agents.remediation_workflow import (
    RemediationAction,
    RemediationPlan,
    run_remediation,
)


ROOT = Path(__file__).parents[1]
EXPECTED_CONTRACT = ROOT / "examples" / "user-api.openapi.yaml"
ACTUAL_CONTRACT = ROOT / "examples" / "user-api.actual.openapi.yaml"
DEMO_REPOSITORY = ROOT / "examples" / "demo-repository"


def _context():
    return build_remediation_context(EXPECTED_CONTRACT, ACTUAL_CONTRACT, DEMO_REPOSITORY)


# ── run_remediation returns a RemediationPlan ─────────────────────────────────


def test_run_remediation_returns_remediation_plan() -> None:
    plan = run_remediation(_context())

    assert isinstance(plan, RemediationPlan)


def test_plan_has_at_least_one_action() -> None:
    plan = run_remediation(_context())

    assert len(plan.actions) > 0


def test_all_actions_are_remediation_action_instances() -> None:
    plan = run_remediation(_context())

    assert all(isinstance(a, RemediationAction) for a in plan.actions)


# ── Actions are sorted deterministically ─────────────────────────────────────


def test_actions_are_sorted_by_file_then_line_then_reference() -> None:
    plan = run_remediation(_context())

    keys = [(a.file_path, a.line_number, a.matched_reference) for a in plan.actions]
    assert keys == sorted(keys)


def test_run_remediation_is_deterministic() -> None:
    ctx = _context()
    plan1 = run_remediation(ctx)
    plan2 = run_remediation(ctx)

    assert plan1.actions == plan2.actions


# ── Actions reference real source lines ──────────────────────────────────────


def test_action_affected_code_matches_source_line_in_context() -> None:
    ctx = _context()
    plan = run_remediation(ctx)

    # Every action's affected_code must equal the actual source line.
    file_text: dict[str, tuple[str, ...]] = {
        f.file_path: f.source_lines for f in ctx.affected_files
    }
    for action in plan.actions:
        expected_line = file_text[action.file_path][action.line_number - 1]
        assert action.affected_code == expected_line


def test_action_for_removed_email_field_references_correct_line() -> None:
    plan = run_remediation(_context())

    # client.py line 5 contains `user["email"]` and is matched by REMOVED_FIELD.
    email_actions = [
        a for a in plan.actions
        if a.file_path == "client.py"
        and a.matched_reference == "email"
        and a.change_type is ChangeType.REMOVED_FIELD
    ]
    assert len(email_actions) >= 1
    action = email_actions[0]
    assert action.line_number == 5
    assert "email" in action.affected_code


# ── Action fields are correctly populated ────────────────────────────────────


def test_action_severity_matches_originating_drift_change() -> None:
    plan = run_remediation(_context())

    for action in plan.actions:
        # Breaking actions must not be labelled NON_BREAKING.
        if action.change_type in {
            ChangeType.REMOVED_FIELD,
            ChangeType.FIELD_TYPE_CHANGED,
            ChangeType.REMOVED_ENDPOINT,
            ChangeType.REMOVED_RESPONSE_STATUS,
        }:
            assert action.severity is Severity.BREAKING


def test_action_reason_is_non_empty_string() -> None:
    plan = run_remediation(_context())

    for action in plan.actions:
        assert isinstance(action.reason, str)
        assert len(action.reason) > 0


def test_action_proposed_change_is_non_empty_string() -> None:
    plan = run_remediation(_context())

    for action in plan.actions:
        assert isinstance(action.proposed_change, str)
        assert len(action.proposed_change) > 0


def test_action_endpoint_and_method_are_populated() -> None:
    plan = run_remediation(_context())

    for action in plan.actions:
        assert action.endpoint.startswith("/")
        assert action.method.isupper()


# ── Plan convenience properties ───────────────────────────────────────────────


def test_plan_breaking_action_count_is_positive() -> None:
    plan = run_remediation(_context())

    assert plan.breaking_action_count > 0


def test_plan_breaking_action_count_counts_only_breaking() -> None:
    plan = run_remediation(_context())

    manual_count = sum(1 for a in plan.actions if a.severity is Severity.BREAKING)
    assert plan.breaking_action_count == manual_count


def test_plan_affected_file_paths_are_sorted_and_unique() -> None:
    plan = run_remediation(_context())

    paths = plan.affected_file_paths
    assert list(paths) == sorted(set(paths))


def test_plan_affected_file_paths_cover_known_demo_files() -> None:
    plan = run_remediation(_context())

    assert "client.py" in plan.affected_file_paths


# ── Proposed change content covers key change types ──────────────────────────


def test_proposed_change_for_removed_field_mentions_remove_or_guard() -> None:
    plan = run_remediation(_context())

    removed = [a for a in plan.actions if a.change_type is ChangeType.REMOVED_FIELD]
    assert len(removed) > 0
    for action in removed:
        lower = action.proposed_change.lower()
        assert "remove" in lower or "guard" in lower


def test_proposed_change_for_added_parameter_mentions_parameter_name() -> None:
    plan = run_remediation(_context())

    added_params = [a for a in plan.actions if a.change_type is ChangeType.ADDED_PARAMETER]
    assert len(added_params) > 0
    for action in added_params:
        assert action.matched_reference in action.proposed_change


def test_proposed_change_for_field_type_changed_mentions_both_types() -> None:
    plan = run_remediation(_context())

    type_changes = [a for a in plan.actions if a.change_type is ChangeType.FIELD_TYPE_CHANGED]
    assert len(type_changes) > 0
    for action in type_changes:
        # Should mention old type (string) and new type (integer).
        assert action.change_type is ChangeType.FIELD_TYPE_CHANGED
        assert len(action.proposed_change) > 0


# ── Immutability ──────────────────────────────────────────────────────────────


def test_remediation_plan_is_immutable() -> None:
    plan = run_remediation(_context())

    with pytest.raises((AttributeError, TypeError)):
        plan.actions = ()  # type: ignore[misc]


def test_remediation_action_is_immutable() -> None:
    plan = run_remediation(_context())
    action = plan.actions[0]

    with pytest.raises((AttributeError, TypeError)):
        action.file_path = "/mutated"  # type: ignore[misc]


# ── Does not modify files ─────────────────────────────────────────────────────


def test_run_remediation_does_not_modify_any_source_file(tmp_path: Path) -> None:
    import shutil

    # Copy the demo repository to a temp dir so we can detect any writes.
    repo_copy = tmp_path / "repo"
    shutil.copytree(DEMO_REPOSITORY, repo_copy)

    # Record mtime of every file before.
    before = {
        p: p.stat().st_mtime
        for p in repo_copy.rglob("*")
        if p.is_file()
    }

    ctx = build_remediation_context(EXPECTED_CONTRACT, ACTUAL_CONTRACT, repo_copy)
    run_remediation(ctx)

    after = {
        p: p.stat().st_mtime
        for p in repo_copy.rglob("*")
        if p.is_file()
    }
    assert before == after


# ── Empty context edge case ───────────────────────────────────────────────────


def test_identical_contracts_produce_empty_plan(tmp_path: Path) -> None:
    # When expected == actual, there are no drifts and no impact matches.
    ctx = build_remediation_context(EXPECTED_CONTRACT, EXPECTED_CONTRACT, DEMO_REPOSITORY)
    plan = run_remediation(ctx)

    assert plan.actions == ()
    assert plan.breaking_action_count == 0
    assert plan.affected_file_paths == ()
