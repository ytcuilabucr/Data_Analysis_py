# Dataset browser

Click column headers to sort ascending or descending. Acquisition date uses the earliest valid parsed instrument datetime; missing dates display Unknown. Numeric timestamp streams with an unspecified epoch are not interpreted. Filesystem creation and modification times are never substituted. Dates retain the instrument’s unspecified timezone. Channels counts scan signal channels, or stored columns for tabular datasets.

Select rows, then use Organize → Favorite selected / Unfavorite selected, Edit tags, or Edit comments. Tags are comma separated; editing multiple selected rows replaces their tags or comments. These annotations can be changed on raw data without modifying observations, acquisition metadata, or revisions. Editable copies inherit independent annotations. Annotations persist in JSON and HDF5 projects, with empty defaults for older projects. Edit → Undo / Redo restores annotation changes during the session.

Search, group, favorites, tag, instrument metadata, and acquisition date filters combine with AND. Date bounds are inclusive and accept YYYY-MM-DD; either end may be blank. Unknown acquisition dates do not match an active date range. Invalid bounds are highlighted and match no rows. Filters and sorting do not alter grouping, dataset order in the project, or plot visibility. Hidden rows lose selection. Clearing filters does not reselect them.

Highlighted rows control inspection and organization; the first-column checkboxes control plotted datasets. Opening a project resets filters and restores its active dataset by identity, even when the browser is sorted.
