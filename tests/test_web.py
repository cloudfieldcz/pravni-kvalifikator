"""Tests for web application routes."""

from datetime import date, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from pravni_kvalifikator.web.auth import generate_token

TEST_HMAC_KEY = "test-secret-key-for-web-tests"


def _make_mock_settings(tmp_path, auth_hmac_key: str = ""):
    """Create mock settings with given auth key."""
    mock_settings = MagicMock()
    mock_settings.sessions_db_path = tmp_path / "sessions.db"
    mock_settings.laws_db_path = tmp_path / "laws.db"
    mock_settings.log_level = "WARNING"
    mock_settings.web_host = "127.0.0.1"
    mock_settings.web_port = 8000
    mock_settings.session_expiry_days = 30
    mock_settings.auth_hmac_key = auth_hmac_key
    return mock_settings


def _make_client(mock_settings, monkeypatch):
    """Create TestClient with given mock settings."""
    monkeypatch.setattr("pravni_kvalifikator.shared.config.get_settings", lambda: mock_settings)
    monkeypatch.setattr("pravni_kvalifikator.web.main.get_settings", lambda: mock_settings)
    monkeypatch.setattr("pravni_kvalifikator.web.auth.get_settings", lambda: mock_settings)
    monkeypatch.setattr("pravni_kvalifikator.web.routes.get_settings", lambda: mock_settings)

    from pravni_kvalifikator.web.main import create_app
    from pravni_kvalifikator.web.session import SessionDB

    session_db = SessionDB(mock_settings.sessions_db_path)
    session_db.create_tables()

    app = create_app()
    return TestClient(app)


def _make_valid_token(username: str = "testuser") -> str:
    """Generate a valid token for testing."""
    expiry = (date.today() + timedelta(days=30)).strftime("%Y%m%d")
    return generate_token(username, expiry, TEST_HMAC_KEY)


def _make_expired_token(username: str = "testuser") -> str:
    """Generate an expired token for testing."""
    expiry = (date.today() - timedelta(days=1)).strftime("%Y%m%d")
    return generate_token(username, expiry, TEST_HMAC_KEY)


@pytest.fixture
def client(tmp_path, monkeypatch):
    """Create a test client with auth DISABLED (default)."""
    mock_settings = _make_mock_settings(tmp_path, auth_hmac_key="")
    return _make_client(mock_settings, monkeypatch)


@pytest.fixture
def auth_client(tmp_path, monkeypatch):
    """Create a test client with auth ENABLED."""
    mock_settings = _make_mock_settings(tmp_path, auth_hmac_key=TEST_HMAC_KEY)
    return _make_client(mock_settings, monkeypatch)


class TestWebRoutes:
    def test_index_page(self, client):
        response = client.get("/")
        assert response.status_code == 200

    def test_health_check(self, client):
        response = client.get("/health")
        assert response.status_code == 200
        assert response.json()["status"] == "healthy"

    def test_qualify_requires_min_length(self, client):
        response = client.post("/qualify", json={"popis_skutku": "short", "typ": "TC"})
        assert response.status_code == 422

    def test_qualify_requires_valid_type(self, client):
        response = client.post(
            "/qualify",
            json={"popis_skutku": "x" * 30, "typ": "INVALID"},
        )
        assert response.status_code == 422

    def test_qualify_starts_pipeline(self, client):
        with patch(
            "pravni_kvalifikator.web.routes.run_qualification",
            new_callable=AsyncMock,
        ):
            response = client.post(
                "/qualify",
                json={
                    "popis_skutku": "Pachatel odcizil z obchodu zboží v hodnotě 5 000 Kč a utekl",
                    "typ": "TC",
                },
            )
            assert response.status_code == 200
            data = response.json()
            assert "qualification_id" in data

    def test_qualify_result_not_found(self, client):
        response = client.get("/qualify/99999")
        assert response.status_code == 404

    def test_history_empty(self, client):
        response = client.get("/history")
        assert response.status_code == 200


