"""End-to-end remediation demo tests.

Separation contract
-------------------
``examples/demo-repository/``   — FROZEN.  Never modified.  Used by all
                                   existing impact-analyzer, remediation-
                                   context, and orchestrator tests.

``examples/remediation-demo/``  — MUTABLE.  Bob edited these files to
                                   genuinely remove the obsolete ``email``
                                   dependencies.  Tests in this module
                                   operate only against the mutable repo.

The two directories start with identical content.  The mutable copies have
had the ``email`` references replaced with the surviving field ``id`` (Python,
TypeScript) or ``name`` (JSX), so impact analysis against the mutable repo
finds zero ``email`` hits.

Verification method
-------------------
``verify_impact_resolved()`` — the correct signal for consumer-code
remediation.  It re-runs ``analyze_repository_impacts()`` and counts how
many matches remain for a set of reference tokens.  A count of 0 means the
reference is genuinely gone from the consumer source.

``verify_remediation()`` measures contract drift (``compare_contracts``
output) which is unchanged by edits to consumer files — it stays correct
for contract-level verification but is not used here.
"""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from drift_engine import (
    ChangeType,
    Severity,
    analyze_repository_impacts,
    build_remediation_context,
    compare_contracts,
    parse_openapi_contract,
)
from agents.bob_orchestrator import verify_impact_resolved
from agents.remediation_workflow import run_remediation


ROOT               = Path(__file__).parents[1]
EXPECTED_CONTRACT  = ROOT / "examples" / "user-api.openapi.yaml"
ACTUAL_CONTRACT    = ROOT / "examples" / "user-api.actual.openapi.yaml"
FROZEN_REPO        = ROOT / "examples" / "demo-repository"
MUTABLE_REPO       = ROOT / "examples" / "remediation-demo"


# ── Helpers ───────────────────────────────────────────────────────────────────


def _drift_changes():
    expected = parse_openapi_contract(EXPECTED_CONTRACT)
    actual   = parse_openapi_contract(ACTUAL_CONTRACT)
    return compare_contracts(expected, actual)


# ═══════════════════════════════════════════════════════════════════════════════
# Fixture separation — frozen repo is untouched
# ═══════════════════════════════════════════════════════════════════════════════


def test_frozen_fixture_still_contains_email_references() -> None:
    """The frozen demo-repository must never be modified."""
    changes = _drift_changes()
    matches = analyze_repository_impacts(FROZEN_REPO, changes)
    email_matches = [m for m in matches if m.matched_reference == "email"]

    assert len(email_matches) == 3, (
        "Frozen fixture must still have exactly 3 email matches; "
        "do not modify examples/demo-repository/"
    )


def test_frozen_fixture_email_line_numbers_unchanged() -> None:
    """Exact line-number assertions that existing tests rely on."""
    changes = _drift_changes()
    matches = analyze_repository_impacts(FROZEN_REPO, changes)

    client_email = next(
        m for m in matches
        if m.file_path == "client.py" and m.matched_reference == "email"
    )
    assert client_email.line_number == 5

    usercard_email = next(
        m for m in matches
        if m.file_path == "web/UserCard.jsx" and m.matched_reference == "email"
    )
    assert usercard_email.line_number == 1

    api_ts_email = next(
        m for m in matches
        if m.file_path == "web/api.ts" and m.matched_reference == "email"
    )
    assert api_ts_email.line_number == 3


def test_mutable_repo_and_frozen_repo_are_at_separate_paths() -> None:
    assert FROZEN_REPO != MUTABLE_REPO
    assert FROZEN_REPO.is_dir()
    assert MUTABLE_REPO.is_dir()


# ═══════════════════════════════════════════════════════════════════════════════
# Pre-remediation state — mutable repo starts with the same broken code
# ═══════════════════════════════════════════════════════════════════════════════


def test_mutable_repo_contains_same_source_files_as_frozen() -> None:
    """The remediation-demo directory has the same file layout."""
    frozen_files  = {p.relative_to(FROZEN_REPO).as_posix()  for p in FROZEN_REPO.rglob("*")  if p.is_file()}
    mutable_files = {p.relative_to(MUTABLE_REPO).as_posix() for p in MUTABLE_REPO.rglob("*") if p.is_file()}
    assert frozen_files == mutable_files


