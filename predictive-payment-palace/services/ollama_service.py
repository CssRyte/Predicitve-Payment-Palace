"""Ollama client for narrative summaries only (not forecasting)."""

from __future__ import annotations

import os
from typing import Any

import requests


def _call_ollama(prompt: str, *, timeout: float = 60.0) -> tuple[str | None, bool]:
    url = os.getenv("OLLAMA_URL", "http://localhost:11434").rstrip("/")
    model = os.getenv("OLLAMA_MODEL", "gemma3")
    try:
        response = requests.post(
            f"{url}/api/generate",
            json={"model": model, "prompt": prompt, "stream": False},
            timeout=timeout,
        )
        response.raise_for_status()
        text = (response.json().get("response") or "").strip()
        return (text if text else None), bool(text)
    except (requests.RequestException, ValueError, OSError):
        return None, False


def generate_prep_explanation(
    business_name: str,
    meal_period: str,
    target_date: str,
    recommendations: list[dict[str, Any]],
    *,
    timeout: float = 60.0,
) -> tuple[str, bool]:
    """Returns (explanation_text, ollama_connected)."""
    lines = []
    for rec in recommendations:
        lines.append(
            f"- {rec['name']}: avg demand {rec['forecasted_demand']} {rec['unit']}, "
            f"recommended prep {rec['recommended_prep']} {rec['unit']} "
            f"(confidence: {rec['confidence']}, on-hand prep: {rec.get('current_prep', 0)})"
        )
    facts = "\n".join(lines)

    prompt = (
        f"You are a helpful restaurant operations assistant for {business_name}.\n"
        f"Write 2-3 short paragraphs for the kitchen manager about prep guidance for "
        f"{meal_period} on {target_date}.\n"
        f"Use ONLY these computed numbers (do not invent new quantities):\n{facts}\n"
        f"Explain patterns in plain language and mention the small safety buffer."
    )

    text, connected = _call_ollama(prompt, timeout=timeout)
    if text:
        return text, connected

    fallback = (
        f"{meal_period} prep for {target_date} is based on trailing averages for the same "
        f"weekday from synthetic transaction history.\n\n"
    )
    if recommendations:
        top = recommendations[0]
        fallback += (
            f"For example, {top['name']} is forecast at about {top['forecasted_demand']} "
            f"{top['unit']} with a recommended prep of {top['recommended_prep']} {top['unit']} "
            f"after a 6% buffer.\n\n"
        )
    fallback += (
        "Quantities were calculated in Python before this summary. "
        "Connect Ollama locally for a richer narrative."
    )
    return fallback, False


def generate_reorder_explanation(
    business_name: str,
    target_date: str,
    reorder_rows: list[dict[str, Any]],
    *,
    timeout: float = 60.0,
) -> tuple[str, bool]:
    """Narrative for supplier reorder quantities (computed in Python first)."""
    lines = []
    for row in reorder_rows:
        lines.append(
            f"- {row['ingredient']}: need {row['needed_amount']}, "
            f"order {row['reorder_quantity']} from {row['supplier']} "
            f"({row['estimated_cost']})"
        )
    facts = "\n".join(lines) if lines else "- No packages needed right now."

    prompt = (
        f"You are a purchasing assistant for {business_name}.\n"
        f"Write 2 short paragraphs about the supplier reorder list for {target_date}.\n"
        f"Use ONLY these computed package quantities:\n{facts}\n"
        f"Call out the highest-priority purchase if any packages are needed."
    )

    text, connected = _call_ollama(prompt, timeout=timeout)
    if text:
        return text, connected

    if not reorder_rows:
        return (
            "Inventory covers the projected prep demand. No supplier packages are required "
            "for this forecast window.",
            False,
        )

    top = max(
        reorder_rows,
        key=lambda r: float(str(r["estimated_cost"]).replace("$", "") or 0),
    )
    return (
        f"The order covers projected demand using each supplier's case quantity.\n\n"
        f"{top['ingredient']} is the largest line at {top['reorder_quantity']} "
        f"({top['estimated_cost']}) from {top['supplier']}.\n\n"
        f"Package counts were calculated in Python before this summary.",
        False,
    )
