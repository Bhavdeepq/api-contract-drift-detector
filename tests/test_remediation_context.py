"""Tests for build_remediation_context() and the remediation model types."""

from pathlib import Path

import pytest

from drift_engine import (
    AffectedFile,
    ApiContract,
    ChangeType,
    DriftChange,
    Endpoint,
    ImpactMatch,
    Operation,
    OperationDiff,
    Parameter,
    RemediationContext,
    Response,
    Schema,
    Severity,
    build_remediation_context,
    parse_openapi_contract,
)


ROOT = Path(__file__).parents[1]
EXPECTED_CONTRACT = ROOT / "examples" / "user-api.openapi.yaml"
ACTUAL_CONTRACT = ROOT / "examples" / "user-api.actual.openapi.yaml"
DEMO_REPOSITORY = ROOT / "examples" / "demo-repository"


# ── build_remediation_context: contract fields ────────────────────────────────


def test_context_holds_both_contracts() -> None:
    ctx = build_remediation_context(EXPECTED_CONTRACT, ACTUAL_CONTRACT, DEMO_REPOSITORY)

    assert ctx.expected_contract.title == "User API"
    assert ctx.expected_contract.version == "1.0.0"
    assert ctx.actual_contract.title == "User API actual implementation"
    assert ctx.actual_contract.version == "1.1.0"


def test_context_repository_path_is_absolute_posix_compatible_string() -> None:
    ctx = build_remediation_context(EXPECTED_CONTRACT, ACTUAL_CONTRACT, DEMO_REPOSITORY)

    assert Path(ctx.repository_path).is_absolute()
    assert Path(ctx.repository_path).is_dir()


# ── build_remediation_context: drift changes ─────────────────────────────────


def test_context_all_drift_changes_are_non_empty_and_sorted() -> None:
    ctx = build_remediation_context(EXPECTED_CONTRACT, ACTUAL_CONTRACT, DEMO_REPOSITORY)

    assert len(ctx.all_drift_changes) > 0
    keys = [(c.endpoint, c.method, c.location, c.change_type.value) for c in ctx.all_drift_changes]
    assert keys == sorted(keys)


def test_context_drift_changes_include_known_breaking_changes() -> None:
    ctx = build_remediation_context(EXPECTED_CONTRACT, ACTUAL_CONTRACT, DEMO_REPOSITORY)

    types = {c.change_type for c in ctx.all_drift_changes}
    assert ChangeType.REMOVED_FIELD in types
    assert ChangeType.FIELD_TYPE_CHANGED in types
    assert ChangeType.ADDED_PARAMETER in types
    assert ChangeType.REMOVED_RESPONSE_STATUS in types


def test_context_drift_changes_match_standalone_compare_contracts() -> None:
    from drift_engine import compare_contracts

    ctx = build_remediation_context(EXPECTED_CONTRACT, ACTUAL_CONTRACT, DEMO_REPOSITORY)
    standalone = compare_contracts(ctx.expected_contract, ctx.actual_contract)

    assert ctx.all_drift_changes == standalone


# ── build_remediation_context: operation diffs ───────────────────────────────


def test_operation_diffs_cover_all_drifted_endpoint_method_pairs() -> None:
    ctx = build_remediation_context(EXPECTED_CONTRACT, ACTUAL_CONTRACT, DEMO_REPOSITORY)

    diff_keys = {(d.endpoint, d.method) for d in ctx.operation_diffs}
    change_keys = {(c.endpoint, c.method) for c in ctx.all_drift_changes}
    assert diff_keys == change_keys


def test_operation_diff_for_shared_endpoint_carries_both_operations() -> None:
    ctx = build_remediation_context(EXPECTED_CONTRACT, ACTUAL_CONTRACT, DEMO_REPOSITORY)

    shared = next(
        d for d in ctx.operation_diffs
        if d.endpoint == "/users/{userId}" and d.method == "GET"
    )
    assert shared.expected_operation is not None
    assert shared.actual_operation is not None
    assert shared.expected_operation.path == "/users/{userId}"
    assert shared.actual_operation.path == "/users/{userId}"


