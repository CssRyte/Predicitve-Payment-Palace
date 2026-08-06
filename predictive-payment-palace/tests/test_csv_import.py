from datetime import datetime
from io import BytesIO

from services.csv_import import parse_sales_csv


class FakeUpload:
    def __init__(self, text: str, as_bytes: bool = True):
        data = text.encode("utf-8") if as_bytes else text
        self._buf = BytesIO(data) if as_bytes else None
        self._text = text
        self._as_bytes = as_bytes

    def read(self):
        if self._as_bytes:
            return self._buf.read()
        return self._text


def test_parse_sales_csv_valid():
    csv_text = (
        "menu_item,quantity,meal_period,sold_at\n"
        "Fried Chicken Plate,90,Dinner,2026-08-05 18:30:00\n"
    )
    rows, errors = parse_sales_csv(FakeUpload(csv_text))
    assert errors == []
    assert len(rows) == 1
    assert rows[0]["quantity"] == 90
    assert rows[0]["menu_item"] == "Fried Chicken Plate"
    assert rows[0]["meal_period"] == "Dinner"
    assert rows[0]["sold_at"] == datetime(2026, 8, 5, 18, 30, 0)


def test_parse_sales_csv_normalizes_lunch_case():
    csv_text = (
        "menu_item,quantity,meal_period,sold_at\n"
        "Cornbread,20,lunch,2026-08-05\n"
    )
    rows, errors = parse_sales_csv(FakeUpload(csv_text))
    assert errors == []
    assert rows[0]["meal_period"] == "Lunch"
    assert rows[0]["sold_at"] == datetime(2026, 8, 5)


def test_parse_sales_csv_missing_columns():
    rows, errors = parse_sales_csv(FakeUpload("a,b\n1,2\n"))
    assert rows == []
    assert any("Missing required columns" in e for e in errors)


def test_parse_sales_csv_invalid_quantity():
    csv_text = (
        "menu_item,quantity,meal_period,sold_at\n"
        "Fried Chicken Plate,-5,Dinner,2026-08-05 18:30:00\n"
        "Macaroni and Cheese,abc,Dinner,2026-08-05 18:30:00\n"
    )
    rows, errors = parse_sales_csv(FakeUpload(csv_text))
    assert rows == []
    assert len(errors) == 2


def test_parse_sales_csv_bad_date():
    csv_text = (
        "menu_item,quantity,meal_period,sold_at\n"
        "Cornbread,10,Dinner,not-a-date\n"
    )
    rows, errors = parse_sales_csv(FakeUpload(csv_text))
    assert rows == []
    assert any("sold_at" in e for e in errors)


def test_parse_sales_csv_skips_blank_rows():
    csv_text = (
        "menu_item,quantity,meal_period,sold_at\n"
        ",,\n"
        "Cornbread,10,Dinner,2026-08-05 12:00:00\n"
    )
    rows, errors = parse_sales_csv(FakeUpload(csv_text))
    assert errors == []
    assert len(rows) == 1


def test_parse_sales_csv_header_only():
    rows, errors = parse_sales_csv(
        FakeUpload("menu_item,quantity,meal_period,sold_at\n")
    )
    assert rows == []
    assert errors == []
