"""Weighted landing priority scoring system.

Scores aircraft 0-100 using configurable component weights and
deterministic tiebreaking for stable ordering across frames.
"""

from __future__ import annotations

from src.models.aircraft import Aircraft, AircraftType

# Default weight distribution across scoring components
_DEFAULT_WEIGHTS: dict[str, float] = {
    "fuel": 0.35,
    "emergency": 0.30,
    "souls": 0.15,
    "wait_time": 0.10,
    "runway": 0.05,
    "distance": 0.05,
}

# Minimum runway requirements (metres) per aircraft type
_MIN_RUNWAY_M: dict[str, float] = {
    "B747": 3000.0,
    "A380": 3000.0,
    "B777": 2500.0,
    "A350": 2500.0,
    "B787": 2500.0,
    "A330": 2500.0,
    "B737": 2000.0,
    "A320": 2000.0,
    "E190": 2000.0,
    "CRJ9": 1800.0,
}


class LandingPriorityCalculator:
    """Weighted multi-factor priority scorer for landing sequencing.

    Each aircraft is evaluated across six independent dimensions.  The raw
    component scores (each 0-100) are combined via a weighted sum then
    normalised to the 0-100 band.
    """

    def __init__(self, weights: dict[str, float] | None = None) -> None:
        """Initialise with optional custom weights.

        Parameters
        ----------
        weights:
            Dict keyed by ``'fuel'``, ``'emergency'``, ``'souls'``,
            ``'wait_time'``, ``'runway'``, ``'distance'``.
            Falls back to sensible defaults when *None*.
        """
        self._weights: dict[str, float] = dict(weights) if weights is not None else dict(_DEFAULT_WEIGHTS)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def calculate_priority(
        self,
        aircraft: Aircraft,
        sim_time: float,
        runway_length_m: float = 3000.0,
    ) -> float:
        """Return a priority score in [0, 100].  Higher = land first."""
        components: dict[str, float] = {
            "fuel": self._fuel_urgency_score(aircraft),
            "emergency": self._emergency_score(aircraft),
            "souls": self._souls_score(aircraft),
            "wait_time": self._wait_time_score(aircraft, sim_time),
            "runway": self._runway_compatibility_score(aircraft, runway_length_m),
            "distance": self._distance_score(aircraft),
        }

        total_weight = sum(self._weights.get(k, 0.0) for k in components)
        if total_weight == 0.0:
            return 0.0

        raw = sum(self._weights.get(k, 0.0) * v for k, v in components.items())
        # Normalise so that if every component were 100 the result is 100
        score = raw / total_weight
        return max(0.0, min(100.0, score))

    def rank_aircraft(
        self,
        aircraft_list: list[Aircraft],
        sim_time: float,
        runway_length_m: float = 3000.0,
    ) -> list[Aircraft]:
        """Score, sort (descending) and return *aircraft_list* in landing order.

        Deterministic tiebreaker via ``hash(aircraft.id)`` so that identical
        scores produce a stable ordering regardless of input order.
        """
        for ac in aircraft_list:
            ac.priority_score = self.calculate_priority(ac, sim_time, runway_length_m)

        return sorted(
            aircraft_list,
            key=lambda ac: (-ac.priority_score, hash(ac.id)),
        )

    # ------------------------------------------------------------------
    # Component scorers (each returns 0-100)
    # ------------------------------------------------------------------

    @staticmethod
    def _emergency_score(aircraft: Aircraft) -> float:
        """Score emergency severity.  Non-emergency → 0."""
        if not aircraft.is_emergency:
            return 0.0

        etype = aircraft.emergency_type.upper() if aircraft.emergency_type else ""

        if etype == "FUEL":
            return 50.0
        if etype == "MEDICAL":
            return 75.0
        if etype in ("ENGINE", "HYDRAULIC", "FIRE"):
            return 100.0
        # Unknown / other emergency type
        return 60.0

    @staticmethod
    def _fuel_urgency_score(aircraft: Aircraft) -> float:
        """Score fuel state — lower fuel = higher urgency.

        A burn-rate modifier nudges the score upward when remaining
        endurance (fuel / burn_rate) is low.
        """
        fuel = aircraft.fuel_remaining_kg

        # Base bracket score
        if fuel < 2_000:
            base = 100.0
        elif fuel < 5_000:
            base = 80.0
        elif fuel < 10_000:
            base = 50.0
        elif fuel < 20_000:
            base = 30.0
        else:
            base = 10.0

        # Burn-rate modifier: remaining endurance in minutes
        burn = aircraft.fuel_burn_rate_kg_s
        if burn > 0.0:
            endurance_min = fuel / burn / 60.0
            if endurance_min < 30:
                base = min(100.0, base + 20.0)
            elif endurance_min < 60:
                base = min(100.0, base + 10.0)

        return base

    @staticmethod
    def _souls_score(aircraft: Aircraft) -> float:
        """More souls on board → higher priority.  Capped at 500+."""
        return min(aircraft.souls_on_board / 500.0 * 100.0, 100.0)

    @staticmethod
    def _wait_time_score(aircraft: Aircraft, sim_time: float) -> float:
        """Linear ramp to 100 over 60 minutes of holding."""
        if aircraft.holding_start_time is None:
            return 0.0
        duration = sim_time - aircraft.holding_start_time
        if duration <= 0.0:
            return 0.0
        return min(duration / 3600.0 * 100.0, 100.0)

    @staticmethod
    def _runway_compatibility_score(aircraft: Aircraft, runway_length_m: float) -> float:
        """Tight runway fit → higher urgency (land before conditions shift).

        The score reflects how constrained the aircraft is by the available
        runway — a perfect fit scores ~50, borderline scores ~80-100.
        """
        required = _MIN_RUNWAY_M.get(aircraft.aircraft_type, 2000.0)

        if runway_length_m >= required:
            # Comfortable margin — low urgency
            return 50.0
        elif runway_length_m >= required - 500:
            # Tight but feasible
            return 80.0
        else:
            # Very tight — highest urgency
            return 100.0

    @staticmethod
    def _distance_score(aircraft: Aircraft) -> float:
        """Lower altitude ≈ closer to landing ≈ higher score.

        Linearly maps 0 ft → 100, 40 000 ft → 0.
        """
        return max(0.0, 100.0 - aircraft.altitude_ft / 400.0)