def test_operation_diff_for_added_endpoint_has_no_expected_operation() -> None:
    ctx = build_remediation_context(EXPECTED_CONTRACT, ACTUAL_CONTRACT, DEMO_REPOSITORY)

    # /users POST exists only in the actual contract (ADDED_ENDPOINT).
    added = next(
        (d for d in ctx.operation_diffs if d.endpoint == "/users" and d.method == "POST"),
        None,
    )
    assert added is not None
    assert added.expected_operation is None
    assert added.actual_operation is not None


def test_operation_diff_drift_changes_are_subset_of_all_drift_changes() -> None:
    ctx = build_remediation_context(EXPECTED_CONTRACT, ACTUAL_CONTRACT, DEMO_REPOSITORY)

    for diff in ctx.operation_diffs:
        for change in diff.drift_changes:
            assert change in ctx.all_drift_changes


def test_operation_diffs_are_sorted_by_endpoint_then_method() -> None:
    ctx = build_remediation_context(EXPECTED_CONTRACT, ACTUAL_CONTRACT, DEMO_REPOSITORY)

    keys = [(d.endpoint, d.method) for d in ctx.operation_diffs]
    assert keys == sorted(keys)


# ── build_remediation_context: impact matches ────────────────────────────────


def test_context_impact_matches_are_non_empty() -> None:
    ctx = build_remediation_context(EXPECTED_CONTRACT, ACTUAL_CONTRACT, DEMO_REPOSITORY)

    assert len(ctx.all_impact_matches) > 0


def test_context_impact_matches_match_standalone_analyze() -> None:
    from drift_engine import analyze_repository_impacts

    ctx = build_remediation_context(EXPECTED_CONTRACT, ACTUAL_CONTRACT, DEMO_REPOSITORY)
    standalone = analyze_repository_impacts(DEMO_REPOSITORY, ctx.all_drift_changes)

    assert ctx.all_impact_matches == standalone


# ── build_remediation_context: affected files ────────────────────────────────


def test_affected_files_cover_all_matched_file_paths() -> None:
    ctx = build_remediation_context(EXPECTED_CONTRACT, ACTUAL_CONTRACT, DEMO_REPOSITORY)

    expected_paths = {m.file_path for m in ctx.all_impact_matches}
    actual_paths = {f.file_path for f in ctx.affected_files}
    assert actual_paths == expected_paths


def test_affected_files_are_sorted_by_file_path() -> None:
    ctx = build_remediation_context(EXPECTED_CONTRACT, ACTUAL_CONTRACT, DEMO_REPOSITORY)

    paths = [f.file_path for f in ctx.affected_files]
    assert paths == sorted(paths)


def test_affected_file_source_lines_are_non_empty() -> None:
    ctx = build_remediation_context(EXPECTED_CONTRACT, ACTUAL_CONTRACT, DEMO_REPOSITORY)

    for affected in ctx.affected_files:
        assert len(affected.source_lines) > 0


def test_affected_file_language_matches_extension() -> None:
    ctx = build_remediation_context(EXPECTED_CONTRACT, ACTUAL_CONTRACT, DEMO_REPOSITORY)

    for affected in ctx.affected_files:
        ext = Path(affected.file_path).suffix.lstrip(".")
        assert affected.language == ext


def test_affected_file_matches_are_subset_of_all_impact_matches() -> None:
    ctx = build_remediation_context(EXPECTED_CONTRACT, ACTUAL_CONTRACT, DEMO_REPOSITORY)

    for affected in ctx.affected_files:
        for match in affected.matches:
            assert match in ctx.all_impact_matches
            assert match.file_path == affected.file_path


