"""Utility function tests."""
import pytest

from main import _hash_password, unique, extract_json


class TestPasswordHashing:
    """Password hashing utility tests."""

    def test_hash_password_deterministic(self):
        """Same password + salt = same hash."""
        salt = "a" * 32
        hash1 = _hash_password("testpass", salt)
        hash2 = _hash_password("testpass", salt)
        assert hash1 == hash2
        assert len(hash1) == 64  # SHA256 hex

    def test_hash_password_different_salt(self):
        """Different salt = different hash."""
        hash1 = _hash_password("testpass", "a" * 32)
        hash2 = _hash_password("testpass", "b" * 32)
        assert hash1 != hash2

    def test_hash_password_different_password(self):
        """Different password = different hash."""
        salt = "a" * 32
        hash1 = _hash_password("password1", salt)
        hash2 = _hash_password("password2", salt)
        assert hash1 != hash2


class TestUnique:
    """Unique deduplication utility tests."""

    def test_unique_basic(self):
        """Basic deduplication."""
        result = unique(["python", "Python", "PYTHON", "fastapi", "FastAPI"])
        assert result == ["python", "fastapi"]

    def test_unique_preserves_order(self):
        """First occurrence preserved."""
        result = unique(["b", "a", "b", "c", "a"])
        assert result == ["b", "a", "c"]

    def test_unique_empty(self):
        """Empty input."""
        assert unique([]) == []

    def test_unique_whitespace(self):
        """Whitespace normalization."""
        result = unique(["  python  ", "python", "\tfastapi\n"])
        assert result == ["python", "fastapi"]

    def test_unique_case_insensitive(self):
        """Case insensitive comparison."""
        result = unique(["Python", "PYTHON", "python"])
        assert result == ["Python"]


class TestExtractJson:
    """JSON extraction utility tests."""

    def test_extract_json_simple(self):
        """Extract JSON from simple text."""
        text = 'Here is the result: {"key": "value"} and done.'
        result = extract_json(text)
        assert result == {"key": "value"}

    def test_extract_json_nested(self):
        """Extract nested JSON."""
        text = 'Result: {"outer": {"inner": [1, 2, 3]}}'
        result = extract_json(text)
        assert result == {"outer": {"inner": [1, 2, 3]}}

    def test_extract_json_no_json(self):
        """No JSON raises ValueError."""
        with pytest.raises(ValueError, match="AI response did not contain JSON"):
            extract_json("No JSON here")

    def test_extract_json_first_object(self):
        """First complete JSON object extracted."""
        text = 'First: {"a": 1} Second: {"b": 2}'
        result = extract_json(text)
        assert result == {"a": 1}
