#!/usr/bin/env python3
"""
Tune int32_temp_current_target (TS_MODE)
==========================================

2D visualization replicating the firmware's TS_MODE formula:

    int32_temp_current_target = (TS_COEF * assist_level *
                                 ((torque_cumulated * PAS_IMP_PER_TURN_RECIP_MULTIPLIER) >> 8)
                                 / uint32_PAS) >> 8

Firmware factors (Inc/config.h):
    TS_COEF                = 2400
    PAS_IMP_PER_TURN       = 32
    PAS_IMP_PER_TURN_RECIP_MULTIPLIER = (1<<8)/32 = 8
    SPEEDLIMIT             = 25 km/h

Speed reduction (INDIVIDUAL_MODES / assist_profile):
    Speed 0 km/h -> speedfactor = 255 (100%)
    Speed 10km/h -> speedfactor = 255 (100%)
    Speed 20km/h -> speedfactor = 200 (~78%)
    Speed 30km/h -> speedfactor = 100 (~39%)
    Speed 45km/h -> speedfactor = 60 (~23%)
    Speed 48km/h -> speedfactor = 30 (~12%)

The Python model:
    torque  ∝ force on pedals
    cadence ∝ 1 / PAS  (inverse relationship)
    uint32_PAS is approximated as PAS_TIMEOUT / (cadence_rpm / 60 * 2)
    (PAS_TIMEOUT=1000 counts ~2 seconds of no-motion timeout)

TUNING KNOBS (adjust to match real-world feel):
    - TS_COEF
    - assist_level (0..255)
    - torque_per_cadence_ratio
"""

import numpy as np
import matplotlib
matplotlib.use('Qt5Agg')
import matplotlib.pyplot as plt

# ── Firmware constants ───────────────────────────────────────────────────
TS_COEF = 2400
PAS_IMP_PER_TURN = 32
PAS_IMP_PER_TURN_RECIP_MULTIPLIER = (1 << 8) // PAS_IMP_PER_TURN  # = 8
SPEEDLIMIT = 25  # km/h

# ── Tuning parameters ────────────────────────────────────────────────────
assist_level = 100        # 0..255 (MID = ~5th bar on King-Meter 0..9 scale)
torque_per_cadence_ratio = 0.8   # how much torque Nm per cadence rpm (sensor calibration knob)
PAS_TIMEOUT = 1000         # timeout threshold in raw PAS counter ticks

# ── Assist profile speedfactor (matches INC/config.h) ────────────────────
# Speed breakpoints (km/h) and speedfactor values (0..255)
_SPEED_BREAKPOINTS = np.array([0., 10., 20., 30., 45., 48.])
_SPEED_FACTORS     = np.array([255., 255., 200., 100., 60., 30.])


def _speedfactor(speed_kmh: float) -> float:
    """Return speedfactor 0..255 by linear interpolation over assist_profile."""
    return float(np.interp(speed_kmh, _SPEED_BREAKPOINTS, _SPEED_FACTORS))


def _pas_from_cadence(cadence_rpm: float) -> float:
    """
    Approximate the raw PAS counter from cadence.

    In firmware, uint32_PAS is the elapsed timer-tick count since the last
    hall-sensor pass.  The relationship is roughly:

        uint32_PAS ≈ PAS_TIMEOUT / (cadence_rpm / 60 * 2)

    because 2 hall passes happen per full pedal revolution and PAS_TIMEOUT
    represents the 2-second no-pedal threshold.
    """
    cadence_rps = cadence_rpm / 60.0
    if cadence_rps <= 0:
        return PAS_TIMEOUT
    return PAS_TIMEOUT / (cadence_rps * 2)


def int32_temp_current_target_raw(speed_kmh: float, cadence_rpm: float) -> int:
    """
    Replicate the firmware TS_MODE formula exactly (Q8.8 fixed-point math).

    Returns the raw int32_t value (same scale as PH_CURRENT_MAX=1500).
    """
    pas = _pas_from_cadence(cadence_rpm)

    torque_cumulated = int(np.round(torque_per_cadence_ratio * cadence_rpm))

    nom = (TS_COEF
           * assist_level
           * ((torque_cumulated * PAS_IMP_PER_TURN_RECIP_MULTIPLIER) >> 8))
    result = (nom // max(int(pas), 1)) >> 8
    return max(result, 0)


def int32_temp_current_target(speed_kmh: float, cadence_rpm: float) -> float:
    """
    Full chain: TS_MODE current target multiplied by speedfactor / 256
    (INDIVIDUAL_MODES scaling) and clipped to PH_CURRENT_MAX.
    """
    raw = int32_temp_current_target_raw(speed_kmh, cadence_rpm)
    sf = _speedfactor(speed_kmh)
    current = int(raw * sf / 256.0)
    return float(current)


def main():
    speed = np.linspace(0, 48, 200)   # km/h
    cadencies = [0, 30, 60, 90, 120]  # rpm

    fig, ax = plt.subplots(figsize=(10, 6))

    for rpm in cadencies:
        vals = np.array([int32_temp_current_target(s, rpm) for s in speed])
        ax.plot(speed, vals, label=f'{rpm} rpm')

    ax.set_xlabel('Speed (km/h)')
    ax.set_ylabel('int32_temp_current_target (raw firmware units)')
    ax.set_title(
        f'int32_temp_current_target vs Speed\n'
        f'TS_COEF={TS_COEF}, assist_level={assist_level}, torque_per_cadence={torque_per_cadence_ratio}'
    )
    ax.legend()
    ax.grid(True)
    plt.tight_layout()
    plt.show()


if __name__ == '__main__':
    main()
