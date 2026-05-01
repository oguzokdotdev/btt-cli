import pytest
from unittest.mock import patch
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from btt.database.models import Base, File, FileStatus
from btt.database.manager import DatabaseManager

# --- Test Database Setup ---
TEST_DATABASE_URL = "sqlite+aiosqlite:///:memory:"
test_engine = create_async_engine(TEST_DATABASE_URL, echo=False)
TestingSessionLocal = async_sessionmaker(test_engine, class_=AsyncSession, expire_on_commit=False)


@pytest.fixture(autouse=True)
async def setup_test_db():
    """
    Creates a fresh in-memory database before each test.
    Automatically patches the DatabaseManager to use the test database.
    """
    async with test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    
    with patch("btt.database.manager.AsyncSessionLocal", TestingSessionLocal):
        yield
    
    async with test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)


# --- add_file() Tests ---
class TestAddFile:
    """Test suite for DatabaseManager.add_file()"""

    async def test_add_file_success(self):
        """Successfully add a new file to the database."""
        filepath = "/home/user/music.mp3"
        file_hash = "sha256_hash_value"
        
        result = await DatabaseManager.add_file(filepath, file_hash)
        
        assert result is True
        assert await DatabaseManager.file_exists(filepath) is True

    async def test_add_file_duplicate(self):
        """Prevent duplicate files with the same filepath."""
        filepath = "/home/user/music.mp3"
        
        # First add succeeds
        assert await DatabaseManager.add_file(filepath, "hash1") is True
        
        # Second add with same path fails
        assert await DatabaseManager.add_file(filepath, "hash2") is False
        
        # File count should still be 1
        assert len(await DatabaseManager.get_all_files()) == 1

    async def test_add_multiple_files(self):
        """Add multiple files with different paths."""
        files_to_add = [
            ("/home/user/file1.mp3", "hash1"),
            ("/home/user/file2.mp3", "hash2"),
            ("/home/user/file3.mp3", "hash3"),
        ]
        
        for filepath, file_hash in files_to_add:
            assert await DatabaseManager.add_file(filepath, file_hash) is True
        
        all_files = await DatabaseManager.get_all_files()
        assert len(all_files) == 3
        
        # All should have PENDING status by default
        for file in all_files:
            assert file.status == FileStatus.PENDING.value

    async def test_add_file_with_special_characters(self):
        """Handle filepaths with special characters."""
        filepath = "/home/user/文件.mp3"  # Chinese characters
        result = await DatabaseManager.add_file(filepath, "hash")
        assert result is True


# --- get_files_by_status() Tests ---
class TestGetFilesByStatus:
    """Test suite for DatabaseManager.get_files_by_status()"""

    async def test_get_pending_files(self):
        """Retrieve files with PENDING status."""
        await DatabaseManager.add_file("/file1.mp3", "hash1")
        await DatabaseManager.add_file("/file2.mp3", "hash2")
        
        pending = await DatabaseManager.get_files_by_status(FileStatus.PENDING)
        
        assert len(pending) == 2
        assert all(f.status == FileStatus.PENDING.value for f in pending)

    async def test_get_files_empty_status(self):
        """Return empty list when no files match the status."""
        await DatabaseManager.add_file("/file1.mp3", "hash1")
        
        success = await DatabaseManager.get_files_by_status(FileStatus.SUCCESS)
        
        assert success == []
        assert isinstance(success, list)

    async def test_files_ordered_by_id(self):
        """Files should be ordered by ID for consistent processing."""
        for i in range(5):
            await DatabaseManager.add_file(f"/file{i}.mp3", f"hash{i}")
        
        pending = await DatabaseManager.get_files_by_status(FileStatus.PENDING)
        
        # Check IDs are in ascending order
        ids = [f.id for f in pending]
        assert ids == sorted(ids)

    async def test_mixed_statuses(self):
        """Retrieve files when multiple statuses exist in database."""
        file1_id = (await DatabaseManager.add_file("/file1.mp3", "h1"), 
                    await DatabaseManager.get_all_files())[1][0].id
        file2_id = (await DatabaseManager.add_file("/file2.mp3", "h2"),
                    await DatabaseManager.get_all_files())[1][1].id
        
        # Change file1 to SUCCESS
        await DatabaseManager.update_status(file1_id, FileStatus.SUCCESS)
        
        pending = await DatabaseManager.get_files_by_status(FileStatus.PENDING)
        success = await DatabaseManager.get_files_by_status(FileStatus.SUCCESS)
        
        assert len(pending) == 1
        assert len(success) == 1


