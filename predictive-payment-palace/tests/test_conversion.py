from services.conversion import calculate_packages_needed


def test_calculate_packages_needed_chicken_example():
    # 90 servings * 2 pcs = 180 needed; 45 on hand => 135 shortage; /40 => 4 cases
    assert (
        calculate_packages_needed(
            forecasted_servings=90,
            ingredient_per_serving=2.0,
            current_inventory=45.0,
            quantity_per_package=40.0,
        )
        == 4
    )


def test_no_packages_when_inventory_covers_demand():
    assert (
        calculate_packages_needed(
            forecasted_servings=10,
            ingredient_per_serving=2.0,
            current_inventory=50.0,
            quantity_per_package=40.0,
        )
        == 0
    )


def test_zero_package_size_returns_zero():
    assert (
        calculate_packages_needed(
            forecasted_servings=100,
            ingredient_per_serving=1.0,
            current_inventory=0,
            quantity_per_package=0,
        )
        == 0
    )


def test_packages_needed_rounds_up():
    # need 41, package 40 => 2 packages
    assert (
        calculate_packages_needed(
            forecasted_servings=41,
            ingredient_per_serving=1.0,
            current_inventory=0,
            quantity_per_package=40.0,
        )
        == 2
    )


def test_packages_needed_exact_fit():
    assert (
        calculate_packages_needed(
            forecasted_servings=40,
            ingredient_per_serving=1.0,
            current_inventory=0,
            quantity_per_package=40.0,
        )
        == 1
    )
