
# AGENTS.md

This file provides guidance to agents when working with code in this repository.

## Non-obvious documentation context

- **`drift_engine/README.md` says the package is a "placeholder" — it is not.** The full parser, detector, and impact analyzer are implemented and fully tested. Ignore that README.
- **`agents/README.md` describes a 6-step Bob workflow that is not yet implemented.** It is aspirational documentation only; no code in `agents/` exists beyond `__init__.py`.
- **The demo consumer repo at `examples/demo-repository/` exists solely as a test fixture**, not as an example of how to integrate the library. Its `node_modules/`, `dist/`, and `venv/` subdirectories are intentionally committed and intentionally ignored by the scanner.
- **`backend/app/models/`, `backend/app/schemas/`, `backend/app/services/`, and `backend/app/api/` are all empty stubs** (contain only `__init__.py`). The entire backend is currently just `backend/app/main.py`.
- **`tests/README.md` says the directory is "reserved for future tests" — it already has three full test files.** Ignore that README.
- **There is no linter or formatter config anywhere in the repo.** Style is inferred from the source code only.