# ═══════════════════════════════════════════════════════════════════════════════
# Post-remediation state — email references are genuinely gone
# ═══════════════════════════════════════════════════════════════════════════════


def test_email_impact_matches_are_zero_in_mutable_repo() -> None:
    """Core verification: no email references survive in the mutable repo."""
    changes = _drift_changes()
    counts = verify_impact_resolved(MUTABLE_REPO, changes, ("email",))

    assert counts["email"] == 0, (
        f"Expected 0 email matches in remediation-demo, got {counts['email']}. "
        "Bob must remove/replace all email references, not merely guard them."
    )


def test_email_impact_matches_are_absent_by_file() -> None:
    """Each individual mutable file must have no email reference."""
    changes = _drift_changes()
    matches = analyze_repository_impacts(MUTABLE_REPO, changes)
    email_matches = [m for m in matches if m.matched_reference == "email"]

    assert email_matches == [], (
        f"Unexpected email matches: {[(m.file_path, m.line_number) for m in email_matches]}"
    )


def test_client_py_no_longer_reads_email_field() -> None:
    client = (MUTABLE_REPO / "client.py").read_text(encoding="utf-8")
    assert "email" not in client


def test_usercard_jsx_no_longer_renders_email() -> None:
    usercard = (MUTABLE_REPO / "web" / "UserCard.jsx").read_text(encoding="utf-8")
    assert "email" not in usercard


def test_api_ts_no_longer_exports_email_accessor() -> None:
    api_ts = (MUTABLE_REPO / "web" / "api.ts").read_text(encoding="utf-8")
    assert "email" not in api_ts


def test_mutable_repo_client_py_uses_surviving_field() -> None:
    """Replacement must use a field that actually exists in the actual contract."""
    client = (MUTABLE_REPO / "client.py").read_text(encoding="utf-8")
    # The actual contract has 'id' (optional string) and 'name' (required integer).
    assert "id" in client or "name" in client


def test_mutable_repo_usercard_jsx_uses_surviving_field() -> None:
    usercard = (MUTABLE_REPO / "web" / "UserCard.jsx").read_text(encoding="utf-8")
    assert "name" in usercard or "id" in usercard


def test_mutable_repo_api_ts_uses_surviving_field() -> None:
    api_ts = (MUTABLE_REPO / "web" / "api.ts").read_text(encoding="utf-8")
    assert "id" in api_ts or "name" in api_ts


# ═══════════════════════════════════════════════════════════════════════════════
# verify_impact_resolved() function behaviour
# ═══════════════════════════════════════════════════════════════════════════════


def test_verify_impact_resolved_returns_dict() -> None:
    changes = _drift_changes()
    result = verify_impact_resolved(MUTABLE_REPO, changes, ("email",))
    assert isinstance(result, dict)


def test_verify_impact_resolved_keys_match_requested_tokens() -> None:
    changes = _drift_changes()
    tokens = ("email", "includeDetails")
    result = verify_impact_resolved(MUTABLE_REPO, changes, tokens)
    assert set(result.keys()) == set(tokens)


def test_verify_impact_resolved_email_is_zero_after_remediation() -> None:
    changes = _drift_changes()
    result = verify_impact_resolved(MUTABLE_REPO, changes, ("email",))
    assert result["email"] == 0


def test_verify_impact_resolved_email_is_nonzero_in_frozen_fixture() -> None:
    """Confirm the function correctly detects un-remediated references."""
    changes = _drift_changes()
    result = verify_impact_resolved(FROZEN_REPO, changes, ("email",))
    assert result["email"] > 0


def test_verify_impact_resolved_includeDetails_still_present_in_mutable_repo() -> None:
    """query.tsx still references includeDetails — that drift is not being remediated."""
    changes = _drift_changes()
    result = verify_impact_resolved(MUTABLE_REPO, changes, ("includeDetails",))
    assert result["includeDetails"] > 0


def test_verify_impact_resolved_empty_tokens_returns_empty_dict() -> None:
    changes = _drift_changes()
    result = verify_impact_resolved(MUTABLE_REPO, changes, ())
    assert result == {}