def test_affected_file_line_number_indexes_correct_source_line() -> None:
    ctx = build_remediation_context(EXPECTED_CONTRACT, ACTUAL_CONTRACT, DEMO_REPOSITORY)

    # client.py line 5 is known to contain "email" (from test_impact_analyzer.py).
    client = next(f for f in ctx.affected_files if f.file_path == "client.py")
    email_match = next(m for m in client.matches if m.matched_reference == "email")
    assert email_match.line_number == 5
    assert "email" in client.source_lines[email_match.line_number - 1]


def test_affected_file_matches_contain_all_matches_for_that_file() -> None:
    ctx = build_remediation_context(EXPECTED_CONTRACT, ACTUAL_CONTRACT, DEMO_REPOSITORY)

    for affected in ctx.affected_files:
        all_for_file = tuple(
            m for m in ctx.all_impact_matches if m.file_path == affected.file_path
        )
        assert affected.matches == all_for_file


# ── Frozen / immutability ─────────────────────────────────────────────────────


def test_remediation_context_is_immutable() -> None:
    ctx = build_remediation_context(EXPECTED_CONTRACT, ACTUAL_CONTRACT, DEMO_REPOSITORY)

    with pytest.raises((AttributeError, TypeError)):
        ctx.repository_path = "/other"  # type: ignore[misc]


def test_affected_file_is_immutable() -> None:
    ctx = build_remediation_context(EXPECTED_CONTRACT, ACTUAL_CONTRACT, DEMO_REPOSITORY)
    af = ctx.affected_files[0]

    with pytest.raises((AttributeError, TypeError)):
        af.language = "cobol"  # type: ignore[misc]


def test_operation_diff_is_immutable() -> None:
    ctx = build_remediation_context(EXPECTED_CONTRACT, ACTUAL_CONTRACT, DEMO_REPOSITORY)
    diff = ctx.operation_diffs[0]

    with pytest.raises((AttributeError, TypeError)):
        diff.endpoint = "/mutated"  # type: ignore[misc]


# ── Error handling ────────────────────────────────────────────────────────────


def test_invalid_repository_path_raises_value_error(tmp_path: Path) -> None:
    missing = tmp_path / "no-such-dir"

    with pytest.raises(ValueError, match="existing directory"):
        build_remediation_context(EXPECTED_CONTRACT, ACTUAL_CONTRACT, missing)


def test_invalid_contract_path_raises_contract_parse_error(tmp_path: Path) -> None:
    from drift_engine import ContractParseError

    bad = tmp_path / "bad.yaml"
    bad.write_text("not: valid: openapi", encoding="utf-8")

    with pytest.raises(ContractParseError):
        build_remediation_context(bad, ACTUAL_CONTRACT, DEMO_REPOSITORY)


# ── Determinism ───────────────────────────────────────────────────────────────


def test_build_remediation_context_is_deterministic() -> None:
    ctx1 = build_remediation_context(EXPECTED_CONTRACT, ACTUAL_CONTRACT, DEMO_REPOSITORY)
    ctx2 = build_remediation_context(EXPECTED_CONTRACT, ACTUAL_CONTRACT, DEMO_REPOSITORY)

    assert ctx1.all_drift_changes == ctx2.all_drift_changes
    assert ctx1.all_impact_matches == ctx2.all_impact_matches
    assert ctx1.affected_files == ctx2.affected_files
    assert ctx1.operation_diffs == ctx2.operation_diffs


# ── OperationDiff full Operation detail ──────────────────────────────────────


def test_operation_diff_carries_full_schema_not_just_display_strings() -> None:
    ctx = build_remediation_context(EXPECTED_CONTRACT, ACTUAL_CONTRACT, DEMO_REPOSITORY)

    diff = next(d for d in ctx.operation_diffs if d.endpoint == "/users/{userId}")
    # The expected contract has 3 required fields on the 200 response.
    expected_op = diff.expected_operation
    assert expected_op is not None
    response_200 = next(r for r in expected_op.responses if r.status_code == "200")
    schema = response_200.schemas[0][1]
    assert schema.type == "object"
    assert set(schema.required_fields) == {"id", "name", "email"}
