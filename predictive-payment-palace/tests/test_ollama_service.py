from unittest.mock import MagicMock, patch

from services.ollama_service import generate_prep_explanation, generate_reorder_explanation


def test_prep_explanation_fallback_when_ollama_down():
    with patch("services.ollama_service.requests.post", side_effect=ConnectionError):
        text, connected = generate_prep_explanation(
            "Mama's Soul Food",
            "Dinner",
            "2026-08-05",
            [
                {
                    "name": "Fried Chicken Plate",
                    "forecasted_demand": 85,
                    "recommended_prep": 91,
                    "unit": "plate",
                    "confidence": "high",
                    "current_prep": 12,
                }
            ],
            timeout=1,
        )
    assert connected is False
    assert "Fried Chicken Plate" in text
    assert "91" in text


def test_prep_explanation_uses_ollama_response():
    mock_response = MagicMock()
    mock_response.raise_for_status.return_value = None
    mock_response.json.return_value = {"response": "Kitchen summary from Ollama."}

    with patch("services.ollama_service.requests.post", return_value=mock_response):
        text, connected = generate_prep_explanation(
            "Mama's Soul Food",
            "Dinner",
            "2026-08-05",
            [
                {
                    "name": "Cornbread",
                    "forecasted_demand": 70,
                    "recommended_prep": 75,
                    "unit": "piece",
                    "confidence": "high",
                }
            ],
        )
    assert connected is True
    assert text == "Kitchen summary from Ollama."


def test_reorder_explanation_fallback_highlights_costliest_line():
    with patch("services.ollama_service.requests.post", side_effect=ConnectionError):
        text, connected = generate_reorder_explanation(
            "Mama's Soul Food",
            "2026-08-05",
            [
                {
                    "ingredient": "Chicken (Raw)",
                    "needed_amount": "180 piece",
                    "reorder_quantity": "4 cases",
                    "supplier": "Georgia Foods",
                    "estimated_cost": "$500.00",
                },
                {
                    "ingredient": "Yams",
                    "needed_amount": "20 lb",
                    "reorder_quantity": "1 case",
                    "supplier": "PFG",
                    "estimated_cost": "$18.00",
                },
            ],
            timeout=1,
        )
    assert connected is False
    assert "Chicken (Raw)" in text
