# Example data

[User guide](index.md)

`example-data/` (raw instrument files plus converted `.h5` projects) and `artifacts/` (generated analysis and HDF5-trial outputs) are not stored in git; both are listed in `.gitignore`. Get the `260813` measurement folder from the project maintainer and place it at `example-data/260813/` with its `Spectrum/`, `spm/`, and `sxm/` subfolders. Several tests read files from `example-data/260813/Spectrum/` and `example-data/260813/spm/`, so they need this folder to run. `scripts/hdf5_trial.py` regenerates `artifacts/hdf5-trial/`.
