"""Unit tests for arceus.config."""

import json
import os
import tempfile
from pathlib import Path

import pytest

from arceus.config import ArceusConfig, _DEFAULTS
from arceus.exceptions import ConfigError


class TestArceusConfigDefaults:
    """Config should fall back to built-in defaults."""

    def test_default_backend_is_echo(self):
        cfg = ArceusConfig.default()
        assert cfg.model_backend == "echo"

    def test_default_temperature(self):
        cfg = ArceusConfig.default()
        assert cfg.temperature == 0.7

    def test_default_max_tokens(self):
        cfg = ArceusConfig.default()
        assert cfg.max_tokens == 1024

    def test_all_defaults_populated(self):
        cfg = ArceusConfig.default()
        for key, default_val in _DEFAULTS.items():
            assert getattr(cfg, key) == default_val


class TestArceusConfigEnvOverride:
    """Environment variables (ARCEUS_*) should override defaults."""

    def test_env_overrides_backend(self, monkeypatch):
        monkeypatch.setenv("ARCEUS_MODEL_BACKEND", "openai")
        cfg = ArceusConfig()
        assert cfg.model_backend == "openai"

    def test_env_overrides_temperature(self, monkeypatch):
        monkeypatch.setenv("ARCEUS_TEMPERATURE", "0.2")
        cfg = ArceusConfig()
        assert cfg.temperature == 0.2


class TestArceusConfigFromJSON:
    """Config should load from a JSON file."""

    def test_loads_valid_json(self, tmp_path):
        p = tmp_path / "cfg.json"
        p.write_text(json.dumps({"model_backend": "ollama", "temperature": 0.9}))
        cfg = ArceusConfig.from_json(p)
        assert cfg.model_backend == "ollama"
        assert cfg.temperature == 0.9

    def test_missing_file_raises(self):
        with pytest.raises(ConfigError, match="not found"):
            ArceusConfig.from_json("/nonexistent/path.json")

    def test_invalid_json_raises(self, tmp_path):
        p = tmp_path / "bad.json"
        p.write_text("{this is not json!!}")
        with pytest.raises(ConfigError, match="Invalid JSON"):
            ArceusConfig.from_json(p)

    def test_extra_keys_stored(self, tmp_path):
        p = tmp_path / "cfg.json"
        p.write_text(json.dumps({"model_backend": "echo", "custom_key": 42}))
        cfg = ArceusConfig.from_json(p)
        assert cfg._extras["custom_key"] == 42


class TestArceusConfigHelpers:
    def test_to_dict_roundtrip(self):
        cfg = ArceusConfig.default()
        d = cfg.to_dict()
        assert isinstance(d, dict)
        assert set(d.keys()) == set(_DEFAULTS.keys())

    def test_summary_contains_backend(self):
        cfg = ArceusConfig.default()
        assert "echo" in cfg.summary()
