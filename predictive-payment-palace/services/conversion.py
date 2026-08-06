"""Convert forecasted servings into supplier package quantities."""

from __future__ import annotations

import math


def calculate_packages_needed(
    forecasted_servings: int,
    ingredient_per_serving: float,
    current_inventory: float,
    quantity_per_package: float,
) -> int:
    if quantity_per_package <= 0:
        return 0
    required_amount = forecasted_servings * ingredient_per_serving
    shortage = max(required_amount - float(current_inventory), 0)
    return math.ceil(shortage / quantity_per_package)
