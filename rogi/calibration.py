"""Bundled detector calibration curves (no Qt).

Curves are typical datasheet values, not calibrations of an individual detector.
Responsivity is linearly interpolated between tabulated points and is missing
(NaN) outside the tabulated wavelength range; it is never extrapolated.
"""
from copy import deepcopy
import numpy as np

DETECTORS = {
    'newport_2107': dict(
        label='Newport 2107 (Si)',
        source=('Digitized from the Newport 2107/2117 datasheet responsivity plot (2026-10-22); '
                'about ±0.005 A/W digitization uncertainty; typical unit.'),
        wavelength_nm=[300., 350., 400., 450., 500., 550., 600., 650., 700., 750., 800., 850.,
                       900., 950., 1000., 1050.],
        responsivity_a_per_w=[0.100, 0.180, 0.240, 0.279, 0.314, 0.350, 0.379, 0.404, 0.429, 0.460,
                              0.478, 0.508, 0.524, 0.508, 0.409, 0.119],
        # Front-panel gain settings map to transimpedance by one factor: 626 V/A at setting 1
        # up to 18.8e6 V/A at 3e4 (2107/2117 manual Rev A, p. 9 and specifications).
        gain_settings=[1., 3., 10., 30., 100., 300., 1e3, 3e3, 1e4, 3e4],
        transimpedance_v_per_a_per_setting=626.),
}


def detector_curve(detector):
    if detector not in DETECTORS:
        raise ValueError(f'Unknown detector: {detector}.')
    return deepcopy(DETECTORS[detector])


def responsivity(detector, wavelength_nm):
    """Responsivity in A/W at each wavelength (nm); NaN outside the curve or for missing input."""
    curve = DETECTORS.get(detector)
    if curve is None:
        raise ValueError(f'Unknown detector: {detector}.')
    grid = np.asarray(curve['wavelength_nm'])
    x = np.asarray(wavelength_nm, dtype=float)
    result = np.interp(x, grid, curve['responsivity_a_per_w'])
    result = np.where((x >= grid[0]) & (x <= grid[-1]), result, np.nan)
    return result


def photodiode_power_mw(voltage_v, wavelength_nm, detector, gain_setting=1.0, dark_v=0.0):
    """Optical power in mW: 1000 * (V - V_dark) / (626 V/A * setting * R(lambda)) for the 2107.

    The voltage must be measured into a high-impedance input; a 50-ohm load reads lower.
    """
    gain_v_per_a = DETECTORS[detector]['transimpedance_v_per_a_per_setting'] * gain_setting
    return 1e3 * (np.asarray(voltage_v, dtype=float) - dark_v) / (gain_v_per_a * responsivity(detector, wavelength_nm))
