# AGENTS.md

This file provides guidance to agents when working with code in this repository.

## Repository layout

Two independent test suites in two different directories — **do not conflate them**:

- `backend/tests/` — FastAPI endpoint tests. Must be run **from inside `backend/`** because `pytest.ini` sets `pythonpath = .` (so `from app.main import app` resolves correctly).
- `tests/` — cross-project drift-engine tests. Must be run **from the repository root** because they import `drift_engine` as a top-level package.

## Commands

### Backend tests (from `backend/`)
```powershell
pytest                                      # all backend tests
pytest tests/test_main.py::test_health_returns_ok   # single test
```

### Drift-engine / cross-project tests (from repo root)
```powershell
pytest tests/                               # all drift-engine tests
pytest tests/test_drift_detector.py::test_identical_contract_has_no_drift  # single test
```

### Backend dev server (from `backend/`)
```powershell
uvicorn app.main:app --reload
```

### Frontend (from `frontend/`)
```powershell
npm run dev        # Vite dev server on :5173
```

## Critical architecture rules

- `drift_engine/` is a **pure, I/O-free Python package** — `compare_contracts()` and `parse_openapi_contract()` have no side effects. Keep all new drift-engine logic the same way.
- `drift_engine/__init__.py` is the public API surface. Every new public symbol must be added to `__all__` there.
- All models in `drift_engine/models.py` and `drift_engine/changes.py` are **`frozen=True` dataclasses**. New models must follow the same pattern.
- The impact analyzer reads file content internally but **does not surface it** in `ImpactMatch` — the struct only stores `file_path`, `line_number`, and `matched_reference`.
- `VITE_API_URL` env var overrides the frontend's backend base URL (defaults to `http://localhost:8000`). CORS is locked to `http://localhost:5173` in `backend/app/main.py`.

## Python code style (inferred from codebase — no linter config present)

- `from __future__ import annotations` at the top of every `drift_engine/` module.
- Type annotations on every function signature, including return type. Use built-in generics (`tuple[str, ...]`, `dict[str, Any]`) not `typing.Tuple/Dict`.
- Private helpers are module-level functions prefixed with `_`, not methods on a class.
- Enum values are lowercase strings matching the attribute name (`BREAKING = "breaking"`).
- Collections returned from public functions are always `tuple[..., ...]`, never `list`.
- Sort keys are expressed as `tuple` returns on standalone `_sort_key` / `_drift_key` helper functions, not inline lambdas with multiple fields.
- Error messages in `ContractParseError` quote the offending key/context in single quotes: `"Expected 'info' to be an object."`.

## Testing conventions

- Test functions use plain `assert` (no helper wrappers).
- Fixture contracts are built inline with `ApiContract(...)` / `Operation(...)` constructors — there are factory helpers `_contract()` and `_operation()` defined at the top of `tests/test_drift_detector.py`; reuse or follow that pattern.
- The demo consumer repo lives at `examples/demo-repository/` and is used as a live fixture by `tests/test_impact_analyzer.py`. Do not add build artifacts or new files there unless they are intentional test targets.
- `node_modules/`, `dist/`, and `venv/` inside `examples/demo-repository/` are **intentionally present and ignored by the impact scanner** — the ignored-directory test asserts no matches come from them.
