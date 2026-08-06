from datetime import date

from app import (
    business_initials,
    dashboard_context,
    parse_target_date,
    unit_label,
)


def test_business_initials_two_words():
    assert business_initials("Mama's Soul Food") == "MS"


def test_business_initials_single_word():
    assert business_initials("Palace") == "PA"


def test_business_initials_empty():
    assert business_initials("") == "PP"


def test_unit_label_mapping():
    assert unit_label("plate") == "plates"
    assert unit_label("serving") == "servings"
    assert unit_label("piece") == "pieces"
    assert unit_label("box") == "box"


def test_parse_target_date_valid():
    assert parse_target_date("2026-08-05") == date(2026, 8, 5)


def test_parse_target_date_invalid_falls_back():
    assert parse_target_date("not-a-date") == date(2026, 8, 5)


def test_parse_target_date_none_falls_back():
    assert parse_target_date(None) == date(2026, 8, 5)


def test_dashboard_context_defaults(monkeypatch):
    # dashboard_context reads session; provide an empty session-like object
    monkeypatch.setattr("app.session", {})
    ctx = dashboard_context({"name": "Mama's Soul Food"}, "Aug 4, 2026")
    assert ctx["business_name"] == "Mama's Soul Food"
    assert ctx["business_initials"] == "MS"
    assert ctx["last_updated"] == "Aug 4, 2026"
    assert ctx["logged_in"] is False
