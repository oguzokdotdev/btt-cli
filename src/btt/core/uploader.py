import asyncio
import logging
import os
from typing import Callable, Optional

from hydrogram import Client
from hydrogram.errors import FloodWait

from btt.database.manager import DatabaseManager as db
from btt.database.models import FileStatus

logger = logging.getLogger(__name__)

MAX_RETRIES = 5


class TelegramUploader:
    """Handles file upload logic with FloodWait recovery and progress reporting."""

    def __init__(self, client: Client):
        self.client = client

    async def upload_file(
        self,
        file_id: int,
        filepath: str,
        chat_id: int,
        progress: Optional[Callable] = None,
        progress_args: tuple = (),
        remove_after: bool = False,
        on_flood_wait: Optional[Callable[[int], None]] = None,
    ) -> bool:
        """
        Uploads a single file to Telegram with automatic FloodWait retry.

        Args:
            file_id: Database record ID.
            filepath: Absolute path to the file on disk.
            chat_id: Target Telegram chat ID.
            progress: Async callback — signature: (current, total, *progress_args).
            progress_args: Extra arguments forwarded to the progress callback.
            remove_after: Delete file from disk after successful upload (cleanup mode).
            on_flood_wait: Sync callback called with wait_seconds when FloodWait hits.

        Returns:
            True on success, False on failure.
        """
        if not os.path.exists(filepath):
            logger.error(f"File not found on disk: {filepath}")
            await db.update_status(file_id, FileStatus.FAILED)
            return False

        await db.update_status(file_id, FileStatus.UPLOADING)

        for attempt in range(1, MAX_RETRIES + 1):
            try:
                msg = await self.client.send_document(
                    chat_id=chat_id,
                    document=filepath,
                    progress=progress,
                    progress_args=progress_args,
                )

                await db.update_status(file_id, FileStatus.SUCCESS, message_id=msg.id)

                if remove_after:
                    os.remove(filepath)
                    logger.info(f"Removed from disk after upload: {filepath}")

                return True

            except FloodWait as e:
                logger.warning(
                    f"FloodWait on attempt {attempt}/{MAX_RETRIES}: sleeping {e.value}s"
                )
                if on_flood_wait:
                    on_flood_wait(e.value)
                await asyncio.sleep(e.value)
                continue

            except Exception as e:
                logger.error(
                    f"Upload error for {filepath} (attempt {attempt}/{MAX_RETRIES}): {e}"
                )
                if attempt == MAX_RETRIES:
                    await db.update_status(file_id, FileStatus.FAILED)
                    return False
                await asyncio.sleep(2 ** attempt)

        await db.update_status(file_id, FileStatus.FAILED)
        return False

    async def get_chat_title(self, chat_id: int) -> str:
        """Fetches the display name of the target chat for pre-flight confirmation."""
        try:
            chat = await self.client.get_chat(chat_id)
            return chat.title or chat.first_name or str(chat_id)
        except Exception as e:
            logger.warning(f"Could not fetch chat title for {chat_id}: {e}")
            return str(chat_id)

