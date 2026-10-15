# Validation — 2026-10-14

Environment: macOS ARM64, Python 3.13.16. Exact installed packages are recorded in requirements-tested.txt.

Command: `.venv/bin/python -m pytest -q`

Result: **22 passed**. Eight upstream Matplotlib/Qt deprecation warnings concern `AA_UseHighDpiPixmaps`; no test failures.

Covered:
- Linear recovery with seeded noise, covariance comparison against NumPy polyfit, and residual identity.
- Positive/negative Gaussian peak recovery and noisy Gaussian standard errors.
- Inclusive fit range, explicit missing-row exclusion, invalid bounds/insufficient data/constant Gaussian failure.
- CSV/TSV, headerless input, selected numeric columns, preserved source text, empty/header-only/malformed/nonnumeric/infinite imports.
- Immutable raw arrays, independent derived edits, edit history, and fit invalidation.
- Project save/reopen with missing values, provenance, fit outputs, plot settings; unknown version and malformed axis/parameter/row/column rejection; preservation of previous file on serialization failure.
- Data CSV reimport and fit CSV output.
- Offscreen Qt integration: import preview, editable copy, cell edit, threaded fit, overlay/residual rendering, PNG/SVG generation, save and GUI project reopening.

Native check: launched the macOS Qt window with the sample Gaussian dataset and fitted residuals, captured the window, inspected the layout, and closed it through the event loop. No native startup error. This was an automated launch/render check, not a complete manual click-through.

Still manual: native file dialogs, mouse range handles, toolbar pan/zoom, platform-specific keyboard behavior, your actual input formats and scales, Igor Pro comparison, Windows/Linux testing, large-file performance. Numerical fit convergence does not validate the scientific model.