# --- get_all_files() Tests ---
class TestGetAllFiles:
    """Test suite for DatabaseManager.get_all_files()"""

    async def test_get_all_files_empty(self):
        """Return empty list when database is empty."""
        files = await DatabaseManager.get_all_files()
        assert files == []

    async def test_get_all_files_multiple(self):
        """Retrieve all files regardless of status."""
        for i in range(3):
            await DatabaseManager.add_file(f"/file{i}.mp3", f"hash{i}")
        
        all_files = await DatabaseManager.get_all_files()
        assert len(all_files) == 3

    async def test_get_all_files_includes_all_statuses(self):
        """Verify get_all_files includes all statuses."""
        await DatabaseManager.add_file("/file1.mp3", "h1")
        await DatabaseManager.add_file("/file2.mp3", "h2")
        
        files = await DatabaseManager.get_all_files()
        await DatabaseManager.update_status(files[0].id, FileStatus.SUCCESS)
        
        all_files = await DatabaseManager.get_all_files()
        statuses = {f.status for f in all_files}
        
        assert len(statuses) == 2  # PENDING and SUCCESS


# --- get_file_by_id() Tests ---
class TestGetFileById:
    """Test suite for DatabaseManager.get_file_by_id()"""

    async def test_get_existing_file(self):
        """Retrieve a file by its ID."""
        await DatabaseManager.add_file("/test.mp3", "hash")
        file_id = (await DatabaseManager.get_all_files())[0].id
        
        file = await DatabaseManager.get_file_by_id(file_id)
        
        assert file is not None
        assert file.id == file_id
        assert file.filepath == "/test.mp3"

    async def test_get_nonexistent_file(self):
        """Return None for nonexistent file ID."""
        file = await DatabaseManager.get_file_by_id(999)
        assert file is None

    async def test_get_file_with_message_id(self):
        """Retrieve file that has a Telegram message_id set."""
        await DatabaseManager.add_file("/test.mp3", "hash")
        file_id = (await DatabaseManager.get_all_files())[0].id
        
        await DatabaseManager.update_status(file_id, FileStatus.SUCCESS, message_id=12345)
        
        file = await DatabaseManager.get_file_by_id(file_id)
        assert file.message_id == 12345


# --- update_status() Tests ---
class TestUpdateStatus:
    """Test suite for DatabaseManager.update_status()"""

    async def test_update_status_basic(self):
        """Update file status from PENDING to another status."""
        await DatabaseManager.add_file("/test.mp3", "hash")
        file_id = (await DatabaseManager.get_all_files())[0].id
        
        result = await DatabaseManager.update_status(file_id, FileStatus.UPLOADING)
        
        assert result is True
        updated_file = await DatabaseManager.get_file_by_id(file_id)
        assert updated_file.status == FileStatus.UPLOADING.value

    async def test_update_status_with_message_id(self):
        """Update status and set Telegram message_id simultaneously."""
        await DatabaseManager.add_file("/test.mp3", "hash")
        file_id = (await DatabaseManager.get_all_files())[0].id
        
        result = await DatabaseManager.update_status(
            file_id,
            FileStatus.SUCCESS,
            message_id=999
        )
        
        assert result is True
        file = await DatabaseManager.get_file_by_id(file_id)
        assert file.status == FileStatus.SUCCESS.value
        assert file.message_id == 999

    async def test_update_status_nonexistent_file(self):
        """Fail gracefully when updating nonexistent file."""
        result = await DatabaseManager.update_status(999, FileStatus.SUCCESS)
        assert result is False

    async def test_update_status_transitions(self):
        """Test valid status transitions."""
        await DatabaseManager.add_file("/test.mp3", "hash")
        file_id = (await DatabaseManager.get_all_files())[0].id
        
        # PENDING -> UPLOADING
        await DatabaseManager.update_status(file_id, FileStatus.UPLOADING)
        assert (await DatabaseManager.get_file_by_id(file_id)).status == FileStatus.UPLOADING.value
        
        # UPLOADING -> SUCCESS
        await DatabaseManager.update_status(file_id, FileStatus.SUCCESS)
        assert (await DatabaseManager.get_file_by_id(file_id)).status == FileStatus.SUCCESS.value

    async def test_update_status_clear_message_id(self):
        """Verify message_id doesn't change when not provided."""
        await DatabaseManager.add_file("/test.mp3", "hash")
        file_id = (await DatabaseManager.get_all_files())[0].id
        
        # Set message_id
        await DatabaseManager.update_status(file_id, FileStatus.SUCCESS, message_id=123)
        
        # Update status without message_id
        await DatabaseManager.update_status(file_id, FileStatus.FAILED)
        
        # message_id should still be 123
        file = await DatabaseManager.get_file_by_id(file_id)
        assert file.message_id == 123


