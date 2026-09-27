from pathlib import Path

from drift_engine import (
    ApiContract,
    ChangeType,
    Endpoint,
    Field,
    Operation,
    Parameter,
    RequestBody,
    Response,
    Schema,
    Severity,
    compare_contracts,
    parse_openapi_contract,
)


ROOT = Path(__file__).parents[1]


def _contract(operation: Operation) -> ApiContract:
    return ApiContract("3.0.3", "Test", "1", (Endpoint(operation.path, (operation,)),))


def _operation(*, parameters: tuple[Parameter, ...] = (), request: Schema | None = None, response: Schema | None = None,
               statuses: tuple[str, ...] = ("200",)) -> Operation:
    bodies = (RequestBody("application/json", True, request),) if request else ()
    responses = tuple(Response(status, (("application/json", response),) if response else ()) for status in statuses)
    return Operation("POST", "/widgets", (), parameters, bodies, responses)


def test_example_and_modified_contract_produce_expected_drifts() -> None:
    expected = parse_openapi_contract(ROOT / "examples" / "user-api.openapi.yaml")
    actual = parse_openapi_contract(ROOT / "examples" / "user-api.actual.openapi.yaml")

    changes = compare_contracts(expected, actual)
    summary = {(change.change_type, change.expected_value, change.actual_value, change.severity) for change in changes}

    assert (ChangeType.ADDED_ENDPOINT, None, "present", Severity.NON_BREAKING) in summary
    assert (ChangeType.ADDED_PARAMETER, None, "query boolean (required)", Severity.BREAKING) in summary
    assert (ChangeType.REMOVED_FIELD, "string (required)", None, Severity.BREAKING) in summary
    assert (ChangeType.FIELD_TYPE_CHANGED, "string", "integer", Severity.BREAKING) in summary
    assert (ChangeType.REQUIRED_TO_OPTIONAL, "required", "optional", Severity.BREAKING) in summary
    assert (ChangeType.ADDED_FIELD, None, "string (optional)", Severity.NON_BREAKING) in summary
    assert (ChangeType.REMOVED_RESPONSE_STATUS, "404", None, Severity.BREAKING) in summary
    assert (ChangeType.ADDED_RESPONSE_STATUS, None, "202", Severity.WARNING) in summary


def test_identical_contract_has_no_drift() -> None:
    contract = parse_openapi_contract(ROOT / "examples" / "user-api.openapi.yaml")

    assert compare_contracts(contract, contract) == ()


def test_added_and_removed_operations_are_classified_deterministically() -> None:
    expected = _contract(_operation())
    actual = ApiContract("3.0.3", "Test", "1", (Endpoint("/other", (Operation("GET", "/other", responses=(Response("200"),)),)),))

    changes = compare_contracts(expected, actual)

    assert [(change.change_type, change.severity) for change in changes] == [
        (ChangeType.ADDED_ENDPOINT, Severity.NON_BREAKING),
        (ChangeType.REMOVED_ENDPOINT, Severity.BREAKING),
    ]


def test_request_parameter_add_remove_type_and_required_changes() -> None:
    before = _contract(_operation(parameters=(
        Parameter("page", "query", False, Schema("integer")),
        Parameter("legacy", "query", False, Schema("string")),
        Parameter("sort", "query", False, Schema("string")),
    )))
    after = _contract(_operation(parameters=(
        Parameter("page", "query", True, Schema("string")),
        Parameter("limit", "query", True, Schema("integer")),
    )))

    changes = compare_contracts(before, after)
    by_type = {change.change_type: change for change in changes}
    assert by_type[ChangeType.ADDED_PARAMETER].severity is Severity.BREAKING
    assert by_type[ChangeType.REMOVED_PARAMETER].severity is Severity.BREAKING
    assert by_type[ChangeType.PARAMETER_TYPE_CHANGED].severity is Severity.BREAKING
    assert by_type[ChangeType.OPTIONAL_TO_REQUIRED].location == "parameter"
    assert by_type[ChangeType.OPTIONAL_TO_REQUIRED].severity is Severity.BREAKING


def test_request_and_response_field_rules_cover_add_remove_type_and_requiredness() -> None:
    expected_schema = Schema("object", fields=(
        Field("drop", "string", False), Field("kind", "string", False), Field("loosen", "string", True),
        Field("tighten", "string", False), Field("stable", "string", False),
    ))
    actual_schema = Schema("object", fields=(
        Field("add", "string", True), Field("kind", "integer", False), Field("loosen", "string", False),
        Field("tighten", "string", True), Field("stable", "string", False),
    ))
    request_changes = compare_contracts(_contract(_operation(request=expected_schema)), _contract(_operation(request=actual_schema)))
    request_by_type = {change.change_type: change for change in request_changes if change.location == "request"}
    assert request_by_type[ChangeType.ADDED_FIELD].severity is Severity.BREAKING
    assert request_by_type[ChangeType.REMOVED_FIELD].severity is Severity.BREAKING
    assert request_by_type[ChangeType.FIELD_TYPE_CHANGED].severity is Severity.BREAKING
    assert request_by_type[ChangeType.REQUIRED_TO_OPTIONAL].severity is Severity.NON_BREAKING
    assert request_by_type[ChangeType.OPTIONAL_TO_REQUIRED].severity is Severity.BREAKING

    response_changes = compare_contracts(_contract(_operation(response=expected_schema)), _contract(_operation(response=actual_schema)))
    response_by_type = {change.change_type: change for change in response_changes if change.location == "response"}
    assert response_by_type[ChangeType.ADDED_FIELD].severity is Severity.NON_BREAKING
    assert response_by_type[ChangeType.REQUIRED_TO_OPTIONAL].severity is Severity.BREAKING
    assert response_by_type[ChangeType.OPTIONAL_TO_REQUIRED].severity is Severity.NON_BREAKING


def test_nested_fields_and_response_statuses_are_compared() -> None:
    before = Schema("object", fields=(Field("profile", "object", False, schema=Schema("object", fields=(Field("name", "string", True),))),))
    after = Schema("object", fields=(Field("profile", "object", False, schema=Schema("object", fields=(Field("name", "integer", True),))),))
    changes = compare_contracts(_contract(_operation(response=before, statuses=("200", "404"))),
                                _contract(_operation(response=after, statuses=("200", "201"))))

    assert any(change.change_type is ChangeType.FIELD_TYPE_CHANGED and "profile.name" in change.explanation for change in changes)
    assert any(change.change_type is ChangeType.REMOVED_RESPONSE_STATUS and change.expected_value == "404" for change in changes)
    assert any(change.change_type is ChangeType.ADDED_RESPONSE_STATUS and change.actual_value == "201" for change in changes)


def test_comparison_order_is_stable() -> None:
    expected = _contract(_operation(response=Schema("object", fields=(Field("z", "string", False), Field("a", "string", False)))))
    actual = _contract(_operation(response=Schema("object", fields=(Field("c", "string", False),))))

    first = compare_contracts(expected, actual)
    assert first == compare_contracts(expected, actual)
    assert [change.expected_value or change.actual_value for change in first] == ["string (optional)", "string (optional)", "string (optional)"]
