import asyncio
import pytest
from unittest.mock import patch, MagicMock
from typer.testing import CliRunner

from btt.database.models import FileStatus

MOCK_STATS = {
    "total": 5,
    "pending": 3,
    "uploading": 0,
    "success": 2,
    "failed": 0,
}


class TestStatusCommand:
    def _invoke(self, args=None, stats=None, authorized=False):
        from btt.__main__ import app
        runner = CliRunner()
        _stats = stats or MOCK_STATS

        async def fake_get_status_data(*_):
            return _stats, ("Alexey" if authorized else None), None

        with patch("btt.commands.status.is_db_initialized", return_value=True), \
             patch("btt.commands.status.load_config", return_value={}), \
             patch("btt.commands.status.asyncio.run",
                   side_effect=lambda coro: asyncio.get_event_loop().run_until_complete(coro)), \
             patch("btt.commands.status.get_status_data", side_effect=fake_get_status_data):
            return runner.invoke(app, ["status"] + (args or []))

    def test_shows_stats_table(self):
        result = self._invoke()
        assert result.exit_code == 0
        assert "Backup Index Status" in result.output
        assert "5" in result.output

    def test_shows_not_authorized(self):
        with patch("btt.commands.status.Path.exists", return_value=False):
            result = self._invoke()
        assert "Not Authorized" in result.output

    def test_shows_authorized(self):
        result = self._invoke(authorized=True)
        assert "Alexey" in result.output

    def test_pending_hint(self):
        result = self._invoke()
        assert "btt upload" in result.output

    def test_no_pending_hint_when_all_done(self):
        stats = {**MOCK_STATS, "pending": 0}
        result = self._invoke(stats=stats)
        assert "up to date" in result.output

    def test_db_not_initialized(self):
        from btt.__main__ import app
        runner = CliRunner()
        with patch("btt.commands.status.is_db_initialized", return_value=False):
            result = runner.invoke(app, ["status"])
        assert result.exit_code == 1
        assert "btt init" in result.output

    def test_list_flag_shows_files_table(self):
        from btt.__main__ import app
        from btt.database.models import File
        runner = CliRunner()

        mock_file = MagicMock(spec=File)
        mock_file.id = 1
        mock_file.filepath = "/home/user/song.mp3"
        mock_file.status = FileStatus.PENDING.value

        async def fake_get_all():
            return [mock_file]

        with patch("btt.commands.status.is_db_initialized", return_value=True), \
             patch("btt.commands.status.load_config", return_value={}), \
             patch("btt.commands.status.asyncio.run",
                   side_effect=lambda coro: asyncio.get_event_loop().run_until_complete(coro)), \
             patch("btt.commands.status.get_all_files_data", side_effect=fake_get_all):
            result = runner.invoke(app, ["status", "--list"])

        assert result.exit_code == 0
        assert "song.mp3" in result.output
        assert "Indexed Files" in result.output

    def test_list_flag_hides_stats_tables(self):
        from btt.__main__ import app
        runner = CliRunner()

        async def fake_get_all():
            return []

        with patch("btt.commands.status.is_db_initialized", return_value=True), \
             patch("btt.commands.status.load_config", return_value={}), \
             patch("btt.commands.status.asyncio.run",
                   side_effect=lambda coro: asyncio.get_event_loop().run_until_complete(coro)), \
             patch("btt.commands.status.get_all_files_data", side_effect=fake_get_all):
            result = runner.invoke(app, ["status", "--list"])

        assert "Backup Index Status" not in result.output
        assert "Telegram Configuration" not in result.output