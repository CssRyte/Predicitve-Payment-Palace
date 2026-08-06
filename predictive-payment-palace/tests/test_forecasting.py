from datetime import datetime

from services.forecasting import (
    calculate_average_demand,
    calculate_recommended_prep,
    confidence_label,
    forecast_for_menu_item,
    meal_period_matches,
    python_weekday,
)


def test_average_demand_empty():
    assert calculate_average_demand([]) == 0.0


def test_average_demand_wednesday_chicken():
    assert calculate_average_demand([82, 84, 86, 88]) == 85


def test_average_demand_single_value():
    assert calculate_average_demand([40]) == 40


def test_recommended_prep_with_buffer():
    assert calculate_recommended_prep(85, 0.06) == 91


def test_recommended_prep_exact_ceiling():
    # 10 * 1.06 = 10.6 -> ceil 11
    assert calculate_recommended_prep(10, 0.06) == 11


def test_recommended_prep_zero_demand():
    assert calculate_recommended_prep(0) == 0


def test_confidence_label_tiers():
    assert confidence_label(0) == "low"
    assert confidence_label(2) == "low"
    assert confidence_label(3) == "medium"
    assert confidence_label(5) == "medium"
    assert confidence_label(6) == "high"
    assert confidence_label(8) == "high"


def test_forecast_for_menu_item_medium_confidence():
    result = forecast_for_menu_item([82, 84, 86, 88])
    assert result["forecasted_demand"] == 85
    assert result["recommended_prep"] == 91
    assert result["confidence"] == "medium"
    assert result["sample_size"] == 4


def test_forecast_for_menu_item_high_confidence():
    sales = [82, 84, 86, 88, 83, 85, 87, 89]
    result = forecast_for_menu_item(sales)
    assert result["sample_size"] == 8
    assert result["confidence"] == "high"
    assert result["forecasted_demand"] == int(round(sum(sales) / len(sales)))


def test_forecast_for_empty_history():
    result = forecast_for_menu_item([])
    assert result["forecasted_demand"] == 0
    assert result["recommended_prep"] == 0
    assert result["confidence"] == "low"
    assert result["sample_size"] == 0


def test_python_weekday_matches_mysql_convention():
    # 2026-08-05 is a Wednesday -> weekday 2
    assert python_weekday(datetime(2026, 8, 5, 18, 30)) == 2


def test_meal_period_matches():
    assert meal_period_matches("Dinner", "dinner") is True
    assert meal_period_matches("Lunch", "Dinner") is False
    assert meal_period_matches(None, "Dinner") is True
    assert meal_period_matches("", "Lunch") is True