# --- bulk_update_status() Tests ---
class TestBulkUpdateStatus:
    """Test suite for DatabaseManager.bulk_update_status()"""

    async def test_bulk_update_multiple_files(self):
        """Update status for multiple files in one operation."""
        for i in range(5):
            await DatabaseManager.add_file(f"/file{i}.mp3", f"hash{i}")
        
        files = await DatabaseManager.get_all_files()
        ids = [files[0].id, files[2].id, files[4].id]
        
        updated_count = await DatabaseManager.bulk_update_status(ids, FileStatus.SUCCESS)
        
        assert updated_count == 3
        success_files = await DatabaseManager.get_files_by_status(FileStatus.SUCCESS)
        assert len(success_files) == 3

    async def test_bulk_update_empty_list(self):
        """Handle empty file_ids list gracefully."""
        result = await DatabaseManager.bulk_update_status([], FileStatus.SUCCESS)
        assert result == 0

    async def test_bulk_update_partial_nonexistent(self):
        """Bulk update with some nonexistent IDs updates only existing ones."""
        await DatabaseManager.add_file("/file1.mp3", "hash1")
        file_id = (await DatabaseManager.get_all_files())[0].id
        
        # Mix of existing and nonexistent IDs
        ids = [file_id, 999, 1000]
        
        updated_count = await DatabaseManager.bulk_update_status(ids, FileStatus.SUCCESS)
        
        # Should update only the existing file
        assert updated_count == 1


# --- clear_successful_files() Tests ---
class TestClearSuccessfulFiles:
    """Test suite for DatabaseManager.clear_successful_files()"""

    async def test_clear_successful_files_basic(self):
        """Delete all SUCCESS files from database."""
        await DatabaseManager.add_file("/file1.mp3", "h1")
        await DatabaseManager.add_file("/file2.mp3", "h2")
        
        files = await DatabaseManager.get_all_files()
        await DatabaseManager.update_status(files[0].id, FileStatus.SUCCESS)
        
        deleted_count = await DatabaseManager.clear_successful_files()
        
        assert deleted_count == 1
        remaining = await DatabaseManager.get_all_files()
        assert len(remaining) == 1

    async def test_clear_successful_files_none(self):
        """Return 0 when there are no SUCCESS files."""
        await DatabaseManager.add_file("/file1.mp3", "h1")
        
        deleted_count = await DatabaseManager.clear_successful_files()
        
        assert deleted_count == 0
        assert len(await DatabaseManager.get_all_files()) == 1

    async def test_clear_successful_preserves_others(self):
        """Verify only SUCCESS files are deleted."""
        statuses = [FileStatus.SUCCESS, FileStatus.FAILED, FileStatus.PENDING, FileStatus.UPLOADING]
        
        for i, status in enumerate(statuses):
            await DatabaseManager.add_file(f"/file{i}.mp3", f"hash{i}")
        
        files = await DatabaseManager.get_all_files()
        for i, status in enumerate(statuses):
            await DatabaseManager.update_status(files[i].id, status)
        
        deleted_count = await DatabaseManager.clear_successful_files()
        
        assert deleted_count == 1
        remaining = await DatabaseManager.get_all_files()
        assert len(remaining) == 3


# --- delete_file() Tests ---
class TestDeleteFile:
    """Test suite for DatabaseManager.delete_file()"""

    async def test_delete_file_success(self):
        """Delete a file by ID."""
        await DatabaseManager.add_file("/test.mp3", "hash")
        file_id = (await DatabaseManager.get_all_files())[0].id
        
        result = await DatabaseManager.delete_file(file_id)
        
        assert result is True
        assert len(await DatabaseManager.get_all_files()) == 0

    async def test_delete_nonexistent_file(self):
        """Return False when deleting nonexistent file."""
        result = await DatabaseManager.delete_file(999)
        assert result is False

    async def test_delete_file_twice(self):
        """Fail gracefully when deleting same file twice."""
        await DatabaseManager.add_file("/test.mp3", "hash")
        file_id = (await DatabaseManager.get_all_files())[0].id
        
        assert await DatabaseManager.delete_file(file_id) is True
        assert await DatabaseManager.delete_file(file_id) is False


