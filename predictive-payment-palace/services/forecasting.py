"""Trailing-period average demand and prep recommendations."""

from __future__ import annotations

import math
from datetime import datetime


def calculate_average_demand(sales: list[int]) -> float:
    if not sales:
        return 0.0
    return sum(sales) / len(sales)


def calculate_recommended_prep(
    average_demand: float,
    buffer_percentage: float = 0.06,
) -> int:
    return math.ceil(average_demand * (1 + buffer_percentage))


def confidence_label(sample_size: int) -> str:
    if sample_size >= 6:
        return "high"
    if sample_size >= 3:
        return "medium"
    return "low"


def forecast_for_menu_item(
    historical_quantities: list[int],
    buffer_percentage: float = 0.06,
) -> dict:
    average = calculate_average_demand(historical_quantities)
    recommended = calculate_recommended_prep(average, buffer_percentage)
    return {
        "forecasted_demand": int(round(average)),
        "recommended_prep": recommended,
        "confidence": confidence_label(len(historical_quantities)),
        "sample_size": len(historical_quantities),
    }


def python_weekday(dt: datetime) -> int:
    """Monday=0 .. Sunday=6 (matches MySQL WEEKDAY)."""
    return dt.weekday()


def meal_period_matches(stored: str | None, target: str) -> bool:
    if not stored:
        return target.lower() in ("dinner", "lunch")
    return stored.lower() == target.lower()
