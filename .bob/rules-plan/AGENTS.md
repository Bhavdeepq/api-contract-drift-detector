




# AGENTS.md

This file provides guidance to agents when working with code in this repository.

## Non-obvious architectural constraints

- **`DriftChange.expected_value` / `actual_value` are lossy.** They are human-readable display strings produced by `_field_value()` / `_parameter_value()` in `detector.py`, not the underlying `Schema` or `Parameter` objects. Any feature that needs full before/after schema detail must thread the original `ApiContract` objects through separately.
- **`ImpactMatch` carries no source text.** The impact analyzer reads files internally but discards the lines after scanning. A remediation layer will need to re-read each matched file using `file_path` + `line_number`.
- **The detector and impact analyzer share no state.** They are two independent passes; the impact analyzer re-opens every source file from disk. There is no shared cache or session object.
- **`ImpactMatch` records are flat, not grouped.** One file affected by three drift changes produces three separate `ImpactMatch` objects. Any UI or agent workflow that wants per-file batching must group them itself by `(file_path, related_drift_change.endpoint, related_drift_change.method)`.
- **`ImpactConfidence` has only one value (`HIGH`).** The enum exists as an extension point; the architecture anticipates a future `MEDIUM`/`LOW` tier for probabilistic matches, but none are implemented.
- **The `agents/` package is a planned integration point for IBM Bob 2.0**, not a utilities library. Nothing in the existing codebase imports from it.
- **Backend stubs (`app/api/`, `app/models/`, `app/schemas/`, `app/services/`) are empty.** All future drift API endpoints will be added there; do not put new logic directly in `app/main.py`.
