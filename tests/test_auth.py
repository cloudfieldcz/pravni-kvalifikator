"""Tests for HMAC SHA-256 authentication module."""

from datetime import date, timedelta

import pytest

from pravni_kvalifikator.web.auth import (
    AuthRequired,
    compute_hmac,
    generate_token,
    parse_token,
    validate_token,
)

TEST_KEY = "test-secret-key-12345"


class TestParseToken:
    def test_valid_token(self):
        username, platnost_do, hex_token = parse_token("jan:20261231:abcdef1234567890")
        assert username == "jan"
        assert platnost_do == "20261231"
        assert hex_token == "abcdef1234567890"

    def test_missing_parts(self):
        with pytest.raises(ValueError, match="USERNAME:YYYYMMDD:TOKEN"):
            parse_token("jan:20261231")

    def test_too_many_parts(self):
        with pytest.raises(ValueError, match="USERNAME:YYYYMMDD:TOKEN"):
            parse_token("jan:20261231:abc:extra")

    def test_empty_string(self):
        with pytest.raises(ValueError, match="USERNAME:YYYYMMDD:TOKEN"):
            parse_token("")

    def test_username_with_colon(self):
        # Colon is the delimiter — can't appear in username
        with pytest.raises(ValueError, match="USERNAME:YYYYMMDD:TOKEN"):
            parse_token("user:name:20261231:abc")

    def test_username_with_space(self):
        with pytest.raises(ValueError, match="uživatelské jméno"):
            parse_token("user name:20261231:abc")

    def test_username_with_unicode(self):
        with pytest.raises(ValueError, match="uživatelské jméno"):
            parse_token("uživatel:20261231:abc")

    def test_username_too_long(self):
        long_name = "a" * 65
        with pytest.raises(ValueError, match="uživatelské jméno"):
            parse_token(f"{long_name}:20261231:abc")

    def test_username_max_length_ok(self):
        name = "a" * 64
        username, _, _ = parse_token(f"{name}:20261231:abc")
        assert username == name

    def test_invalid_date_format(self):
        with pytest.raises(ValueError, match="datum platnosti"):
            parse_token("jan:2026-12-31:abc")

    def test_date_too_short(self):
        with pytest.raises(ValueError, match="datum platnosti"):
            parse_token("jan:202612:abc")

    def test_valid_username_chars(self):
        username, _, _ = parse_token("jan.novak-test_1:20261231:abc")
        assert username == "jan.novak-test_1"


class TestComputeHmac:
    def test_deterministic(self):
        h1 = compute_hmac("jan", "20261231", TEST_KEY)
        h2 = compute_hmac("jan", "20261231", TEST_KEY)
        assert h1 == h2

    def test_different_username(self):
        h1 = compute_hmac("jan", "20261231", TEST_KEY)
        h2 = compute_hmac("petr", "20261231", TEST_KEY)
        assert h1 != h2

    def test_different_date(self):
        h1 = compute_hmac("jan", "20261231", TEST_KEY)
        h2 = compute_hmac("jan", "20270101", TEST_KEY)
        assert h1 != h2

    def test_different_key(self):
        h1 = compute_hmac("jan", "20261231", "key1")
        h2 = compute_hmac("jan", "20261231", "key2")
        assert h1 != h2

    def test_returns_hex_string(self):
        result = compute_hmac("jan", "20261231", TEST_KEY)
        assert len(result) == 64  # SHA-256 hex digest
        int(result, 16)  # Valid hex


class TestGenerateToken:
    def test_roundtrip(self):
        token = generate_token("jan", "20261231", TEST_KEY)
        username, platnost_do, hex_token = parse_token(token)
        assert username == "jan"
        assert platnost_do == "20261231"
        expected = compute_hmac("jan", "20261231", TEST_KEY)
        assert hex_token == expected

    def test_invalid_username_rejected(self):
        with pytest.raises(ValueError, match="uživatelské jméno"):
            generate_token("user name", "20261231", TEST_KEY)

    def test_invalid_date_rejected(self):
        with pytest.raises(ValueError, match="datum platnosti"):
            generate_token("jan", "not-a-date", TEST_KEY)

    def test_unparseable_date_rejected(self):
        with pytest.raises(ValueError):
            generate_token("jan", "99991399", TEST_KEY)  # Month 13 is invalid


class TestValidateToken:
    def _make_token(self, username: str = "jan", days_from_now: int = 30) -> str:
        expiry = date.today() + timedelta(days=days_from_now)
        platnost_do = expiry.strftime("%Y%m%d")
        return generate_token(username, platnost_do, TEST_KEY)

    def test_valid_token(self):
        token = self._make_token()
        assert validate_token(token, TEST_KEY) == "jan"

    def test_today_is_valid(self):
        token = self._make_token(days_from_now=0)
        assert validate_token(token, TEST_KEY) == "jan"

    def test_expired_yesterday(self):
        token = self._make_token(days_from_now=-1)
        assert validate_token(token, TEST_KEY) is None

    def test_invalid_hmac(self):
        token = self._make_token()
        # Tamper with last char of hex
        tampered = token[:-1] + ("0" if token[-1] != "0" else "1")
        assert validate_token(tampered, TEST_KEY) is None

    def test_wrong_key(self):
        token = self._make_token()
        assert validate_token(token, "wrong-key") is None

    def test_bad_format(self):
        assert validate_token("not-a-token", TEST_KEY) is None

    def test_empty_string(self):
        assert validate_token("", TEST_KEY) is None

    def test_empty_key_makes_auth_disabled(self):
        # With empty key, tokens generated with empty key validate with empty key
        token = generate_token("jan", "20261231", "")
        assert validate_token(token, "") == "jan"


class TestAuthRequiredException:
    def test_is_exception(self):
        assert issubclass(AuthRequired, Exception)

    def test_can_raise(self):
        with pytest.raises(AuthRequired):
            raise AuthRequired()


class TestCreateSessionWithId:
    def test_create_new(self, session_db):
        result = session_db.create_session_with_id("jan")
        assert result == "jan"
        session = session_db.get_session("jan")
        assert session is not None
        assert session["id"] == "jan"

    def test_idempotent(self, session_db):
        session_db.create_session_with_id("jan")
        # Second call should not raise (INSERT OR IGNORE)
        result = session_db.create_session_with_id("jan")
        assert result == "jan"
        session = session_db.get_session("jan")
        assert session is not None