# --- get_statistics() Tests ---
class TestGetStatistics:
    """Test suite for DatabaseManager.get_statistics()"""

    async def test_statistics_empty_database(self):
        """Return correct counts for empty database."""
        stats = await DatabaseManager.get_statistics()
        
        assert stats["total"] == 0
        assert stats["pending"] == 0
        assert stats["uploading"] == 0
        assert stats["success"] == 0
        assert stats["failed"] == 0

    async def test_statistics_mixed_statuses(self):
        """Calculate statistics correctly with mixed statuses."""
        # Add files
        for i in range(6):
            await DatabaseManager.add_file(f"/file{i}.mp3", f"hash{i}")
        
        files = await DatabaseManager.get_all_files()
        
        # Distribute files across statuses
        await DatabaseManager.update_status(files[0].id, FileStatus.SUCCESS)
        await DatabaseManager.update_status(files[1].id, FileStatus.SUCCESS)
        await DatabaseManager.update_status(files[2].id, FileStatus.FAILED)
        await DatabaseManager.update_status(files[3].id, FileStatus.UPLOADING)
        # files[4] and files[5] remain PENDING
        
        stats = await DatabaseManager.get_statistics()
        
        assert stats["total"] == 6
        assert stats["pending"] == 2
        assert stats["uploading"] == 1
        assert stats["success"] == 2
        assert stats["failed"] == 1

    async def test_statistics_single_file(self):
        """Statistics with only one file."""
        await DatabaseManager.add_file("/test.mp3", "hash")
        
        stats = await DatabaseManager.get_statistics()
        
        assert stats["total"] == 1
        assert stats["pending"] == 1
        assert sum(stats[k] for k in ["uploading", "success", "failed"]) == 0


# --- file_exists() Tests ---
class TestFileExists:
    """Test suite for DatabaseManager.file_exists()"""

    async def test_file_exists_true(self):
        """Return True for existing file."""
        filepath = "/home/user/music.mp3"
        await DatabaseManager.add_file(filepath, "hash")
        
        result = await DatabaseManager.file_exists(filepath)
        
        assert result is True

    async def test_file_exists_false(self):
        """Return False for nonexistent file."""
        result = await DatabaseManager.file_exists("/nonexistent/path.mp3")
        assert result is False

    async def test_file_exists_case_sensitive(self):
        """File existence check is case-sensitive."""
        await DatabaseManager.add_file("/Path/File.mp3", "hash")
        
        # Different case should be different file
        assert await DatabaseManager.file_exists("/path/file.mp3") is False
        assert await DatabaseManager.file_exists("/Path/File.mp3") is True

    async def test_file_exists_after_deletion(self):
        """Return False for file after deletion."""
        filepath = "/test.mp3"
        await DatabaseManager.add_file(filepath, "hash")
        file_id = (await DatabaseManager.get_all_files())[0].id
        
        assert await DatabaseManager.file_exists(filepath) is True
        
        await DatabaseManager.delete_file(file_id)
        
        assert await DatabaseManager.file_exists(filepath) is False


# --- Integration Tests ---
class TestIntegration:
    """Integration tests covering realistic workflows."""

    async def test_complete_file_lifecycle(self):
        """Test complete lifecycle: add -> get -> update -> delete."""
        # Add file
        filepath = "/home/user/demo.mp3"
        assert await DatabaseManager.add_file(filepath, "hash123") is True
        
        # Get file
        files = await DatabaseManager.get_files_by_status(FileStatus.PENDING)
        assert len(files) == 1
        file_id = files[0].id
        
        # Update status with message_id
        assert await DatabaseManager.update_status(file_id, FileStatus.SUCCESS, message_id=555) is True
        
        # Verify update
        file = await DatabaseManager.get_file_by_id(file_id)
        assert file.status == FileStatus.SUCCESS.value
        assert file.message_id == 555
        
        # Delete file
        assert await DatabaseManager.delete_file(file_id) is True
        assert await DatabaseManager.get_file_by_id(file_id) is None

    async def test_batch_processing_workflow(self):
        """Simulate real workflow: add multiple -> bulk update -> clear."""
        # Simulate adding queue of files
        for i in range(10):
            await DatabaseManager.add_file(f"/queue/file{i}.mp3", f"hash{i}")
        
        # Get pending files for processing
        pending = await DatabaseManager.get_files_by_status(FileStatus.PENDING)
        pending_ids = [f.id for f in pending]
        
        # Mark as uploading
        await DatabaseManager.bulk_update_status(pending_ids[:5], FileStatus.UPLOADING)
        
        # Simulate some succeed, some fail
        uploading = await DatabaseManager.get_files_by_status(FileStatus.UPLOADING)
        for i, file in enumerate(uploading):
            if i < 3:
                await DatabaseManager.update_status(file.id, FileStatus.SUCCESS, message_id=1000+i)
            else:
                await DatabaseManager.update_status(file.id, FileStatus.FAILED)
        
        # Check statistics
        stats = await DatabaseManager.get_statistics()
        assert stats["pending"] == 5
        assert stats["uploading"] == 0
        assert stats["success"] == 3
        assert stats["failed"] == 2
        
        # Clear successful files
        cleared = await DatabaseManager.clear_successful_files()
        assert cleared == 3
        
        stats = await DatabaseManager.get_statistics()
        assert stats["total"] == 7