# Models and uncertainty assumptions

[User guide](index.md) · [Validation and limitations](../limitations.md)

**Linear:** `y = slope*x + intercept`. Slope has Y/X units; intercept has Y units. Solved by ordinary least squares. More than two distinct X values are required so residual variance can be estimated.

**Gaussian:** `y = baseline + amplitude * exp(-0.5*((x-center)/sigma)^2)`. Baseline is the constant background, amplitude is peak height relative to baseline (negative peaks allowed), center is in X units, and sigma is positive width in X units. FWHM = `2*sqrt(2*ln(2))*sigma`. More than four distinct X values are required. Initial guesses use median background, strongest deviation, and range/6 width. Select a single peak with both tails; local optimization can fail or converge to an unsuitable peak. Inspect residuals and physical plausibility; convergence alone is not validation.

Both models minimize unweighted squared Y residuals. X is treated as exact. Errors are assumed independent with equal unknown variance; residual variance is estimated as SSE/(N-p). Reported ± values are approximate one-standard-deviation parameter standard errors from covariance, not confidence intervals or measurement uncertainties. Gaussian covariance is a local linear approximation. Unavailable/nonfinite or severely ill-conditioned covariance is reported explicitly. Exact synthetic fits can have zero estimated errors; that does not establish zero experimental uncertainty. No weighting, X-error treatment, robust loss, or parameter constraints beyond positive Gaussian sigma are provided yet.
