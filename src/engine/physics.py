"""Core physics engine for aircraft movement simulation.

All operations are vectorized via NumPy — no Python loops over aircraft.
Positions in km, altitudes in feet, speeds in knots, vertical speeds in fpm.
Simulation tick rate: 20Hz (dt=0.05s).
"""

from __future__ import annotations

import numpy as np
from numpy.typing import NDArray

# ---------------------------------------------------------------------------
# Unit conversion constants
# ---------------------------------------------------------------------------
KT_TO_KM_S: float = 0.000514444  # knots -> km/s
FPM_TO_KM_S: float = 0.00000508  # feet/min -> km/s
NM_TO_KM: float = 1.852  # nautical miles -> km
FT_TO_KM: float = 0.0003048  # feet -> km
DEG_TO_RAD: float = np.pi / 180.0
RAD_TO_DEG: float = 180.0 / np.pi

# ---------------------------------------------------------------------------
# Physical / operational constants
# ---------------------------------------------------------------------------
GRAVITY_MS2: float = 9.81  # m/s^2
MAX_BANK_ANGLE_DEG: float = 25.0  # standard rate turn limit
MIN_SPEED_KT: float = 140.0  # minimum safe airspeed
MAX_SPEED_KT: float = 350.0  # max in terminal area


class PhysicsEngine:
    """Vectorized physics engine for batch aircraft state updates.

    Every public method operates on NumPy arrays of shape ``(N, ...)`` where
    *N* is the number of aircraft.  No Python-level iteration over individual
    aircraft is performed.
    """

    def __init__(self, dt: float = 0.05) -> None:
        """Initialise the engine.

        Parameters
        ----------
        dt : float
            Tick interval in seconds (default 50 ms = 20 Hz).
        """
        self.dt: float = dt

    # ------------------------------------------------------------------
    # 1. Position integration
    # ------------------------------------------------------------------
    def integrate_positions(
        self,
        positions: NDArray[np.float64],
        velocities: NDArray[np.float64],
    ) -> NDArray[np.float64]:
        """Euler integration: ``new_pos = pos + vel * dt``.

        Parameters
        ----------
        positions : ndarray, shape (N, 3)
            Current positions in km.
        velocities : ndarray, shape (N, 3)
            Velocity vectors in km/s.

        Returns
        -------
        ndarray, shape (N, 3)
            Updated positions.
        """
        return positions + velocities * self.dt

    # ------------------------------------------------------------------
    # 2. Velocity vector from heading / speed / vspeed
    # ------------------------------------------------------------------
    def compute_velocity_vectors(
        self,
        headings: NDArray[np.float64],
        speeds_kt: NDArray[np.float64],
        vertical_speeds_fpm: NDArray[np.float64],
    ) -> NDArray[np.float64]:
        """Convert heading + airspeed + vertical speed to a 3-D velocity vector.

        Parameters
        ----------
        headings : ndarray, shape (N,)
            Headings in degrees (0 = north, 90 = east).
        speeds_kt : ndarray, shape (N,)
            Airspeeds in knots.
        vertical_speeds_fpm : ndarray, shape (N,)
            Vertical speeds in feet/min.

        Returns
        -------
        ndarray, shape (N, 3)
            ``[vx, vy, vz]`` in km/s.
        """
        heading_rad = headings * DEG_TO_RAD
        speed_km_s = speeds_kt * KT_TO_KM_S

        vx = speed_km_s * np.sin(heading_rad)
        vy = speed_km_s * np.cos(heading_rad)
        vz = vertical_speeds_fpm * FPM_TO_KM_S

        return np.column_stack((vx, vy, vz))

    # ------------------------------------------------------------------
    # 3. Heading / bank-angle update (shortest-turn logic)
    # ------------------------------------------------------------------
    def update_headings(
        self,
        headings: NDArray[np.float64],
        target_headings: NDArray[np.float64],
        bank_angles: NDArray[np.float64],
    ) -> tuple[NDArray[np.float64], NDArray[np.float64]]:
        """Steer each aircraft toward its target heading via bank-limited turn.

        The turn rate is capped at 3 deg/s (standard rate).  The shortest-
        turn direction is chosen automatically.  When within 1 deg of target
        the bank angle decays toward 0.

        Parameters
        ----------
        headings : ndarray, shape (N,)
            Current headings in degrees [0, 360).
        target_headings : ndarray, shape (N,)
            Desired headings in degrees.
        bank_angles : ndarray, shape (N,)
            Current bank angles in degrees.

        Returns
        -------
        tuple[ndarray, ndarray]
            ``(new_headings, new_bank_angles)`` each shape (N,).
        """
        # Angle difference wrapped to (-180, 180]
        diff = (target_headings - headings + 180.0) % 360.0 - 180.0

        abs_diff = np.abs(diff)
        direction = np.sign(diff)  # +1 CW, -1 CCW, 0 on target

        # Standard-rate turn capped at 3 deg/s
        turn_rate = np.full_like(headings, 3.0)
        max_step = turn_rate * self.dt  # degrees this tick

        # Don't overshoot: step = min(rate * dt, remaining)
        step = np.minimum(max_step, abs_diff)

        new_headings = headings + direction * step
        # Wrap to [0, 360)
        new_headings = new_headings % 360.0

        # Bank angle: set to MAX_BANK if actively turning, decay toward 0 if ~on target
        turning = abs_diff > 1.0
        new_bank = np.where(
            turning,
            MAX_BANK_ANGLE_DEG,
            bank_angles * 0.8,  # exponential decay when nearly aligned
        )

        return new_headings, new_bank

    # ------------------------------------------------------------------
    # 4. Altitude / vertical-speed update
    # ------------------------------------------------------------------
    def update_altitudes(
        self,
        altitudes_ft: NDArray[np.float64],
        target_altitudes_ft: NDArray[np.float64],
        vertical_speeds_fpm: NDArray[np.float64],
        max_climb_fpm: NDArray[np.float64],
        max_descent_fpm: NDArray[np.float64],
    ) -> tuple[NDArray[np.float64], NDArray[np.float64]]:
        """Move altitudes toward their targets, respecting climb/descent limits.

        Aircraft within 50 ft of their target snap to the target and level
        off (vertical speed set to 0).

        Parameters
        ----------
        altitudes_ft : ndarray, shape (N,)
        target_altitudes_ft : ndarray, shape (N,)
        vertical_speeds_fpm : ndarray, shape (N,)
            Desired / commanded vertical speeds (positive = climb).
        max_climb_fpm : ndarray, shape (N,)
            Per-aircraft maximum climb rate (positive).
        max_descent_fpm : ndarray, shape (N,)
            Per-aircraft maximum descent rate (positive value; will be negated internally).

        Returns
        -------
        tuple[ndarray, ndarray]
            ``(new_altitudes_ft, new_vertical_speeds_fpm)``.
        """
        alt_diff = target_altitudes_ft - altitudes_ft

        # Determine effective vertical speed
        # Climbing: positive vspeed clamped to max_climb
        # Descending: negative vspeed clamped to -max_descent
        need_climb = alt_diff > 50.0
        need_descend = alt_diff < -50.0
        level = ~need_climb & ~need_descend  # within 50 ft

        # Compute constrained vertical speeds
        # When vertical_speeds_fpm is 0, use max climb/descent as the commanded rate
        effective_vs = np.where(
            vertical_speeds_fpm == 0.0,
            max_climb_fpm,  # use max rate when no explicit vspeed commanded
            np.abs(vertical_speeds_fpm),
        )
        climb_vs = np.minimum(effective_vs, max_climb_fpm)
        descend_vs = -np.minimum(effective_vs, max_descent_fpm)

        new_vs = np.where(need_climb, climb_vs, np.where(need_descend, descend_vs, 0.0))

        # Integrate altitude (fpm -> ft/s -> ft per tick)
        delta_ft = new_vs * (self.dt / 60.0)  # fpm * (s / 60) = feet

        new_alt = altitudes_ft + delta_ft

        # Snap to target when within tolerance
        new_alt = np.where(level, target_altitudes_ft, new_alt)
        new_vs = np.where(level, 0.0, new_vs)

        return new_alt, new_vs

    # ------------------------------------------------------------------
    # 5. Speed constraints
    # ------------------------------------------------------------------
    def apply_speed_constraints(
        self,
        speeds_kt: NDArray[np.float64],
    ) -> NDArray[np.float64]:
        """Clamp airspeeds to ``[MIN_SPEED_KT, MAX_SPEED_KT]``.

        Parameters
        ----------
        speeds_kt : ndarray, shape (N,)

        Returns
        -------
        ndarray, shape (N,)
        """
        return np.clip(speeds_kt, MIN_SPEED_KT, MAX_SPEED_KT)

    # ------------------------------------------------------------------
    # 6. Fuel burn
    # ------------------------------------------------------------------
    def update_fuel(
        self,
        fuel_kg: NDArray[np.float64],
        burn_rates_kg_s: NDArray[np.float64],
        phase_multipliers: NDArray[np.float64],
    ) -> NDArray[np.float64]:
        """Burn fuel for one tick.

        ``new_fuel = fuel - burn_rate * multiplier * dt``, clamped >= 0.

        Typical *phase_multipliers*::

            CLIMB=1.5  CRUISE=1.0  DESCENT=0.6
            HOLDING=1.2  APPROACH=0.4  LANDING=0.1

        Parameters
        ----------
        fuel_kg : ndarray, shape (N,)
        burn_rates_kg_s : ndarray, shape (N,)
            Base burn rate in kg/s.
        phase_multipliers : ndarray, shape (N,)
            Multiplier for current flight phase.

        Returns
        -------
        ndarray, shape (N,)
        """
        consumed = burn_rates_kg_s * phase_multipliers * self.dt
        return np.maximum(fuel_kg - consumed, 0.0)

    # ------------------------------------------------------------------
    # 7. Speed update (accel / decel toward target)
    # ------------------------------------------------------------------
    def update_speeds(
        self,
        speeds_kt: NDArray[np.float64],
        target_speeds_kt: NDArray[np.float64],
        accel_kt_per_s: float = 2.0,
    ) -> NDArray[np.float64]:
        """Accelerate or decelerate toward a target speed.

        ``speed += sign(target - speed) * min(accel * dt, |target - speed|)``

        The result is then clamped via :meth:`apply_speed_constraints`.

        Parameters
        ----------
        speeds_kt : ndarray, shape (N,)
        target_speeds_kt : ndarray, shape (N,)
        accel_kt_per_s : float
            Acceleration / deceleration magnitude in kt/s.

        Returns
        -------
        ndarray, shape (N,)
        """
        diff = target_speeds_kt - speeds_kt
        max_step = accel_kt_per_s * self.dt
        step = np.sign(diff) * np.minimum(np.abs(diff), max_step)
        new_speeds = speeds_kt + step
        return self.apply_speed_constraints(new_speeds)
