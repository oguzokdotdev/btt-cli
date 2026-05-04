import asyncio
import logging
import os
import time
from typing import Optional

import typer
from platformdirs import user_config_path
from rich.console import Console
from rich.progress import BarColumn, DownloadColumn, Progress, SpinnerColumn, TaskID, TextColumn

from hydrogram import Client

from btt.commands.config import load_config, get_nested
from btt.core.uploader import TelegramUploader, GROUP_SIZE
from btt.database.manager import DatabaseManager as db
from btt.database.models import FileStatus

logger = logging.getLogger(__name__)

app = typer.Typer()
console = Console()

CONFIG_DIR = user_config_path("btt", "oguzok")
SESSION_FILE = CONFIG_DIR / "btt"


@app.callback(invoke_without_command=True)
def upload(
    ctx: typer.Context,
    chat_id: Optional[int] = typer.Option(
        None, "--chat-id", "-c", help="Target Telegram Chat ID (default: from config)"
    ),
    mode: str = typer.Option(
        "backup", "--mode", "-m", help="'backup' — upload only. 'cleanup' — upload then delete from disk."
    ),
    strict: bool = typer.Option(False, "--strict", "-s", help="Abort entire session on first failed file."),
    no_signature: bool = typer.Option(
        False, "--no-signature", "-ns", help="Skip the summary message sent to Telegram after upload."
    ),
):
    """Upload pending files from the index to Telegram."""
    if ctx.invoked_subcommand is not None:
        return
    asyncio.run(_upload_logic(chat_id, mode, strict, no_signature))


async def _upload_logic(chat_id: Optional[int], mode: str, strict: bool, no_signature: bool):
    # -- Config ------------------------------------------------------------------
    config = load_config()
    api_id = get_nested(config, "api.id")
    api_hash = get_nested(config, "api.hash")

    if not config or not api_id or not api_hash:
        console.print("[red]Missing configuration. Run 'btt config set' first.[/red]")
        raise typer.Exit(code=1)

    if chat_id is None:
        chat_id = get_nested(config, "chat.id")
    if not chat_id:
        console.print("[red]No chat_id provided. Pass --chat-id or set it via 'btt config set'.[/red]")
        raise typer.Exit(code=1)

    # -- Stage 0: Recovery -------------------------------------------------------
    recovered = await db.recover_stuck_uploads()
    if recovered > 0:
        console.print(f"[yellow]⚠  Recovered {recovered} stuck file(s) from a previous session.[/yellow]")

    # -- Stage 1: Pre-flight -----------------------------------------------------
    files = await db.get_files_by_status(FileStatus.PENDING)
    if not files:
        console.print("[dim]Nothing to upload. Index has no PENDING files.[/dim]")
        return

    cleanup = mode == "cleanup"
    mode_label = "[red bold]CLEANUP[/red bold]" if cleanup else "[green bold]BACKUP[/green bold]"

    # Разбиваем на чанки по GROUP_SIZE
    chunks = [files[i:i + GROUP_SIZE] for i in range(0, len(files), GROUP_SIZE)]

    async with Client(
        str(SESSION_FILE),
        api_id=api_id,
        api_hash=api_hash,
    ) as tg_client:
        uploader = TelegramUploader(tg_client)
        chat_title = await uploader.get_chat_title(chat_id)

        console.print(
            f"\n[bold]{len(files)} file(s)[/bold] will be uploaded to "
            f"[bold cyan]'{chat_title}'[/bold cyan]  •  Mode: {mode_label}"
        )
        console.print(f"[dim]{len(chunks)} group(s) of up to {GROUP_SIZE} files each.[/dim]\n")

        if not typer.confirm("Proceed?", default=False):
            return

        # -- Stage 2: Upload loop ------------------------------------------------
        successful = 0
        failed = 0
        total_bytes = 0
        start_time = time.monotonic()

        with Progress(
            SpinnerColumn(),
            TextColumn("[bold]{task.description}"),
            BarColumn(),
            DownloadColumn(),
            console=console,
        ) as progress:
            overall_task = progress.add_task(f"[0/{len(files)}] Uploading...", total=len(files))

            def _on_flood_wait(seconds: int) -> None:
                progress.console.print(
                    f"[yellow]⏳  Flood limit hit. Pausing for {seconds}s...[/yellow]"
                )

            for chunk in chunks:
                chunk_pairs = [(f.id, f.filepath) for f in chunk]

                # Прогресс-таск для текущего активного файла в группе
                first_filepath = chunk[0].filepath
                first_size = os.path.getsize(first_filepath) if os.path.exists(first_filepath) else 1
                file_task: TaskID = progress.add_task(
                    os.path.basename(first_filepath),
                    total=max(first_size, 1),
                )

                def _on_file_progress(filepath: str, current: int, total: int) -> None:
                    progress.update(
                        file_task,
                        completed=current,
                        total=max(total, 1),
                        description=os.path.basename(filepath),
                    )

                succeeded_ids, failed_ids = await uploader.upload_group(
                    files=chunk_pairs,
                    chat_id=chat_id,
                    remove_after=cleanup,
                    on_flood_wait=_on_flood_wait,
                    on_file_progress=_on_file_progress,
                )

                progress.remove_task(file_task)

                # Считаем байты успешно загруженных
                for f in chunk:
                    if f.id in succeeded_ids:
                        if os.path.exists(f.filepath):
                            total_bytes += os.path.getsize(f.filepath)

                successful += len(succeeded_ids)
                failed += len(failed_ids)

                # Логируем результат группы
                if succeeded_ids:
                    names = ", ".join(os.path.basename(f.filepath) for f in chunk if f.id in succeeded_ids)
                    progress.console.print(f"  [green]✓[/green] {names}")
                if failed_ids:
                    names = ", ".join(os.path.basename(f.filepath) for f in chunk if f.id in failed_ids)
                    progress.console.print(f"  [red]✗[/red] {names}")
                    if strict:
                        progress.console.print(
                            "[red]Strict mode enabled — stopping on first error.[/red]"
                        )
                        break

                progress.update(
                    overall_task,
                    advance=len(chunk),
                    description=f"[{successful + failed}/{len(files)}] Uploading...",
                )

        # -- Stage 3: Teardown ---------------------------------------------------
        duration = int(time.monotonic() - start_time)
        total_mb = total_bytes / (1024 * 1024)

        console.print(f"\n[bold]Upload session complete[/bold]")
        console.print(f"  Successful : [green]{successful}[/green]")
        console.print(f"  Failed     : [red]{failed}[/red]")
        console.print(f"  Duration   : {duration}s  •  Uploaded: {total_mb:.1f} MB\n")

        if not no_signature and successful > 0:
            summary = (
                f"✅ Backup completed\n"
                f"📦 {successful} file(s) uploaded ({total_mb:.1f} MB)\n"
                f"⏱ Duration: {duration}s\n"
                f"🔗 Powered by [btt-cli](https://github.com/oguzokdotdev/btt-cli)"
            )
            try:
                await tg_client.send_message(chat_id, summary)
            except Exception as e:
                logger.warning(f"Could not send summary message: {e}")