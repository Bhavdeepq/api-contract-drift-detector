from pathlib import Path

import pytest

from drift_engine import (
    ChangeType,
    DriftChange,
    ImpactConfidence,
    Severity,
    analyze_repository_impacts,
    compare_contracts,
    parse_openapi_contract,
)


ROOT = Path(__file__).parents[1]
DEMO_REPOSITORY = ROOT / "examples" / "demo-repository"


def _example_changes() -> tuple[DriftChange, ...]:
    expected = parse_openapi_contract(ROOT / "examples" / "user-api.openapi.yaml")
    actual = parse_openapi_contract(ROOT / "examples" / "user-api.actual.openapi.yaml")
    return compare_contracts(expected, actual)


def test_finds_endpoint_field_and_parameter_references_in_all_supported_languages() -> None:
    matches = analyze_repository_impacts(DEMO_REPOSITORY, _example_changes())

    assert {match.file_path for match in matches} >= {
        "client.py", "web/api.ts", "web/UserCard.jsx", "web/query.tsx"
    }
    assert all(match.confidence is ImpactConfidence.HIGH for match in matches)
    assert any(match.matched_reference == "/users/{userId}" and match.file_path == "client.py" for match in matches)
    assert any(match.matched_reference == "email" and match.file_path == "web/UserCard.jsx" for match in matches)
    assert any(match.matched_reference == "includeDetails" and match.file_path == "web/query.tsx" for match in matches)


def test_matches_retain_the_related_drift_change_and_line_numbers() -> None:
    matches = analyze_repository_impacts(DEMO_REPOSITORY, _example_changes())
    email_match = next(match for match in matches if match.file_path == "client.py" and match.matched_reference == "email")

    assert email_match.line_number == 5
    assert email_match.related_drift_change.change_type is ChangeType.REMOVED_FIELD
    assert email_match.related_drift_change.location == "response"
    assert email_match.reason == "Exact field or parameter reference matched in supported source code."


def test_ignored_and_unsupported_files_are_not_scanned() -> None:
    matches = analyze_repository_impacts(DEMO_REPOSITORY, _example_changes())
    paths = {match.file_path for match in matches}

    assert not {"node_modules/ignored.js", "dist/bundle.js", "venv/ignored.py"} & paths


def test_results_are_deterministic_and_retain_all_change_context() -> None:
    changes = _example_changes()
    first = analyze_repository_impacts(DEMO_REPOSITORY, reversed(changes))
    second = analyze_repository_impacts(DEMO_REPOSITORY, changes)

    assert first == second
    assert all(match.related_drift_change in changes for match in first)


def test_invalid_repository_path_has_a_clear_error(tmp_path: Path) -> None:
    missing = tmp_path / "missing"

    with pytest.raises(ValueError, match="existing directory"):
        analyze_repository_impacts(missing, ())


def test_unrelated_identifier_substrings_do_not_match() -> None:
    change = DriftChange(
        endpoint="/nothing",
        method="GET",
        location="response",
        change_type=ChangeType.REMOVED_FIELD,
        expected_value="string (required)",
        actual_value=None,
        severity=Severity.BREAKING,
        explanation="Response field 'mail' was removed.",
    )

    matches = analyze_repository_impacts(DEMO_REPOSITORY, (change,))
    assert matches == ()
