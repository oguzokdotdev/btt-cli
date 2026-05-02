import asyncio
import hashlib
import pytest
from unittest.mock import patch, MagicMock
from typer.testing import CliRunner
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession

from btt.database.models import Base
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


class TestGetFileHash:
    def test_hash_returns_hex_string(self, tmp_path):
        from btt.commands.add import get_file_hash
        f = tmp_path / "file.bin"
        f.write_bytes(b"hello world")
        result = get_file_hash(f)
        assert isinstance(result, str)
        assert len(result) == 64

    def test_hash_is_deterministic(self, tmp_path):
        from btt.commands.add import get_file_hash
        f = tmp_path / "file.bin"
        f.write_bytes(b"some content")
        assert get_file_hash(f) == get_file_hash(f)

    def test_different_content_different_hash(self, tmp_path):
        from btt.commands.add import get_file_hash
        f1 = tmp_path / "a.bin"
        f2 = tmp_path / "b.bin"
        f1.write_bytes(b"aaa")
        f2.write_bytes(b"bbb")
        assert get_file_hash(f1) != get_file_hash(f2)

    def test_large_file_chunked_correctly(self, tmp_path):
        from btt.commands.add import get_file_hash
        data = b"x" * (65536 * 3)
        f = tmp_path / "big.bin"
        f.write_bytes(data)
        expected = hashlib.sha256(data).hexdigest()
        assert get_file_hash(f) == expected


class TestProcessAndAddFiles:
    async def test_adds_single_file(self, tmp_path):
        from btt.commands.add import process_and_add_files
        f = tmp_path / "track.mp3"
        f.write_bytes(b"audio")
        added, skipped = await process_and_add_files([f])
        assert added == 1
        assert skipped == 0

    async def test_skips_duplicate(self, tmp_path):
        from btt.commands.add import process_and_add_files
        f = tmp_path / "track.mp3"
        f.write_bytes(b"audio")
        await process_and_add_files([f])
        added, skipped = await process_and_add_files([f])
        assert added == 0
        assert skipped == 1

    async def test_adds_multiple_files(self, tmp_path):
        from btt.commands.add import process_and_add_files
        files = []
        for i in range(5):
            f = tmp_path / f"file{i}.mp3"
            f.write_bytes(f"content{i}".encode())
            files.append(f)
        added, skipped = await process_and_add_files(files)
        assert added == 5
        assert skipped == 0


class TestAddCommand:
    def test_add_single_file(self, tmp_path):
        from btt.__main__ import app
        f = tmp_path / "song.mp3"
        f.write_bytes(b"data")
        runner = CliRunner()
        with patch("btt.commands.add.is_db_initialized", return_value=True), \
             patch("btt.commands.add.asyncio.run", return_value=(1, 0)):
            result = runner.invoke(app, ["add", str(f)])
        assert result.exit_code == 0
        assert "Added: 1" in result.output

    def test_add_directory(self, tmp_path):
        from btt.__main__ import app
        for i in range(3):
            (tmp_path / f"file{i}.mp3").write_bytes(b"x")
        runner = CliRunner()
        with patch("btt.commands.add.is_db_initialized", return_value=True), \
             patch("btt.commands.add.asyncio.run", return_value=(3, 0)):
            result = runner.invoke(app, ["add", str(tmp_path)])
        assert result.exit_code == 0
        assert "Found 3 files" in result.output

    def test_add_empty_directory(self, tmp_path):
        from btt.__main__ import app
        runner = CliRunner()
        with patch("btt.commands.add.is_db_initialized", return_value=True):
            result = runner.invoke(app, ["add", str(tmp_path)])
        assert result.exit_code == 0
        assert "No files found" in result.output

    def test_add_without_init(self, tmp_path):
        from btt.__main__ import app
        f = tmp_path / "song.mp3"
        f.write_bytes(b"data")
        runner = CliRunner()
        with patch("btt.commands.add.is_db_initialized", return_value=False):
            result = runner.invoke(app, ["add", str(f)])
        assert result.exit_code == 1
        assert "btt init" in result.output

    def test_add_nonexistent_path(self, tmp_path):
        from btt.__main__ import app
        runner = CliRunner()
        result = runner.invoke(app, ["add", str(tmp_path / "nonexistent.mp3")])
        assert result.exit_code != 0