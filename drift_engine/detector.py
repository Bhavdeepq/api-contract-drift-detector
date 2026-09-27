"""Pure deterministic comparison of two parsed OpenAPI contracts."""

from __future__ import annotations

from collections.abc import Iterable

from .changes import ChangeType, DriftChange, Severity
from .models import ApiContract, Field, Operation, Parameter, RequestBody, Response, Schema


def compare_contracts(expected: ApiContract, actual: ApiContract) -> tuple[DriftChange, ...]:
    """Return all MVP contract drifts, consistently ordered by endpoint and method.

    ``expected`` is the documented/baseline contract; ``actual`` is the observed
    implementation contract. The function has no I/O and makes no probabilistic
    decisions, making it suitable for repeatable CI checks.
    """

    expected_operations = _operations(expected)
    actual_operations = _operations(actual)
    changes: list[DriftChange] = []

    for key in sorted(expected_operations.keys() - actual_operations.keys()):
        path, method = key
        changes.append(_change(path, method, "endpoint", ChangeType.REMOVED_ENDPOINT, "present", None, Severity.BREAKING,
                               "The documented endpoint is not available in the actual contract."))
    for key in sorted(actual_operations.keys() - expected_operations.keys()):
        path, method = key
        changes.append(_change(path, method, "endpoint", ChangeType.ADDED_ENDPOINT, None, "present", Severity.NON_BREAKING,
                               "The actual contract exposes an endpoint not documented in the expected contract."))
    for key in sorted(expected_operations.keys() & actual_operations.keys()):
        changes.extend(_compare_operation(expected_operations[key], actual_operations[key]))
    return tuple(sorted(changes, key=_sort_key))


def _operations(contract: ApiContract) -> dict[tuple[str, str], Operation]:
    return {(operation.path, operation.method): operation for endpoint in contract.endpoints for operation in endpoint.operations}


def _compare_operation(expected: Operation, actual: Operation) -> list[DriftChange]:
    changes: list[DriftChange] = []
    changes.extend(_compare_parameters(expected, actual))
    changes.extend(_compare_request_bodies(expected, actual))
    changes.extend(_compare_responses(expected, actual))
    return changes


def _compare_parameters(expected: Operation, actual: Operation) -> list[DriftChange]:
    expected_parameters = _parameters(expected)
    actual_parameters = _parameters(actual)
    changes: list[DriftChange] = []
    for key in sorted(expected_parameters.keys() - actual_parameters.keys()):
        parameter = expected_parameters[key]
        changes.append(_change(expected.path, expected.method, "parameter", ChangeType.REMOVED_PARAMETER,
                               _parameter_value(parameter), None, Severity.BREAKING,
                               f"Parameter '{parameter.name}' is no longer accepted."))
    for key in sorted(actual_parameters.keys() - expected_parameters.keys()):
        parameter = actual_parameters[key]
        severity = Severity.BREAKING if parameter.required else Severity.NON_BREAKING
        changes.append(_change(expected.path, expected.method, "parameter", ChangeType.ADDED_PARAMETER,
                               None, _parameter_value(parameter), severity,
                               f"New {parameter.location} parameter '{parameter.name}' was added."))
    for key in sorted(expected_parameters.keys() & actual_parameters.keys()):
        before, after = expected_parameters[key], actual_parameters[key]
        if before.schema.type != after.schema.type:
            changes.append(_change(expected.path, expected.method, "parameter", ChangeType.PARAMETER_TYPE_CHANGED,
                                   before.schema.type, after.schema.type, Severity.BREAKING,
                                   f"Parameter '{before.name}' changed type."))
        changes.extend(_required_change(expected.path, expected.method, "parameter", before.required, after.required,
                                        f"Parameter '{before.name}'"))
    return changes


def _parameters(operation: Operation) -> dict[tuple[str, str], Parameter]:
    return {(parameter.location, parameter.name): parameter for parameter in (*operation.path_parameters, *operation.query_parameters)}


def _compare_request_bodies(expected: Operation, actual: Operation) -> list[DriftChange]:
    before = {body.content_type: body for body in expected.request_bodies}
    after = {body.content_type: body for body in actual.request_bodies}
    changes: list[DriftChange] = []
    for content_type in sorted(before.keys() - after.keys()):
        changes.append(_change(expected.path, expected.method, "request", ChangeType.REMOVED_REQUEST_BODY,
                               content_type, None, Severity.NON_BREAKING,
                               f"Request body '{content_type}' is no longer required or validated."))
    for content_type in sorted(after.keys() - before.keys()):
        body = after[content_type]
        severity = Severity.BREAKING if body.required else Severity.NON_BREAKING
        changes.append(_change(expected.path, expected.method, "request", ChangeType.ADDED_REQUEST_BODY,
                               None, content_type, severity, f"Request body '{content_type}' was added."))
    for content_type in sorted(before.keys() & after.keys()):
        changes.extend(_compare_schema_fields(expected.path, expected.method, "request", before[content_type].schema, after[content_type].schema, ""))
        changes.extend(_required_change(expected.path, expected.method, "request", before[content_type].required, after[content_type].required,
                                        f"Request body '{content_type}'"))
    return changes


