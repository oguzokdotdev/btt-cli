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

from btt.commands.config import load_config
from btt.core.uploader import TelegramUploader
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
    strict: bool = typer.Option(False, "--strict", help="Abort entire session on first failed file."),
    no_signature: bool = typer.Option(
        False, "--no-signature", help="Skip the summary message sent to Telegram after upload."
    ),
):
    """Upload pending files from the index to Telegram."""
    if ctx.invoked_subcommand is not None:
        return
    asyncio.run(_upload_logic(chat_id, mode, strict, no_signature))


async def _upload_logic(chat_id: Optional[int], mode: str, strict: bool, no_signature: bool):
    # -- Config ------------------------------------------------------------------
    config = load_config()
    if not config or not config.get("api_id") or not config.get("api_hash"):
        console.print("[red]Missing configuration. Run 'btt config set' first.[/red]")
        raise typer.Exit(code=1)

    if chat_id is None:
        chat_id = config.get("chat_id")
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

    async with Client(
        str(SESSION_FILE),
        api_id=config["api_id"],
        api_hash=config["api_hash"],
    ) as tg_client:
        uploader = TelegramUploader(tg_client)
        chat_title = await uploader.get_chat_title(chat_id)

        console.print(
            f"\n[bold]{len(files)} file(s)[/bold] will be uploaded to "
            f"[bold cyan]'{chat_title}'[/bold cyan]  •  Mode: {mode_label}"
        )
        console.print("[dim]Run 'btt status --list' to review the queue.[/dim]\n")

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

            for file_data in files:
                filename = os.path.basename(file_data.filepath)
                file_size = (
                    os.path.getsize(file_data.filepath)
                    if os.path.exists(file_data.filepath)
                    else 0
                )
                file_task: TaskID = progress.add_task(filename, total=max(file_size, 1))

                async def _progress_cb(current: int, total: int, ftask: TaskID) -> None:
                    progress.update(ftask, completed=current)

                def _on_flood_wait(seconds: int) -> None:
                    progress.console.print(
                        f"[yellow]⏳  Flood limit hit. Pausing for {seconds}s...[/yellow]"
                    )

                success = await uploader.upload_file(
                    file_id=file_data.id,
                    filepath=file_data.filepath,
                    chat_id=chat_id,
                    progress=_progress_cb,
                    progress_args=(file_task,),
                    remove_after=cleanup,
                    on_flood_wait=_on_flood_wait,
                )

                progress.remove_task(file_task)

                if success:
                    successful += 1
                    total_bytes += file_size
                    progress.console.print(f"  [green]✓[/green] {filename}")
                else:
                    failed += 1
                    progress.console.print(f"  [red]✗[/red] {filename}")
                    if strict:
                        progress.console.print(
                            "[red]Strict mode enabled — stopping on first error.[/red]"
                        )
                        break

                progress.update(
                    overall_task,
                    advance=1,
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

