import asyncio
import logging
from pathlib import Path
from typing import Optional
from platformdirs import user_config_path
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from sqlalchemy import select, update, delete, func
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from btt.database.models import Base, File, FileStatus

logger = logging.getLogger(__name__)

CONFIG_DIR = Path(user_config_path("btt", "oguzok"))
CONFIG_DIR.mkdir(parents=True, exist_ok=True)
DATABASE_URL = f"sqlite+aiosqlite:///{CONFIG_DIR / 'index.db'}"

engine = create_async_engine(
    DATABASE_URL,
    echo=False,
    connect_args={"timeout": 10}
)
AsyncSessionLocal = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False
)


async def init_db():
    """Creates database tables on first run."""
    try:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        logger.info("Database initialized successfully")
    except SQLAlchemyError as e:
        logger.error(f"Failed to initialize database: {e}")
        raise

def is_db_initialized() -> bool:
    """Checks if the database file exists."""
    db_path = CONFIG_DIR / "index.db"
    return db_path.exists()

class DatabaseManager:
    """Manager for executing CRUD operations with files in the index."""

    @staticmethod
    async def add_file(filepath: str, file_hash: str) -> bool:
        """
        Adds a file to the queue.
        
        Args:
            filepath: Absolute path to the file
            file_hash: SHA256 hash of the file
            
        Returns:
            True if added, False if a file with this path already exists or on error
        """
        try:
            async with AsyncSessionLocal() as session:
                stmt = select(File).where(File.filepath == filepath)
                result = await session.execute(stmt)
                existing_file = result.scalar_one_or_none()

                if existing_file:
                    logger.debug(f"File already exists in index: {filepath}")
                    return False

                new_file = File(filepath=filepath, file_hash=file_hash, status=FileStatus.PENDING.value)
                session.add(new_file)
                await session.commit()
                logger.info(f"File added to index: {filepath}")
                return True

        except IntegrityError as e:
            logger.warning(f"Integrity error while adding file {filepath}: {e}")
            return False
        except SQLAlchemyError as e:
            logger.error(f"Database error while adding file {filepath}: {e}")
            return False
        except Exception as e:
            logger.error(f"Unexpected error while adding file {filepath}: {e}")
            return False

    @staticmethod
    async def get_files_by_status(status: FileStatus) -> list[File]:
        """
        Returns a list of files with a specific status (e.g., PENDING).
        Files are ordered by ID for consistent processing.
        
        Args:
            status: FileStatus enum value
            
        Returns:
            List of File objects, empty list if none found or on error
        """
        try:
            async with AsyncSessionLocal() as session:
                stmt = (
                    select(File)
                    .where(File.status == status.value)
                    .order_by(File.id)
                )
                result = await session.execute(stmt)
                files = result.scalars().all()
                logger.debug(f"Retrieved {len(files)} files with status {status.name}")
                return files

        except SQLAlchemyError as e:
            logger.error(f"Database error while fetching files by status {status.name}: {e}")
            return []
        except Exception as e:
            logger.error(f"Unexpected error while fetching files by status: {e}")
            return []

    @staticmethod
    async def get_all_files() -> list[File]:
        """
        Returns all files in the database (for the status command).
        
        Returns:
            List of all File objects, empty list if none found or on error
        """
        try:
            async with AsyncSessionLocal() as session:
                stmt = select(File).order_by(File.id)
                result = await session.execute(stmt)
                files = result.scalars().all()
                logger.debug(f"Retrieved {len(files)} total files from database")
                return files

        except SQLAlchemyError as e:
            logger.error(f"Database error while fetching all files: {e}")
            return []
        except Exception as e:
            logger.error(f"Unexpected error while fetching all files: {e}")
            return []

    @staticmethod
    async def get_file_by_id(file_id: int) -> Optional[File]:
        """
        Retrieves a single file by ID.
        
        Args:
            file_id: The file ID
            
        Returns:
            File object if found, None otherwise
        """
        try:
            async with AsyncSessionLocal() as session:
                stmt = select(File).where(File.id == file_id)
                result = await session.execute(stmt)
                file = result.scalar_one_or_none()
                return file

        except SQLAlchemyError as e:
            logger.error(f"Database error while fetching file {file_id}: {e}")
            return None
        except Exception as e:
            logger.error(f"Unexpected error while fetching file {file_id}: {e}")
            return None

    @staticmethod
    async def update_status(
        file_id: int,
        status: FileStatus,
        message_id: Optional[int] = None
    ) -> bool:
        """
        Updates the file status. If the file is successfully uploaded,
        it also records its Telegram message_id.
        
        Args:
            file_id: The file ID to update
            status: New FileStatus
            message_id: Optional Telegram message ID (for SUCCESS status)
            
        Returns:
            True if updated successfully, False if file not found or on error
        """
        try:
            async with AsyncSessionLocal() as session:
                check_stmt = select(File).where(File.id == file_id)
                result = await session.execute(check_stmt)
                existing_file = result.scalar_one_or_none()

                if not existing_file:
                    logger.warning(f"File {file_id} not found for status update")
                    return False

                values_to_update = {"status": status.value}
                if message_id is not None:
                    values_to_update["message_id"] = message_id

                stmt = update(File).where(File.id == file_id).values(**values_to_update)
                result = await session.execute(stmt)
                await session.commit()

                if result.rowcount == 0:
                    logger.warning(f"No rows updated for file {file_id}")
                    return False

                logger.info(
                    f"File {file_id} status updated to {status.name}"
                    + (f", message_id={message_id}" if message_id else "")
                )
                return True

        except SQLAlchemyError as e:
            logger.error(f"Database error while updating file {file_id}: {e}")
            return False
        except Exception as e:
            logger.error(f"Unexpected error while updating file {file_id}: {e}")
            return False

    @staticmethod
    async def bulk_update_status(
        file_ids: list[int],
        status: FileStatus
    ) -> int:
        """
        Efficiently updates status for multiple files in one operation.
        Useful for batch processing (e.g., marking 1000 files as SUCCESS).
        
        Args:
            file_ids: List of file IDs to update
            status: New FileStatus for all files
            
        Returns:
            Number of files actually updated
        """
        if not file_ids:
            logger.warning("bulk_update_status called with empty file_ids list")
            return 0

        try:
            async with AsyncSessionLocal() as session:
                stmt = (
                    update(File)
                    .where(File.id.in_(file_ids))
                    .values(status=status.value)
                )
                result = await session.execute(stmt)
                await session.commit()

                updated_count = result.rowcount
                logger.info(f"Bulk updated {updated_count} files to status {status.name}")
                return updated_count

        except SQLAlchemyError as e:
            logger.error(f"Database error during bulk status update: {e}")
            return 0
        except Exception as e:
            logger.error(f"Unexpected error during bulk status update: {e}")
            return 0

    @staticmethod
    async def clear_successful_files() -> int:
        """
        Deletes all files with the SUCCESS status from the index.
        
        Returns:
            The number of deleted records
        """
        try:
            async with AsyncSessionLocal() as session:
                stmt = delete(File).where(File.status == FileStatus.SUCCESS.value)
                result = await session.execute(stmt)
                await session.commit()

                deleted_count = result.rowcount
                logger.info(f"Cleared {deleted_count} successful files from index")
                return deleted_count

        except SQLAlchemyError as e:
            logger.error(f"Database error while clearing successful files: {e}")
            return 0
        except Exception as e:
            logger.error(f"Unexpected error while clearing successful files: {e}")
            return 0

    @staticmethod
    async def delete_file(file_id: int) -> bool:
        """
        Deletes a single file from the index by ID.
        
        Args:
            file_id: The file ID to delete
            
        Returns:
            True if deleted successfully, False if not found or on error
        """
        try:
            async with AsyncSessionLocal() as session:
                stmt = delete(File).where(File.id == file_id)
                result = await session.execute(stmt)
                await session.commit()

                if result.rowcount == 0:
                    logger.warning(f"File {file_id} not found for deletion")
                    return False

                logger.info(f"File {file_id} deleted from index")
                return True

        except SQLAlchemyError as e:
            logger.error(f"Database error while deleting file {file_id}: {e}")
            return False
        except Exception as e:
            logger.error(f"Unexpected error while deleting file {file_id}: {e}")
            return False
    
    @staticmethod
    async def delete_by_filepath(filepath: str) -> bool:
        """
        Deletes a single file from the index by its filepath.
        
        Args:
            filepath: Absolute path to the file
            
        Returns:
            True if deleted successfully, False if not found or on error
        """
        try:
            async with AsyncSessionLocal() as session:
                stmt = delete(File).where(File.filepath == filepath)
                result = await session.execute(stmt)
                await session.commit()

                if result.rowcount == 0:
                    logger.debug(f"File {filepath} not found for deletion")
                    return False

                logger.info(f"File {filepath} deleted from index")
                return True

        except SQLAlchemyError as e:
            logger.error(f"Database error while deleting file {filepath}: {e}")
            return False
        except Exception as e:
            logger.error(f"Unexpected error while deleting file {filepath}: {e}")
            return False

    @staticmethod
    async def get_statistics() -> dict[str, int]:
        """
        Returns statistics about files in the database.
        
        Returns:
            Dictionary with counts: {
                'total': int,
                'pending': int,
                'uploading': int,
                'success': int,
                'failed': int
            }
        """
        try:
            async with AsyncSessionLocal() as session:
                total_stmt = select(func.count(File.id))
                total_result = await session.execute(total_stmt)
                total = total_result.scalar() or 0

                stats = {
                    "total": total,
                }

                for status in FileStatus:
                    count_stmt = select(func.count(File.id)).where(File.status == status.value)
                    count_result = await session.execute(count_stmt)
                    count = count_result.scalar() or 0
                    stats[status.name.lower()] = count

                logger.debug(f"Database statistics: {stats}")
                return stats

        except SQLAlchemyError as e:
            logger.error(f"Database error while getting statistics: {e}")
            return {"total": 0, "error": str(e)}
        except Exception as e:
            logger.error(f"Unexpected error while getting statistics: {e}")
            return {"total": 0, "error": str(e)}

    @staticmethod
    async def file_exists(filepath: str) -> bool:
        """
        Checks if a file already exists in the index.
        
        Args:
            filepath: Path to check
            
        Returns:
            True if file exists, False otherwise
        """
        try:
            async with AsyncSessionLocal() as session:
                stmt = select(func.count(File.id)).where(File.filepath == filepath)
                result = await session.execute(stmt)
                count = result.scalar() or 0
                return count > 0

        except SQLAlchemyError as e:
            logger.error(f"Database error while checking file existence: {e}")
            return False
        except Exception as e:
            logger.error(f"Unexpected error while checking file existence: {e}")
            return False
        
        