def _compare_responses(expected: Operation, actual: Operation) -> list[DriftChange]:
    before = {response.status_code: response for response in expected.responses}
    after = {response.status_code: response for response in actual.responses}
    changes: list[DriftChange] = []
    for status in sorted(before.keys() - after.keys(), key=_status_key):
        changes.append(_change(expected.path, expected.method, "response", ChangeType.REMOVED_RESPONSE_STATUS,
                               status, None, Severity.BREAKING, f"Documented response status {status} is no longer returned."))
    for status in sorted(after.keys() - before.keys(), key=_status_key):
        changes.append(_change(expected.path, expected.method, "response", ChangeType.ADDED_RESPONSE_STATUS,
                               None, status, Severity.WARNING, f"Actual contract returns undocumented response status {status}."))
    for status in sorted(before.keys() & after.keys(), key=_status_key):
        changes.extend(_compare_response_content(expected.path, expected.method, status, before[status], after[status]))
    return changes


def _compare_response_content(path: str, method: str, status: str, expected: Response, actual: Response) -> list[DriftChange]:
    before, after = dict(expected.schemas), dict(actual.schemas)
    changes: list[DriftChange] = []
    for content_type in sorted(before.keys() - after.keys()):
        changes.append(_change(path, method, "response", ChangeType.REMOVED_RESPONSE_CONTENT, content_type, None,
                               Severity.BREAKING, f"Response {status} no longer provides '{content_type}'."))
    for content_type in sorted(after.keys() - before.keys()):
        changes.append(_change(path, method, "response", ChangeType.ADDED_RESPONSE_CONTENT, None, content_type,
                               Severity.WARNING, f"Response {status} adds undocumented content type '{content_type}'."))
    for content_type in sorted(before.keys() & after.keys()):
        changes.extend(_compare_schema_fields(path, method, "response", before[content_type], after[content_type], ""))
    return changes


def _compare_schema_fields(path: str, method: str, location: str, expected: Schema, actual: Schema, prefix: str) -> list[DriftChange]:
    before, after = {field.name: field for field in expected.fields}, {field.name: field for field in actual.fields}
    changes: list[DriftChange] = []
    for name in sorted(before.keys() - after.keys()):
        field = before[name]
        changes.append(_change(path, method, location, ChangeType.REMOVED_FIELD, _field_value(field), None,
                               Severity.BREAKING, f"{location.capitalize()} field '{prefix}{name}' was removed."))
    for name in sorted(after.keys() - before.keys()):
        field = after[name]
        severity = Severity.BREAKING if location == "request" and field.required else Severity.NON_BREAKING
        changes.append(_change(path, method, location, ChangeType.ADDED_FIELD, None, _field_value(field), severity,
                               f"{location.capitalize()} field '{prefix}{name}' was added."))
    for name in sorted(before.keys() & after.keys()):
        old, new = before[name], after[name]
        field_name = f"{prefix}{name}"
        if old.type != new.type:
            changes.append(_change(path, method, location, ChangeType.FIELD_TYPE_CHANGED, old.type, new.type,
                                   Severity.BREAKING, f"{location.capitalize()} field '{field_name}' changed type."))
            continue
        changes.extend(_required_field_change(path, method, location, old, new, field_name))
        changes.extend(_compare_schema_fields(path, method, location, old.schema or Schema(old.type), new.schema or Schema(new.type), f"{field_name}."))
        if old.schema and new.schema and old.schema.items and new.schema.items:
            changes.extend(_compare_schema_fields(path, method, location, old.schema.items, new.schema.items, f"{field_name}[]."))
    return changes


def _required_field_change(path: str, method: str, location: str, old: Field, new: Field, name: str) -> list[DriftChange]:
    if old.required == new.required:
        return []
    if old.required:
        severity = Severity.BREAKING if location == "response" else Severity.NON_BREAKING
        return [_change(path, method, location, ChangeType.REQUIRED_TO_OPTIONAL, "required", "optional", severity,
                        f"{location.capitalize()} field '{name}' is no longer required.")]
    severity = Severity.NON_BREAKING if location == "response" else Severity.BREAKING
    return [_change(path, method, location, ChangeType.OPTIONAL_TO_REQUIRED, "optional", "required", severity,
                    f"{location.capitalize()} field '{name}' is now required.")]


def _required_change(path: str, method: str, location: str, old: bool, new: bool, subject: str) -> list[DriftChange]:
    if old == new:
        return []
    if old:
        return [_change(path, method, location, ChangeType.REQUIRED_TO_OPTIONAL, "required", "optional", Severity.NON_BREAKING,
                        f"{subject} is no longer required.")]
    return [_change(path, method, location, ChangeType.OPTIONAL_TO_REQUIRED, "optional", "required", Severity.BREAKING,
                    f"{subject} is now required.")]


def _change(path: str, method: str, location: str, change_type: ChangeType, expected_value: str | None,
            actual_value: str | None, severity: Severity, explanation: str) -> DriftChange:
    return DriftChange(path, method, location, change_type, expected_value, actual_value, severity, explanation)


def _field_value(field: Field) -> str:
    return f"{field.type} ({'required' if field.required else 'optional'})"


def _parameter_value(parameter: Parameter) -> str:
    return f"{parameter.location} {parameter.schema.type} ({'required' if parameter.required else 'optional'})"


def _status_key(status: str) -> tuple[int, int | str]:
    return (0, int(status)) if status.isdigit() else (1, status)


def _sort_key(change: DriftChange) -> tuple[str, str, str, str, str, str]:
    return (change.endpoint, change.method, change.location, change.change_type.value,
            change.expected_value or "", change.actual_value or "")
