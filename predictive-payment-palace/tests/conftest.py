"""Shared pytest fixtures."""

import pytest

from app import app


@pytest.fixture
def app_context():
    with app.app_context():
        yield app
