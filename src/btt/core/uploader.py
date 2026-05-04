import asyncio
import logging
import os
from typing import Callable, Optional

from hydrogram import Client
from hydrogram.errors import FloodWait
from hydrogram.types import InputMediaDocument

from btt.database.manager import DatabaseManager as db
from btt.database.models import FileStatus

logger = logging.getLogger(__name__)

MAX_RETRIES = 5
GROUP_SIZE = 10


class TelegramUploader:
    """Handles file upload logic with FloodWait recovery and progress reporting."""

    def __init__(self, client: Client):
        self.client = client

    async def upload_group(
        self,
        files: list[tuple[int, str]],  # [(file_id, filepath), ...]
        chat_id: int,
        remove_after: bool = False,
        on_flood_wait: Optional[Callable[[int], None]] = None,
        on_file_progress: Optional[Callable[[str, int, int], None]] = None,
    ) -> tuple[list[int], list[int]]:
        """
        Uploads a group of up to 10 files as a media group.

        Args:
            files: List of (db_id, filepath) tuples.
            chat_id: Target Telegram chat ID.
            remove_after: Delete files from disk after successful upload.
            on_flood_wait: Called with wait_seconds on FloodWait.
            on_file_progress: Called with (filepath, current_bytes, total_bytes).

        Returns:
            (succeeded_ids, failed_ids) — lists of DB file IDs.
        """
        valid = [(fid, fp) for fid, fp in files if os.path.exists(fp)]
        missing = [(fid, fp) for fid, fp in files if not os.path.exists(fp)]

        for fid, fp in missing:
            logger.error(f"File not found on disk: {fp}")
            await db.update_status(fid, FileStatus.FAILED)

        if not valid:
            return [], [fid for fid, _ in missing]

        file_ids = [fid for fid, _ in valid]
        filepaths = [fp for _, fp in valid]

        await db.bulk_update_status(file_ids, FileStatus.UPLOADING)

        # Если один файл — send_document с прогрессом
        if len(valid) == 1:
            fid, fp = valid[0]
            return await self._upload_single(fid, fp, chat_id, remove_after, on_flood_wait, on_file_progress)

        for attempt in range(1, MAX_RETRIES + 1):
            try:
                # Прогресс только для первого файла в группе (Telegram API ограничение)
                first_fp = filepaths[0]

                async def _progress(current: int, total: int) -> None:
                    if on_file_progress:
                        on_file_progress(first_fp, current, total)

                media = [InputMediaDocument(media=filepaths[0])]
                for fp in filepaths[1:]:
                    media.append(InputMediaDocument(media=fp))

                # Первый файл с прогрессом отдельно не получится в media_group,
                # поэтому трекаем размер вручную перед отправкой
                messages = await self.client.send_media_group(
                    chat_id=chat_id,
                    media=media,
                )

                succeeded = []
                for i, (fid, _) in enumerate(valid):
                    msg_id = messages[i].id if i < len(messages) else messages[0].id
                    await db.update_status(fid, FileStatus.SUCCESS, message_id=msg_id)
                    succeeded.append(fid)

                if remove_after:
                    for fp in filepaths:
                        try:
                            os.remove(fp)
                            logger.info(f"Removed from disk: {fp}")
                        except OSError as e:
                            logger.warning(f"Could not remove {fp}: {e}")

                return succeeded, [fid for fid, _ in missing]

            except FloodWait as e:
                logger.warning(f"FloodWait on attempt {attempt}/{MAX_RETRIES}: sleeping {e.value}s")
                if on_flood_wait:
                    on_flood_wait(e.value)
                await asyncio.sleep(e.value)
                continue

            except Exception as e:
                logger.error(f"Group upload error (attempt {attempt}/{MAX_RETRIES}): {e}")
                if attempt == MAX_RETRIES:
                    await db.bulk_update_status(file_ids, FileStatus.FAILED)
                    return [], file_ids + [fid for fid, _ in missing]
                await asyncio.sleep(2 ** attempt)

        await db.bulk_update_status(file_ids, FileStatus.FAILED)
        return [], file_ids + [fid for fid, _ in missing]

    async def _upload_single(
        self,
        file_id: int,
        filepath: str,
        chat_id: int,
        remove_after: bool = False,
        on_flood_wait: Optional[Callable[[int], None]] = None,
        on_file_progress: Optional[Callable[[str, int, int], None]] = None,
    ) -> tuple[list[int], list[int]]:
        """Single-file upload with byte-level progress."""

        for attempt in range(1, MAX_RETRIES + 1):
            try:
                async def _progress(current: int, total: int) -> None:
                    if on_file_progress:
                        on_file_progress(filepath, current, total)

                msg = await self.client.send_document(
                    chat_id=chat_id,
                    document=filepath,
                    progress=_progress,
                )

                await db.update_status(file_id, FileStatus.SUCCESS, message_id=msg.id)

                if remove_after:
                    os.remove(filepath)
                    logger.info(f"Removed from disk: {filepath}")

                return [file_id], []

            except FloodWait as e:
                logger.warning(f"FloodWait on attempt {attempt}/{MAX_RETRIES}: sleeping {e.value}s")
                if on_flood_wait:
                    on_flood_wait(e.value)
                await asyncio.sleep(e.value)
                continue

            except Exception as e:
                logger.error(f"Upload error for {filepath} (attempt {attempt}/{MAX_RETRIES}): {e}")
                if attempt == MAX_RETRIES:
                    await db.update_status(file_id, FileStatus.FAILED)
                    return [], [file_id]
                await asyncio.sleep(2 ** attempt)

        await db.update_status(file_id, FileStatus.FAILED)
        return [], [file_id]

    async def get_chat_title(self, chat_id: int) -> str:
        """Fetches the display name of the target chat for pre-flight confirmation."""
        try:
            chat = await self.client.get_chat(chat_id)
            return chat.title or chat.first_name or str(chat_id)
        except Exception as e:
            logger.warning(f"Could not fetch chat title for {chat_id}: {e}")
            return str(chat_id)