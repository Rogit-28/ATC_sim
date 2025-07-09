"""Tests for the vectorized physics engine."""

import numpy as np
import pytest

from src.engine.physics import (
    FT_TO_KM,
    KT_TO_KM_S,
    NM_TO_KM,
    PhysicsEngine,
)


@pytest.fixture
def engine():
    return PhysicsEngine(dt=0.05)


class TestIntegratePositions:
    def test_stationary(self, engine):
        positions = np.array([[0.0, 0.0, 0.0]], dtype=np.float64)
        velocities = np.array([[0.0, 0.0, 0.0]], dtype=np.float64)
        result = engine.integrate_positions(positions, velocities)
        np.testing.assert_array_almost_equal(result, positions)

    def test_constant_velocity(self, engine):
        positions = np.array([[0.0, 0.0, 0.0]], dtype=np.float64)
        velocities = np.array([[1.0, 2.0, 0.5]], dtype=np.float64)
        result = engine.integrate_positions(positions, velocities)
        expected = positions + velocities * 0.05
        np.testing.assert_array_almost_equal(result, expected)

    def test_multiple_aircraft(self, engine):
        n = 100
        positions = np.random.randn(n, 3)
        velocities = np.random.randn(n, 3)
        result = engine.integrate_positions(positions, velocities)
        expected = positions + velocities * 0.05
        np.testing.assert_array_almost_equal(result, expected)


class TestComputeVelocityVectors:
    def test_north_heading(self, engine):
        headings = np.array([0.0])  # North
        speeds = np.array([100.0])  # 100 knots
        vspeeds = np.array([0.0])
        result = engine.compute_velocity_vectors(headings, speeds, vspeeds)
        # North = positive y in our coordinate system
        speed_km_s = 100.0 * KT_TO_KM_S
        assert result.shape == (1, 3)
        assert result[0, 2] == pytest.approx(0.0, abs=1e-6)  # No vertical

    def test_zero_speed(self, engine):
        headings = np.array([90.0])
        speeds = np.array([0.0])
        vspeeds = np.array([0.0])
        result = engine.compute_velocity_vectors(headings, speeds, vspeeds)
        np.testing.assert_array_almost_equal(result, np.zeros((1, 3)))


class TestUpdateHeadings:
    def test_no_change_needed(self, engine):
        headings = np.array([180.0])
        targets = np.array([180.0])
        bank = np.array([0.0])
        new_h, new_b = engine.update_headings(headings, targets, bank)
        assert new_h[0] == pytest.approx(180.0, abs=0.5)
        assert new_b[0] == pytest.approx(0.0, abs=1.0)

    def test_turn_right(self, engine):
        headings = np.array([10.0])
        targets = np.array([30.0])
        bank = np.array([0.0])
        new_h, _ = engine.update_headings(headings, targets, bank)
        assert new_h[0] > 10.0  # Should have turned right

    def test_wrap_around_360(self, engine):
        headings = np.array([350.0])
        targets = np.array([10.0])
        bank = np.array([0.0])
        new_h, _ = engine.update_headings(headings, targets, bank)
        # Should turn right through 360 (shortest path)
        assert new_h[0] > 350.0 or new_h[0] < 20.0


class TestUpdateAltitudes:
    def test_climb(self, engine):
        alts = np.array([10000.0])
        targets = np.array([20000.0])
        vspeeds = np.array([0.0])
        max_climb = np.array([3000.0])
        max_desc = np.array([4000.0])
        new_a, new_vs = engine.update_altitudes(alts, targets, vspeeds, max_climb, max_desc)
        assert new_a[0] >= 10000.0  # Should be climbing
        assert new_vs[0] > 0  # Positive vertical speed

    def test_descend(self, engine):
        alts = np.array([20000.0])
        targets = np.array([10000.0])
        vspeeds = np.array([0.0])
        max_climb = np.array([3000.0])
        max_desc = np.array([4000.0])
        new_a, new_vs = engine.update_altitudes(alts, targets, vspeeds, max_climb, max_desc)
        assert new_a[0] <= 20000.0
        assert new_vs[0] < 0  # Negative = descending

    def test_level_off(self, engine):
        alts = np.array([15000.0])
        targets = np.array([15000.0])
        vspeeds = np.array([100.0])
        max_climb = np.array([3000.0])
        max_desc = np.array([4000.0])
        new_a, new_vs = engine.update_altitudes(alts, targets, vspeeds, max_climb, max_desc)
        # Should be leveling off
        assert abs(new_vs[0]) < abs(vspeeds[0]) + 50


class TestUpdateFuel:
    def test_burns_fuel(self, engine):
        fuel = np.array([50000.0])
        burn_rate = np.array([0.85])
        phase_mult = np.array([1.0])
        new_fuel = engine.update_fuel(fuel, burn_rate, phase_mult)
        expected = 50000.0 - 0.85 * 1.0 * 0.05
        assert new_fuel[0] == pytest.approx(expected, abs=0.01)

    def test_no_negative_fuel(self, engine):
        fuel = np.array([0.01])
        burn_rate = np.array([10.0])
        phase_mult = np.array([1.0])
        new_fuel = engine.update_fuel(fuel, burn_rate, phase_mult)
        assert new_fuel[0] >= 0.0

    def test_phase_multiplier(self, engine):
        fuel = np.array([50000.0])
        burn_rate = np.array([1.0])
        phase_mult_cruise = np.array([1.0])
        phase_mult_holding = np.array([1.2])
        fuel_cruise = engine.update_fuel(fuel, burn_rate, phase_mult_cruise)
        fuel_holding = engine.update_fuel(fuel, burn_rate, phase_mult_holding)
        # Holding should burn more
        assert fuel_holding[0] < fuel_cruise[0]


class TestUpdateSpeeds:
    def test_accelerate(self, engine):
        speeds = np.array([200.0])
        targets = np.array([300.0])
        new_speeds = engine.update_speeds(speeds, targets)
        assert new_speeds[0] > 200.0

    def test_decelerate(self, engine):
        speeds = np.array([300.0])
        targets = np.array([200.0])
        new_speeds = engine.update_speeds(speeds, targets)
        assert new_speeds[0] < 300.0
