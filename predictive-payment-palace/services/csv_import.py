"""CSV sales import helpers."""

from __future__ import annotations

import csv
import io
from datetime import datetime
from typing import Any


REQUIRED_COLUMNS = ("menu_item", "quantity", "meal_period", "sold_at")


def parse_sales_csv(file_storage) -> tuple[list[dict[str, Any]], list[str]]:
    """
    Parse an uploaded CSV into row dicts.
    Returns (rows, errors). Rows are ready for insert after menu_item_id is resolved.
    """
    raw = file_storage.read()
    if isinstance(raw, bytes):
        text = raw.decode("utf-8-sig")
    else:
        text = str(raw)

    reader = csv.DictReader(io.StringIO(text))
    if not reader.fieldnames:
        return [], ["CSV has no header row."]

    headers = {h.strip().lower(): h for h in reader.fieldnames if h}
    missing = [c for c in REQUIRED_COLUMNS if c not in headers]
    if missing:
        return [], [
            "Missing required columns: "
            + ", ".join(missing)
            + ". Expected: menu_item, quantity, meal_period, sold_at"
        ]

    rows: list[dict[str, Any]] = []
    errors: list[str] = []
    for idx, row in enumerate(reader, start=2):
        name = (row.get(headers["menu_item"]) or "").strip()
        qty_raw = (row.get(headers["quantity"]) or "").strip()
        meal = (row.get(headers["meal_period"]) or "Dinner").strip() or "Dinner"
        sold_raw = (row.get(headers["sold_at"]) or "").strip()

        if not name and not qty_raw and not sold_raw:
            continue

        if not name:
            errors.append(f"Row {idx}: menu_item is required.")
            continue
        try:
            quantity = int(float(qty_raw))
            if quantity <= 0:
                raise ValueError
        except ValueError:
            errors.append(f"Row {idx}: quantity must be a positive number.")
            continue

        sold_at = None
        for fmt in (
            "%Y-%m-%d %H:%M:%S",
            "%Y-%m-%d %H:%M",
            "%Y-%m-%dT%H:%M:%S",
            "%Y-%m-%d",
            "%m/%d/%Y %H:%M",
            "%m/%d/%Y",
        ):
            try:
                sold_at = datetime.strptime(sold_raw, fmt)
                break
            except ValueError:
                continue
        if sold_at is None:
            errors.append(
                f"Row {idx}: sold_at must look like YYYY-MM-DD or YYYY-MM-DD HH:MM:SS."
            )
            continue

        rows.append(
            {
                "menu_item": name,
                "quantity": quantity,
                "meal_period": meal.title() if meal.lower() in ("lunch", "dinner") else meal,
                "sold_at": sold_at,
            }
        )

    return rows, errors
