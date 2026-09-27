
# AGENTS.md

This file provides guidance to agents when working with code in this repository.

## Non-obvious coding rules

- **Two test roots, two working directories.** `pytest` in `backend/` runs only FastAPI tests; `pytest tests/` from the repo root runs only drift-engine tests. There is no single command that runs both at once.
- **`drift_engine/__init__.py` is the only public surface.** Adding a new symbol anywhere in the package without also exporting it from `__init__.__all__` means tests and callers cannot import it.
- **`frozen=True` is mandatory on all dataclasses.** All models in `models.py`, `changes.py`, and `impact_models.py` are frozen. New structs must be too — mutable dataclasses will break set/dict keying used in the detector.
- **`compare_contracts()` must stay I/O-free.** The detector is used in CI; any file or network access inside it would break that contract silently.
- **`_NAMED_REFERENCE` regex in `impact.py` is the only way field/parameter names are extracted from `DriftChange.explanation`.** If you change the explanation string format in `detector.py`, you must verify the regex in `impact.py:16` still matches it.
- **`expected_value` / `actual_value` on `DriftChange` are compressed display strings, not full schema objects.** They are produced by `_field_value()` and `_parameter_value()` helper functions at the bottom of `detector.py`. Do not parse them back into structured data.
- **CORS in `backend/app/main.py` is hardcoded to `http://localhost:5173`.** Any backend endpoint test that sets an `Origin` header must use that exact value.
- **`examples/demo-repository/` is a live test fixture.** The line numbers asserted in `tests/test_impact_analyzer.py` (e.g. `email` on line 5 of `client.py`) will break if you edit those files.
- **Frontend has no test runner.** `package.json` has no `test` script — there are no frontend unit tests yet.
