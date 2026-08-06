import mysql.connector
import pytest

from app import DEMO_EMAIL, DEMO_PASSWORD, app, get_db_connection


@pytest.fixture
def client():
    app.config["TESTING"] = True
    with app.test_client() as test_client:
        yield test_client


def mysql_available() -> bool:
    try:
        conn = get_db_connection()
        conn.close()
        return True
    except mysql.connector.Error:
        return False


requires_mysql = pytest.mark.skipif(
    not mysql_available(),
    reason="MySQL is not available for integration-style route tests",
)


@requires_mysql
def test_login_page_loads(client):
    response = client.get("/")
    assert response.status_code == 200
    assert b"Sign In" in response.data


@requires_mysql
def test_prep_requires_login(client):
    response = client.get("/prep", follow_redirects=False)
    assert response.status_code == 302
    assert "/" in response.headers.get("Location", "")


@requires_mysql
def test_bad_login_rejected(client):
    response = client.post(
        "/",
        data={"email": DEMO_EMAIL, "password": "wrong-password"},
        follow_redirects=False,
    )
    assert response.status_code == 200
    assert b"Invalid" in response.data


@requires_mysql
def test_good_login_redirects_to_prep(client):
    response = client.post(
        "/",
        data={"email": DEMO_EMAIL, "password": DEMO_PASSWORD},
        follow_redirects=False,
    )
    assert response.status_code == 302
    assert "/prep" in response.headers.get("Location", "")


@requires_mysql
def test_logout_clears_session(client):
    client.post("/", data={"email": DEMO_EMAIL, "password": DEMO_PASSWORD})
    response = client.get("/logout", follow_redirects=False)
    assert response.status_code == 302
    blocked = client.get("/history", follow_redirects=False)
    assert blocked.status_code == 302


@requires_mysql
def test_authenticated_prep_page(client):
    client.post("/", data={"email": DEMO_EMAIL, "password": DEMO_PASSWORD})
    response = client.get("/prep?date=2026-08-05&meal_period=Dinner")
    assert response.status_code == 200
    assert b"Prep Recommendations" in response.data
    assert b"Fried Chicken Plate" in response.data


@requires_mysql
def test_test_database_route(client):
    response = client.get("/test-database")
    assert response.status_code == 200
    payload = response.get_json()
    assert payload is not None
    assert "Soul Food" in payload.get("name", "")
