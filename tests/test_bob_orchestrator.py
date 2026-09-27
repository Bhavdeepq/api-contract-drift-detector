"""Tests for agents/bob_orchestrator.py.

Covers:
- serialisation round-trip (serialize_plan / write_plan)
- brief content and structure (build_file_brief)
- verification logic, including resolved/remaining/failure cases
- run_bob_remediation artefact generation
- ActionStatus and VerificationResult model behaviour
- unresolved / verification-failed outcomes
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from unittest.mock import patch

import pytest

from drift_engine import (
    ActionStatus,
    AffectedFile,
    ChangeType,
    DriftChange,
    Severity,
    VerificationResult,
    build_remediation_context,
)
from agents.remediation_workflow import (
    RemediationAction,
    RemediationPlan,
    run_remediation,
    serialize_plan,
    write_plan,
)
from agents.bob_orchestrator import (
    build_file_brief,
    run_bob_remediation,
    verify_remediation,
)


ROOT = Path(__file__).parents[1]
EXPECTED_CONTRACT = ROOT / "examples" / "user-api.openapi.yaml"
ACTUAL_CONTRACT = ROOT / "examples" / "user-api.actual.openapi.yaml"
DEMO_REPOSITORY = ROOT / "examples" / "demo-repository"


def _context():
    return build_remediation_context(EXPECTED_CONTRACT, ACTUAL_CONTRACT, DEMO_REPOSITORY)


def _plan():
    return run_remediation(_context())


# ═══════════════════════════════════════════════════════════════════════════════
# ActionStatus model
# ═══════════════════════════════════════════════════════════════════════════════


def test_action_status_values_are_strings() -> None:
    assert ActionStatus.PROPOSED.value == "proposed"
    assert ActionStatus.RESOLVED.value == "resolved"
    assert ActionStatus.UNRESOLVED.value == "unresolved"
    assert ActionStatus.VERIFICATION_FAILED.value == "verification_failed"


def test_action_status_is_str_enum() -> None:
    assert isinstance(ActionStatus.RESOLVED, str)
    assert ActionStatus.RESOLVED == "resolved"


# ═══════════════════════════════════════════════════════════════════════════════
# VerificationResult model
# ═══════════════════════════════════════════════════════════════════════════════


def _make_change(**kwargs) -> DriftChange:
    defaults = dict(
        endpoint="/test",
        method="GET",
        location="response",
        change_type=ChangeType.REMOVED_FIELD,
        expected_value="string (required)",
        actual_value=None,
        severity=Severity.BREAKING,
        explanation="Response field 'x' was removed.",
    )
    defaults.update(kwargs)
    return DriftChange(**defaults)


def test_verification_result_fully_resolved_true_when_no_remaining_and_tests_pass() -> None:
    vr = VerificationResult(
        resolved_changes=(_make_change(),),
        remaining_changes=(),
        tests_passed=True,
        test_output="",
    )
    assert vr.fully_resolved is True


def test_verification_result_fully_resolved_false_when_remaining_changes() -> None:
    change = _make_change()
    vr = VerificationResult(
        resolved_changes=(),
        remaining_changes=(change,),
        tests_passed=True,
        test_output="",
    )
    assert vr.fully_resolved is False


def test_verification_result_fully_resolved_false_when_tests_fail() -> None:
    vr = VerificationResult(
        resolved_changes=(_make_change(),),
        remaining_changes=(),
        tests_passed=False,
        test_output="FAILED tests/test_x.py::test_y",
    )
    assert vr.fully_resolved is False


def test_verification_result_is_immutable() -> None:
    vr = VerificationResult(
        resolved_changes=(),
        remaining_changes=(),
        tests_passed=True,
        test_output="",
    )
    with pytest.raises((AttributeError, TypeError)):
        vr.tests_passed = False  # type: ignore[misc]


# ═══════════════════════════════════════════════════════════════════════════════
# Serialisation — serialize_plan
# ═══════════════════════════════════════════════════════════════════════════════


def test_serialize_plan_returns_list_of_dicts() -> None:
    records = serialize_plan(_plan())

    assert isinstance(records, list)
    assert all(isinstance(r, dict) for r in records)


def test_serialize_plan_contains_all_actions() -> None:
    plan = _plan()
    records = serialize_plan(plan)

    assert len(records) == len(plan.actions)


def test_serialize_plan_all_values_are_plain_python_types() -> None:
    for record in serialize_plan(_plan()):
        for value in record.values():
            assert isinstance(value, (str, int, float, bool, type(None)))


def test_serialize_plan_required_keys_present() -> None:
    required = {
        "file_path", "line_number", "matched_reference", "endpoint",
        "method", "severity", "change_type", "affected_code",
        "proposed_change", "reason",
    }
    for record in serialize_plan(_plan()):
        assert required <= set(record.keys())


def test_serialize_plan_severity_is_string_value() -> None:
    for record in serialize_plan(_plan()):
        assert record["severity"] in {"breaking", "non-breaking", "warning"}


def test_serialize_plan_change_type_is_string_value() -> None:
    valid_change_types = {ct.value for ct in ChangeType}
    for record in serialize_plan(_plan()):
        assert record["change_type"] in valid_change_types


def test_serialize_plan_is_json_serialisable() -> None:
    records = serialize_plan(_plan())
    # Must not raise.
    dumped = json.dumps(records)
    reloaded = json.loads(dumped)
    assert len(reloaded) == len(records)


def test_serialize_plan_round_trip_preserves_line_numbers() -> None:
    plan = _plan()
    records = serialize_plan(plan)

    for action, record in zip(plan.actions, records):
        assert record["line_number"] == action.line_number
        assert record["file_path"] == action.file_path
        assert record["matched_reference"] == action.matched_reference


def test_serialize_plan_empty_plan_returns_empty_list() -> None:
    empty_plan = RemediationPlan(actions=())
    assert serialize_plan(empty_plan) == []


# ═══════════════════════════════════════════════════════════════════════════════
# Serialisation — write_plan
# ═══════════════════════════════════════════════════════════════════════════════


def test_write_plan_creates_file(tmp_path: Path) -> None:
    dest = tmp_path / "plan.json"
    write_plan(_plan(), dest)

    assert dest.exists()


def test_write_plan_content_is_valid_json(tmp_path: Path) -> None:
    dest = tmp_path / "plan.json"
    write_plan(_plan(), dest)

    loaded = json.loads(dest.read_text(encoding="utf-8"))
    assert isinstance(loaded, list)


def test_write_plan_creates_parent_directories(tmp_path: Path) -> None:
    dest = tmp_path / "nested" / "deep" / "plan.json"
    write_plan(_plan(), dest)

    assert dest.exists()


def test_write_plan_content_matches_serialize_plan(tmp_path: Path) -> None:
    plan = _plan()
    dest = tmp_path / "plan.json"
    write_plan(plan, dest)

    written = json.loads(dest.read_text(encoding="utf-8"))
    expected = serialize_plan(plan)
    assert written == expected


def test_write_plan_overwrites_existing_file(tmp_path: Path) -> None:
    dest = tmp_path / "plan.json"
    dest.write_text("old content", encoding="utf-8")

    write_plan(_plan(), dest)

    loaded = json.loads(dest.read_text(encoding="utf-8"))
    assert isinstance(loaded, list)


# ═══════════════════════════════════════════════════════════════════════════════
# Brief builder — build_file_brief
# ═══════════════════════════════════════════════════════════════════════════════


def _client_file(ctx=None):
    ctx = ctx or _context()
    return next(f for f in ctx.affected_files if f.file_path == "client.py"), ctx


def test_build_file_brief_returns_non_empty_string() -> None:
    af, ctx = _client_file()
    brief = build_file_brief(af, ctx)

    assert isinstance(brief, str)
    assert len(brief) > 0


def test_brief_contains_file_path() -> None:
    af, ctx = _client_file()
    brief = build_file_brief(af, ctx)

    assert af.file_path in brief


def test_brief_contains_language() -> None:
    af, ctx = _client_file()
    brief = build_file_brief(af, ctx)

    assert af.language in brief


def test_brief_contains_endpoint() -> None:
    af, ctx = _client_file()
    brief = build_file_brief(af, ctx)

    assert "/users/{userId}" in brief


def test_brief_contains_expected_contract_section() -> None:
    af, ctx = _client_file()
    brief = build_file_brief(af, ctx)

    assert "EXPECTED CONTRACT" in brief


def test_brief_contains_actual_contract_section() -> None:
    af, ctx = _client_file()
    brief = build_file_brief(af, ctx)

    assert "ACTUAL CONTRACT" in brief


def test_brief_contains_drift_changes_section() -> None:
    af, ctx = _client_file()
    brief = build_file_brief(af, ctx)

    assert "DRIFT CHANGES" in brief


def test_brief_contains_affected_lines_section() -> None:
    af, ctx = _client_file()
    brief = build_file_brief(af, ctx)

    assert "AFFECTED LINES" in brief


def test_brief_contains_full_file_content() -> None:
    af, ctx = _client_file()
    brief = build_file_brief(af, ctx)

    assert "FULL FILE CONTENT" in brief
    # Every source line must appear in the brief.
    for source_line in af.source_lines:
        if source_line.strip():
            assert source_line in brief


def test_brief_contains_instructions_section() -> None:
    af, ctx = _client_file()
    brief = build_file_brief(af, ctx)

    assert "INSTRUCTIONS" in brief


def test_brief_instructs_to_edit_only_the_target_file() -> None:
    af, ctx = _client_file()
    brief = build_file_brief(af, ctx)

    assert "ONLY" in brief
    assert af.file_path in brief


def test_brief_mentions_pytest() -> None:
    af, ctx = _client_file()
    brief = build_file_brief(af, ctx)

    assert "pytest" in brief


def test_brief_mentions_verify_remediation() -> None:
    af, ctx = _client_file()
    brief = build_file_brief(af, ctx)

    assert "verify_remediation" in brief


def test_brief_mentions_resolved_unresolved_verification_failed() -> None:
    af, ctx = _client_file()
    brief = build_file_brief(af, ctx)

    assert "RESOLVED" in brief
    assert "UNRESOLVED" in brief
    assert "VERIFICATION_FAILED" in brief


def test_brief_contains_known_drift_severity() -> None:
    af, ctx = _client_file()
    brief = build_file_brief(af, ctx)

    assert "BREAKING" in brief


def test_brief_contains_proposed_change_text() -> None:
    af, ctx = _client_file()
    brief = build_file_brief(af, ctx)

    # The proposed change for REMOVED_FIELD mentions "remove" or "guard".
    lower = brief.lower()
    assert "remove" in lower or "guard" in lower


def test_brief_is_deterministic() -> None:
    af, ctx = _client_file()
    assert build_file_brief(af, ctx) == build_file_brief(af, ctx)


def test_brief_for_typescript_file() -> None:
    ctx = _context()
    ts_file = next((f for f in ctx.affected_files if f.language == "ts"), None)
    if ts_file is None:
        pytest.skip("no TypeScript file in demo repository")

    brief = build_file_brief(ts_file, ctx)
    assert "LANGUAGE: ts" in brief
    assert ts_file.file_path in brief


# ═══════════════════════════════════════════════════════════════════════════════
# verify_remediation — resolved / remaining / test outcomes
# ═══════════════════════════════════════════════════════════════════════════════


def test_verify_remediation_returns_verification_result() -> None:
    ctx = _context()
    result = verify_remediation(
        EXPECTED_CONTRACT, ACTUAL_CONTRACT, DEMO_REPOSITORY,
        ctx.all_drift_changes,
    )

    assert isinstance(result, VerificationResult)


def test_verify_remediation_all_changes_remain_when_nothing_edited() -> None:
    ctx = _context()
    result = verify_remediation(
        EXPECTED_CONTRACT, ACTUAL_CONTRACT, DEMO_REPOSITORY,
        ctx.all_drift_changes,
    )

    # Nothing was edited; all prior changes should still be present.
    assert len(result.remaining_changes) == len(ctx.all_drift_changes)
    assert len(result.resolved_changes) == 0


def test_verify_remediation_all_resolved_when_identical_contracts() -> None:
    ctx = _context()
    # "Actual" == "expected": all prior drifts disappear.
    result = verify_remediation(
        EXPECTED_CONTRACT, EXPECTED_CONTRACT, DEMO_REPOSITORY,
        ctx.all_drift_changes,
    )

    assert len(result.resolved_changes) == len(ctx.all_drift_changes)
    assert len(result.remaining_changes) == 0


def test_verify_remediation_fully_resolved_property_true_when_all_gone() -> None:
    ctx = _context()
    result = verify_remediation(
        EXPECTED_CONTRACT, EXPECTED_CONTRACT, DEMO_REPOSITORY,
        ctx.all_drift_changes,
    )

    assert result.fully_resolved is True


def test_verify_remediation_fully_resolved_false_when_changes_remain() -> None:
    ctx = _context()
    result = verify_remediation(
        EXPECTED_CONTRACT, ACTUAL_CONTRACT, DEMO_REPOSITORY,
        ctx.all_drift_changes,
    )

    assert result.fully_resolved is False


def test_verify_remediation_no_test_cmd_sets_tests_passed_true() -> None:
    ctx = _context()
    result = verify_remediation(
        EXPECTED_CONTRACT, ACTUAL_CONTRACT, DEMO_REPOSITORY,
        ctx.all_drift_changes,
        test_cmd=None,
    )

    assert result.tests_passed is True
    assert result.test_output == ""


def test_verify_remediation_passing_test_cmd_captured(tmp_path: Path) -> None:
    ctx = _context()
    # Use a simple command guaranteed to succeed on any platform.
    result = verify_remediation(
        EXPECTED_CONTRACT, ACTUAL_CONTRACT, DEMO_REPOSITORY,
        ctx.all_drift_changes,
        test_cmd=["python", "-c", "print('ok')"],
    )

    assert result.tests_passed is True
    assert "ok" in result.test_output


def test_verify_remediation_failing_test_cmd_sets_tests_passed_false(tmp_path: Path) -> None:
    ctx = _context()
    result = verify_remediation(
        EXPECTED_CONTRACT, ACTUAL_CONTRACT, DEMO_REPOSITORY,
        ctx.all_drift_changes,
        test_cmd=["python", "-c", "raise SystemExit(1)"],
    )

    assert result.tests_passed is False


def test_verify_remediation_resolved_and_remaining_are_disjoint() -> None:
    ctx = _context()
    result = verify_remediation(
        EXPECTED_CONTRACT, ACTUAL_CONTRACT, DEMO_REPOSITORY,
        ctx.all_drift_changes,
    )

    resolved_set = set(result.resolved_changes)
    remaining_set = set(result.remaining_changes)
    assert resolved_set.isdisjoint(remaining_set)


def test_verify_remediation_empty_prior_changes_produces_empty_result() -> None:
    result = verify_remediation(
        EXPECTED_CONTRACT, ACTUAL_CONTRACT, DEMO_REPOSITORY,
        prior_changes=(),
    )

    assert result.resolved_changes == ()
    assert result.remaining_changes == ()
    assert result.tests_passed is True


# ═══════════════════════════════════════════════════════════════════════════════
# run_bob_remediation — work-order artefact generation
# ═══════════════════════════════════════════════════════════════════════════════


def test_run_bob_remediation_returns_dict(tmp_path: Path) -> None:
    ctx = _context()
    plan = run_remediation(ctx)
    work_order = run_bob_remediation(ctx, plan, output_dir=tmp_path)

    assert isinstance(work_order, dict)


def test_work_order_has_plan_path_and_file_tasks(tmp_path: Path) -> None:
    ctx = _context()
    plan = run_remediation(ctx)
    work_order = run_bob_remediation(ctx, plan, output_dir=tmp_path)

    assert "plan_path" in work_order
    assert "file_tasks" in work_order


def test_work_order_plan_path_exists_on_disk(tmp_path: Path) -> None:
    ctx = _context()
    plan = run_remediation(ctx)
    work_order = run_bob_remediation(ctx, plan, output_dir=tmp_path)

    assert Path(work_order["plan_path"]).exists()


def test_work_order_plan_file_is_valid_json(tmp_path: Path) -> None:
    ctx = _context()
    plan = run_remediation(ctx)
    work_order = run_bob_remediation(ctx, plan, output_dir=tmp_path)

    content = Path(work_order["plan_path"]).read_text(encoding="utf-8")
    loaded = json.loads(content)
    assert isinstance(loaded, list)
    assert len(loaded) == len(plan.actions)


def test_work_order_file_tasks_count_matches_affected_files(tmp_path: Path) -> None:
    ctx = _context()
    plan = run_remediation(ctx)
    work_order = run_bob_remediation(ctx, plan, output_dir=tmp_path)

    assert len(work_order["file_tasks"]) == len(ctx.affected_files)


def test_work_order_each_task_has_required_keys(tmp_path: Path) -> None:
    ctx = _context()
    plan = run_remediation(ctx)
    work_order = run_bob_remediation(ctx, plan, output_dir=tmp_path)

    required = {"file_path", "brief_path", "action_count", "has_breaking",
                "verify_cmd", "instructions"}
    for task in work_order["file_tasks"]:
        assert required <= set(task.keys())


def test_work_order_brief_files_exist_on_disk(tmp_path: Path) -> None:
    ctx = _context()
    plan = run_remediation(ctx)
    work_order = run_bob_remediation(ctx, plan, output_dir=tmp_path)

    for task in work_order["file_tasks"]:
        assert Path(task["brief_path"]).exists()


def test_work_order_brief_file_contains_expected_sections(tmp_path: Path) -> None:
    ctx = _context()
    plan = run_remediation(ctx)
    work_order = run_bob_remediation(ctx, plan, output_dir=tmp_path)

    for task in work_order["file_tasks"]:
        text = Path(task["brief_path"]).read_text(encoding="utf-8")
        assert "EXPECTED CONTRACT" in text
        assert "ACTUAL CONTRACT" in text
        assert "DRIFT CHANGES" in text
        assert "INSTRUCTIONS" in text


def test_work_order_action_count_matches_plan_actions_for_file(tmp_path: Path) -> None:
    ctx = _context()
    plan = run_remediation(ctx)
    work_order = run_bob_remediation(ctx, plan, output_dir=tmp_path)

    for task in work_order["file_tasks"]:
        expected_count = sum(1 for a in plan.actions if a.file_path == task["file_path"])
        assert task["action_count"] == expected_count


def test_work_order_has_breaking_flag_correct(tmp_path: Path) -> None:
    ctx = _context()
    plan = run_remediation(ctx)
    work_order = run_bob_remediation(ctx, plan, output_dir=tmp_path)

    for task in work_order["file_tasks"]:
        manual = any(
            a.severity is Severity.BREAKING
            for a in plan.actions
            if a.file_path == task["file_path"]
        )
        assert task["has_breaking"] == manual


def test_work_order_instructions_mention_only_the_target_file(tmp_path: Path) -> None:
    ctx = _context()
    plan = run_remediation(ctx)
    work_order = run_bob_remediation(ctx, plan, output_dir=tmp_path)

    for task in work_order["file_tasks"]:
        assert task["file_path"] in task["instructions"]


def test_work_order_is_deterministic(tmp_path: Path) -> None:
    ctx = _context()
    plan = run_remediation(ctx)
    out1 = tmp_path / "run1"
    out2 = tmp_path / "run2"

    wo1 = run_bob_remediation(ctx, plan, output_dir=out1)
    wo2 = run_bob_remediation(ctx, plan, output_dir=out2)

    # File paths differ (different output dirs), but task structure is identical.
    assert len(wo1["file_tasks"]) == len(wo2["file_tasks"])
    for t1, t2 in zip(wo1["file_tasks"], wo2["file_tasks"]):
        assert t1["file_path"] == t2["file_path"]
        assert t1["action_count"] == t2["action_count"]
        assert t1["has_breaking"] == t2["has_breaking"]


def test_work_order_empty_plan_produces_empty_file_tasks(tmp_path: Path) -> None:
    ctx = build_remediation_context(EXPECTED_CONTRACT, EXPECTED_CONTRACT, DEMO_REPOSITORY)
    plan = run_remediation(ctx)
    work_order = run_bob_remediation(ctx, plan, output_dir=tmp_path)

    assert work_order["file_tasks"] == []


# ═══════════════════════════════════════════════════════════════════════════════
# Unresolved and verification-failed outcome scenarios
# ═══════════════════════════════════════════════════════════════════════════════


def test_verification_result_unresolved_scenario() -> None:
    """Simulate what happens when Bob marks an action UNRESOLVED.

    Bob produces a VerificationResult with remaining_changes non-empty
    because it left the file unchanged.  The ActionStatus should be UNRESOLVED.
    """
    change = _make_change()
    # Bob didn't edit the file, so the change is still present.
    result = VerificationResult(
        resolved_changes=(),
        remaining_changes=(change,),
        tests_passed=True,
        test_output="",
    )

    # Derive status the same way the orchestration layer would.
    status = ActionStatus.UNRESOLVED if result.remaining_changes else ActionStatus.RESOLVED
    assert status is ActionStatus.UNRESOLVED
    assert result.fully_resolved is False


def test_verification_result_verification_failed_scenario() -> None:
    """Simulate what happens when Bob edits a file but tests fail."""
    change = _make_change()
    result = VerificationResult(
        resolved_changes=(change,),
        remaining_changes=(),
        tests_passed=False,
        test_output="FAILED tests/test_x.py::test_y - AssertionError",
    )

    # Even if drift is gone, failing tests → VERIFICATION_FAILED.
    status = (
        ActionStatus.VERIFICATION_FAILED
        if not result.tests_passed
        else ActionStatus.RESOLVED
    )
    assert status is ActionStatus.VERIFICATION_FAILED
    assert result.fully_resolved is False
    assert "AssertionError" in result.test_output


def test_action_status_enum_covers_all_four_outcomes() -> None:
    statuses = {s.value for s in ActionStatus}
    assert statuses == {"proposed", "resolved", "unresolved", "verification_failed"}
