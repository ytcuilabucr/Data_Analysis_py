# Region statistics

[User guide](index.md) · [Validation and limitations](../limitations.md)

Enable **View → Show statistics**, highlight a dataset, and check **Drag on plot to select**. Choose **X range** to select a horizontal interval, or **Rectangle** to restrict both X and Y. Drag on the main plot; handles let you adjust the region. Enabling selection turns off toolbar pan/zoom and fitting-range selection. You can also enter bounds and click **Calculate statistics**. Bounds are inclusive and may be equal to select an exact coordinate.

Results summarize the active dataset's selected **Y channel**: count, minimum, maximum, mean, median, standard deviation, variance, standard error of the mean, sum, RMS, and 25th/75th percentiles. Duplicate X values are separate observations; values are neither interpolated nor weighted. Choose **Sample (N − 1)** or **Population (N)** for standard deviation and variance. Standard error is the chosen standard deviation divided by √N; interpreting it as uncertainty assumes independent observations. Percentiles use linear interpolation.

Missing X values are excluded and counted across the whole dataset because their region cannot be determined. Missing Y values are counted within the X interval before optional Y filtering. Empty regions report count zero and N/A statistics; sample standard deviation, variance, and standard error need at least two observations. N/A also denotes numerical overflow.

Statistics use stored values, including nonpositive values hidden by a log scale if they fall inside the specified bounds. They do not summarize fit curves or all overlaid datasets. Check the active dataset's visibility box to see its curve while selecting. Results refresh after edits; changing dataset or X/Y channels clears the selection. The region survives unrelated redraws without changing zoom.

Statistics are a temporary inspection tool: regions/results are not saved in projects and do not mark the project modified. You can select and copy text from the results box. Source data, provenance, and saved fits are unaffected.
