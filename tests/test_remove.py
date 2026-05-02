import pytest
from unittest.mock import patch
from typer.testing import CliRunner
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession

from btt.database.models import Base, FileStatus
from btt.database.manager import DatabaseManager

TEST_DATABASE_URL = "sqlite+aiosqlite:///:memory:"
test_engine = create_async_engine(TEST_DATABASE_URL, echo=False)
TestingSessionLocal = async_sessionmaker(test_engine, class_=AsyncSession, expire_on_commit=False)


@pytest.fixture(autouse=True)
async def setup_test_db():
    async with test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    with patch("btt.database.manager.AsyncSessionLocal", TestingSessionLocal):
        yield
    async with test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)


class TestProcessAndRemoveFiles:
    async def test_removes_existing_file(self, tmp_path):
        from btt.commands.remove import process_and_remove_files
        f = tmp_path / "track.mp3"
        f.write_bytes(b"audio")
        await DatabaseManager.add_file(str(f.resolve()), "hash")
        removed, not_found = await process_and_remove_files([f])
        assert removed == 1
        assert not_found == 0

    async def test_not_found_when_not_indexed(self, tmp_path):
        from btt.commands.remove import process_and_remove_files
        f = tmp_path / "track.mp3"
        f.write_bytes(b"audio")
        removed, not_found = await process_and_remove_files([f])
        assert removed == 0
        assert not_found == 1

    async def test_removes_multiple_files(self, tmp_path):
        from btt.commands.remove import process_and_remove_files
        files = []
        for i in range(3):
            f = tmp_path / f"file{i}.mp3"
            f.write_bytes(b"x")
            await DatabaseManager.add_file(str(f.resolve()), f"hash{i}")
            files.append(f)
        removed, not_found = await process_and_remove_files(files)
        assert removed == 3
        assert not_found == 0

    async def test_mixed_found_and_not_found(self, tmp_path):
        from btt.commands.remove import process_and_remove_files
        f1 = tmp_path / "exists.mp3"
        f2 = tmp_path / "missing.mp3"
        f1.write_bytes(b"x")
        f2.write_bytes(b"x")
        await DatabaseManager.add_file(str(f1.resolve()), "hash1")
        removed, not_found = await process_and_remove_files([f1, f2])
        assert removed == 1
        assert not_found == 1


class TestRemoveCommand:
    def test_remove_single_file(self, tmp_path):
        from btt.__main__ import app
        f = tmp_path / "song.mp3"
        f.write_bytes(b"data")
        runner = CliRunner()
        with patch("btt.commands.remove.is_db_initialized", return_value=True), \
             patch("btt.commands.remove.asyncio.run", return_value=(1, 0)):
            result = runner.invoke(app, ["remove", str(f)])
        assert result.exit_code == 0
        assert "Removed: 1" in result.output

    def test_remove_directory(self, tmp_path):
        from btt.__main__ import app
        for i in range(3):
            (tmp_path / f"file{i}.mp3").write_bytes(b"x")
        runner = CliRunner()
        with patch("btt.commands.remove.is_db_initialized", return_value=True), \
             patch("btt.commands.remove.asyncio.run", return_value=(3, 0)):
            result = runner.invoke(app, ["remove", str(tmp_path)])
        assert result.exit_code == 0
        assert "Found 3 target paths" in result.output

    def test_remove_without_init(self, tmp_path):
        from btt.__main__ import app
        f = tmp_path / "song.mp3"
        f.write_bytes(b"data")
        runner = CliRunner()
        with patch("btt.commands.remove.is_db_initialized", return_value=False):
            result = runner.invoke(app, ["remove", str(f)])
        assert result.exit_code == 1
        assert "btt init" in result.output

    def test_remove_not_found_in_index(self, tmp_path):
        from btt.__main__ import app
        f = tmp_path / "song.mp3"
        f.write_bytes(b"data")
        runner = CliRunner()
        with patch("btt.commands.remove.is_db_initialized", return_value=True), \
             patch("btt.commands.remove.asyncio.run", return_value=(0, 1)):
            result = runner.invoke(app, ["remove", str(f)])
        assert result.exit_code == 0
        assert "Not found in index: 1" in result.output
