import pytest
from unittest.mock import patch
from typer.testing import CliRunner


class TestInitCommand:
    def test_init_success(self):
        from btt.__main__ import app
        runner = CliRunner()
        with patch("btt.commands.init.asyncio.run", return_value=None):
            result = runner.invoke(app, ["init"])
        assert result.exit_code == 0
        assert "initialized successfully" in result.output

    def test_init_failure(self):
        from btt.__main__ import app
        runner = CliRunner()
        with patch("btt.commands.init.asyncio.run", side_effect=Exception("DB error")):
            result = runner.invoke(app, ["init"])
        assert result.exit_code == 1
        assert "Failed" in result.output