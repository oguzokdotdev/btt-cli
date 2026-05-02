import json
import pytest
from unittest.mock import patch
from typer.testing import CliRunner


class TestLoadConfig:
    def test_returns_empty_dict_when_no_file(self, tmp_path):
        from btt.commands.config import load_config
        with patch("btt.commands.config.CONFIG_FILE", tmp_path / "config.json"):
            result = load_config()
        assert result == {}

    def test_loads_existing_config(self, tmp_path):
        from btt.commands.config import load_config
        cfg = tmp_path / "config.json"
        cfg.write_text(json.dumps({"api_id": 123, "api_hash": "abc"}))
        with patch("btt.commands.config.CONFIG_FILE", cfg):
            result = load_config()
        assert result["api_id"] == 123
        assert result["api_hash"] == "abc"


class TestSaveConfig:
    def test_saves_and_reads_back(self, tmp_path):
        from btt.commands.config import save_config, load_config
        cfg_file = tmp_path / "config.json"
        with patch("btt.commands.config.CONFIG_FILE", cfg_file), \
             patch("btt.commands.config.CONFIG_DIR", tmp_path):
            save_config({"api_id": 42})
            result = load_config()
        assert result["api_id"] == 42

    def test_overwrites_existing(self, tmp_path):
        from btt.commands.config import save_config, load_config
        cfg_file = tmp_path / "config.json"
        with patch("btt.commands.config.CONFIG_FILE", cfg_file), \
             patch("btt.commands.config.CONFIG_DIR", tmp_path):
            save_config({"api_id": 1})
            save_config({"api_id": 2})
            result = load_config()
        assert result["api_id"] == 2


class TestConfigCommand:
    def test_set_api_id(self, tmp_path):
        from btt.__main__ import app
        cfg_file = tmp_path / "config.json"
        runner = CliRunner()
        with patch("btt.commands.config.CONFIG_FILE", cfg_file), \
             patch("btt.commands.config.CONFIG_DIR", tmp_path):
            result = runner.invoke(app, ["config", "api.id", "12345"])
        assert result.exit_code == 0
        data = json.loads(cfg_file.read_text())
        assert data["api_id"] == 12345

    def test_set_api_id_invalid(self, tmp_path):
        from btt.__main__ import app
        cfg_file = tmp_path / "config.json"
        runner = CliRunner()
        with patch("btt.commands.config.CONFIG_FILE", cfg_file), \
             patch("btt.commands.config.CONFIG_DIR", tmp_path):
            result = runner.invoke(app, ["config", "api.id", "not_a_number"])
        assert result.exit_code == 1
        assert "must be an integer" in result.output

    def test_get_existing_key(self, tmp_path):
        from btt.__main__ import app
        cfg_file = tmp_path / "config.json"
        cfg_file.write_text(json.dumps({"api_hash": "myhash"}))
        runner = CliRunner()
        with patch("btt.commands.config.CONFIG_FILE", cfg_file), \
             patch("btt.commands.config.CONFIG_DIR", tmp_path):
            result = runner.invoke(app, ["config", "api.hash"])
        assert "myhash" in result.output

    def test_list_config(self, tmp_path):
        from btt.__main__ import app
        cfg_file = tmp_path / "config.json"
        cfg_file.write_text(json.dumps({"api_id": 1, "api_hash": "x"}))
        runner = CliRunner()
        with patch("btt.commands.config.CONFIG_FILE", cfg_file), \
             patch("btt.commands.config.CONFIG_DIR", tmp_path):
            result = runner.invoke(app, ["config", "--list"])
        assert "api.id" in result.output
        assert "api.hash" in result.output

    def test_list_empty_config(self, tmp_path):
        from btt.__main__ import app
        cfg_file = tmp_path / "config.json"
        runner = CliRunner()
        with patch("btt.commands.config.CONFIG_FILE", cfg_file), \
             patch("btt.commands.config.CONFIG_DIR", tmp_path):
            result = runner.invoke(app, ["config", "--list"])
        assert "not set" in result.output