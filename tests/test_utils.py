"""Unit tests for arceus.utils."""

from arceus.utils import banner, sanitize_input, setup_logging


class TestSanitizeInput:
    def test_strips_whitespace(self):
        assert sanitize_input("  hello  ") == "hello"

    def test_collapses_internal_spaces(self):
        assert sanitize_input("hello   world") == "hello world"

    def test_handles_tabs_and_newlines(self):
        assert sanitize_input("hello\t\n  world") == "hello world"

    def test_empty_string(self):
        assert sanitize_input("") == ""

    def test_only_whitespace(self):
        assert sanitize_input("   ") == ""


class TestBanner:
    def test_contains_arceus(self):
        assert "A R C E U S" in banner()

    def test_contains_version(self):
        assert "v0.1" in banner()


class TestSetupLogging:
    def test_does_not_raise(self):
        setup_logging("DEBUG")
        setup_logging("INFO")
