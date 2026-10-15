# Implementation plan

1. Establish package, specification, and architecture checkpoint.
2. Implement imports, immutable raw/derived data, model fitting, exports, versioned project persistence; test synthetic results and failures.
3. Implement desktop import preview, browser/table, plotting, range selection, background fitting, exports, project lifecycle.
4. Run numerical and persistence tests plus offscreen UI workflow tests; launch desktop if available. Document verified behavior and manual checks.
5. Record a local Git checkpoint and provide PyCharm setup and a short workflow guide.

## Completed first version

All five stages completed. The core workflow includes numeric and draggable fitting ranges, overlays, raw/derived separation, background fits, exports, and portable save/reopen. Validation: 22 passing tests; native macOS window launched/rendered/closed and its screenshot inspected. See VALIDATION.md for limits and reproducible checks. Advanced features listed in SPEC.md remain deferred.