class TestAuthEnabled:
    """Tests with authentication enabled (AUTH_HMAC_KEY set)."""

    def test_index_redirects_to_login(self, auth_client):
        response = auth_client.get("/", follow_redirects=False)
        assert response.status_code == 303
        assert response.headers["location"] == "/login"

    def test_login_page_renders(self, auth_client):
        response = auth_client.get("/login")
        assert response.status_code == 200
        assert "Přihlášení" in response.text

    def test_login_with_valid_token(self, auth_client):
        token = _make_valid_token("jan")
        response = auth_client.post("/login", data={"token": token}, follow_redirects=False)
        assert response.status_code == 303
        assert response.headers["location"] == "/"
        assert "auth_token" in response.headers.get("set-cookie", "")

    def test_login_with_invalid_token(self, auth_client):
        response = auth_client.post(
            "/login", data={"token": "invalid:token:value"}, follow_redirects=False
        )
        assert response.status_code == 401
        assert "Neplatný nebo prošlý token" in response.text

    def test_login_with_expired_token(self, auth_client):
        token = _make_expired_token("jan")
        response = auth_client.post("/login", data={"token": token}, follow_redirects=False)
        assert response.status_code == 401
        assert "Neplatný nebo prošlý token" in response.text

    def test_authenticated_access(self, auth_client):
        token = _make_valid_token("jan")
        auth_client.cookies.set("auth_token", token)
        response = auth_client.get("/")
        assert response.status_code == 200

    def test_logout_clears_cookie(self, auth_client):
        token = _make_valid_token("jan")
        auth_client.cookies.set("auth_token", token)
        response = auth_client.get("/logout", follow_redirects=False)
        assert response.status_code == 303
        assert response.headers["location"] == "/login"

    def test_health_check_no_auth_needed(self, auth_client):
        response = auth_client.get("/health")
        assert response.status_code == 200
        assert response.json()["status"] == "healthy"

    def test_session_bound_to_username(self, auth_client):
        token = _make_valid_token("jan")
        auth_client.cookies.set("auth_token", token)
        with patch(
            "pravni_kvalifikator.web.routes.run_qualification",
            new_callable=AsyncMock,
        ):
            response = auth_client.post(
                "/qualify",
                json={
                    "popis_skutku": "Pachatel odcizil z obchodu zboží v hodnotě 5 000 Kč a utekl",
                    "typ": "TC",
                },
            )
            assert response.status_code == 200
            qid = response.json()["qualification_id"]

        # Same user can access the qualification
        response = auth_client.get(f"/qualify/{qid}")
        assert response.status_code == 200

    def test_access_control_blocks_other_user(self, auth_client):
        # Create qualification as "jan"
        token_jan = _make_valid_token("jan")
        auth_client.cookies.set("auth_token", token_jan)
        with patch(
            "pravni_kvalifikator.web.routes.run_qualification",
            new_callable=AsyncMock,
        ):
            response = auth_client.post(
                "/qualify",
                json={
                    "popis_skutku": "Pachatel odcizil z obchodu zboží v hodnotě 5 000 Kč a utekl",
                    "typ": "TC",
                },
            )
            qid = response.json()["qualification_id"]

        # Try to access as "petr" → 404
        token_petr = _make_valid_token("petr")
        auth_client.cookies.set("auth_token", token_petr)
        response = auth_client.get(f"/qualify/{qid}")
        assert response.status_code == 404

    def test_access_control_blocks_api_endpoint(self, auth_client):
        # Create qualification as "jan"
        token_jan = _make_valid_token("jan")
        auth_client.cookies.set("auth_token", token_jan)
        with patch(
            "pravni_kvalifikator.web.routes.run_qualification",
            new_callable=AsyncMock,
        ):
            response = auth_client.post(
                "/qualify",
                json={
                    "popis_skutku": "Pachatel odcizil z obchodu zboží v hodnotě 5 000 Kč a utekl",
                    "typ": "TC",
                },
            )
            qid = response.json()["qualification_id"]

        # Try API endpoint as "petr" → 404
        token_petr = _make_valid_token("petr")
        auth_client.cookies.set("auth_token", token_petr)
        response = auth_client.get(f"/api/qualify/{qid}")
        assert response.status_code == 404

    def test_access_control_blocks_stream_endpoint(self, auth_client):
        # Create qualification as "jan"
        token_jan = _make_valid_token("jan")
        auth_client.cookies.set("auth_token", token_jan)
        with patch(
            "pravni_kvalifikator.web.routes.run_qualification",
            new_callable=AsyncMock,
        ):
            response = auth_client.post(
                "/qualify",
                json={
                    "popis_skutku": "Pachatel odcizil z obchodu zboží v hodnotě 5 000 Kč a utekl",
                    "typ": "TC",
                },
            )
            qid = response.json()["qualification_id"]

        # Try stream endpoint as "petr" → 404
        token_petr = _make_valid_token("petr")
        auth_client.cookies.set("auth_token", token_petr)
        response = auth_client.get(f"/qualify/{qid}/stream")
        assert response.status_code == 404

    def test_login_page_redirects_when_auth_disabled(self, client):
        """When AUTH_HMAC_KEY is empty, /login redirects to /."""
        response = client.get("/login", follow_redirects=False)
        assert response.status_code == 303
        assert response.headers["location"] == "/"

    def test_username_shown_in_header(self, auth_client):
        token = _make_valid_token("jan")
        auth_client.cookies.set("auth_token", token)
        response = auth_client.get("/")
        assert "jan" in response.text
        assert "Odhlásit" in response.text

    def test_same_user_different_login_sees_same_history(self, auth_client):
        """Login as 'jan', create qual, login again as 'jan' → same history."""
        token = _make_valid_token("jan")
        auth_client.cookies.set("auth_token", token)
        with patch(
            "pravni_kvalifikator.web.routes.run_qualification",
            new_callable=AsyncMock,
        ):
            auth_client.post(
                "/qualify",
                json={
                    "popis_skutku": "Pachatel odcizil z obchodu zboží v hodnotě 5 000 Kč a utekl",
                    "typ": "TC",
                },
            )

        # "Re-login" — same token, history should persist
        response = auth_client.get("/history")
        assert response.status_code == 200