def test_verify_impact_resolved_counts_are_non_negative_integers() -> None:
    changes = _drift_changes()
    result = verify_impact_resolved(MUTABLE_REPO, changes, ("email", "name", "id"))
    for token, count in result.items():
        assert isinstance(count, int)
        assert count >= 0


# ═══════════════════════════════════════════════════════════════════════════════
# Full remediation pipeline on the mutable repo
# ═══════════════════════════════════════════════════════════════════════════════


def test_build_remediation_context_on_mutable_repo() -> None:
    ctx = build_remediation_context(EXPECTED_CONTRACT, ACTUAL_CONTRACT, MUTABLE_REPO)
    assert ctx.repository_path == str(MUTABLE_REPO.resolve())


def test_run_remediation_on_mutable_repo_produces_no_email_actions() -> None:
    """After remediation, the plan built against the mutable repo has no email actions."""
    ctx  = build_remediation_context(EXPECTED_CONTRACT, ACTUAL_CONTRACT, MUTABLE_REPO)
    plan = run_remediation(ctx)

    email_actions = [a for a in plan.actions if a.matched_reference == "email"]
    assert email_actions == [], (
        f"Expected no email actions after remediation, got {len(email_actions)}: "
        f"{[(a.file_path, a.line_number) for a in email_actions]}"
    )


def test_mutable_repo_still_has_other_drift_impacts() -> None:
    """Remediating email does not affect other drifts like includeDetails."""
    ctx = build_remediation_context(EXPECTED_CONTRACT, ACTUAL_CONTRACT, MUTABLE_REPO)
    plan = run_remediation(ctx)

    include_details_actions = [a for a in plan.actions if a.matched_reference == "includeDetails"]
    assert len(include_details_actions) > 0


# ═══════════════════════════════════════════════════════════════════════════════
# Ignored directories are still excluded from the mutable repo
# ═══════════════════════════════════════════════════════════════════════════════


def test_ignored_directories_not_scanned_in_mutable_repo() -> None:
    changes = _drift_changes()
    matches = analyze_repository_impacts(MUTABLE_REPO, changes)
    paths = {m.file_path for m in matches}
    assert not {"node_modules/ignored.js", "dist/bundle.js", "venv/ignored.py"} & paths


# ═══════════════════════════════════════════════════════════════════════════════
# Frozen fixture test suite guard — these must never fail
# ═══════════════════════════════════════════════════════════════════════════════


def test_frozen_fixture_impact_matches_unchanged_by_mutable_edits() -> None:
    """Any edit to the mutable repo must not change frozen fixture results."""
    changes = _drift_changes()
    frozen_matches = analyze_repository_impacts(FROZEN_REPO, changes)
    frozen_email = [m for m in frozen_matches if m.matched_reference == "email"]

    # Same assertion as test_impact_analyzer.py:42
    client_match = next(
        (m for m in frozen_email if m.file_path == "client.py"), None
    )
    assert client_match is not None
    assert client_match.line_number == 5
    assert client_match.related_drift_change.change_type is ChangeType.REMOVED_FIELD


def test_frozen_fixture_has_email_in_usercard(  ) -> None:
    """Mirror of test_impact_analyzer.py:34 — must keep passing."""
    changes = _drift_changes()
    matches = analyze_repository_impacts(FROZEN_REPO, changes)
    assert any(
        m.matched_reference == "email" and m.file_path == "web/UserCard.jsx"
        for m in matches
    )


# ═══════════════════════════════════════════════════════════════════════════════
# tmp_path copy — verify_impact_resolved works on a fresh copy too
# ═══════════════════════════════════════════════════════════════════════════════


def test_verify_impact_resolved_works_on_tmp_copy_of_mutable_repo(tmp_path: Path) -> None:
    copy = tmp_path / "repo"
    shutil.copytree(MUTABLE_REPO, copy)

    changes = _drift_changes()
    result = verify_impact_resolved(copy, changes, ("email",))
    assert result["email"] == 0


def test_verify_impact_resolved_detects_references_in_tmp_broken_copy(tmp_path: Path) -> None:
    """If we copy the frozen fixture (broken code) the count is non-zero."""
    copy = tmp_path / "broken"
    shutil.copytree(FROZEN_REPO, copy)

    changes = _drift_changes()
    result = verify_impact_resolved(copy, changes, ("email",))
    assert result["email"] == 3
