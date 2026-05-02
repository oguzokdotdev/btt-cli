import asyncio
from pathlib import Path
import typer
from rich.console import Console
from rich.table import Table
from rich import box
from platformdirs import user_config_path
from hydrogram import Client

from btt.database.manager import DatabaseManager as db, is_db_initialized
from btt.database.models import FileStatus
from btt.commands.config import load_config

app = typer.Typer(help="Show backup status and statistics")
console = Console()

CONFIG_DIR = Path(user_config_path("btt", "oguzok"))

STATUS_STYLES = {
    FileStatus.PENDING: "yellow",
    FileStatus.UPLOADING: "blue",
    FileStatus.SUCCESS: "green",
    FileStatus.FAILED: "red",
}


async def get_status_data(is_authorized: bool, session_path: str, api_id: str, api_hash: str, chat_id: str):
    """Fetches DB statistics, account name and target chat title."""
    stats = await db.get_statistics()
    first_name = None
    chat_title = None

    if is_authorized and api_id and api_hash:
        try:
            session_name = session_path.replace(".session", "")
            async with Client(session_name, api_id=api_id, api_hash=api_hash) as tg_client:
                me = await tg_client.get_me()
                first_name = me.first_name

                if chat_id:
                    try:
                        try:
                            target_chat = int(chat_id)
                        except ValueError:
                            target_chat = chat_id

                        chat = await tg_client.get_chat(target_chat)
                        chat_title = chat.title or chat.first_name or chat.username or "Private Chat"
                    except Exception:
                        pass

        except Exception:
            pass

    return stats, first_name, chat_title


async def get_all_files_data():
    """Fetches all files from the database."""
    return await db.get_all_files()


@app.callback(invoke_without_command=True)
def status_command(
    ctx: typer.Context,
    list_files: bool = typer.Option(False, "--list", "-l", help="Show all indexed files"),
):
    if ctx.invoked_subcommand is not None:
        return

    if not is_db_initialized():
        typer.secho("Database index is not created yet. Run 'btt init'.", fg=typer.colors.RED)
        raise typer.Exit(code=1)

    config = load_config()
    chat_id = config.get("chat.id") or config.get("chat_id")
    api_id = config.get("api.id") or config.get("api_id")
    api_hash = config.get("api.hash") or config.get("api_hash")

    session_file = CONFIG_DIR / "btt.session"
    is_authorized = session_file.exists()

    with console.status("[bold cyan]Fetching status data...", spinner="dots"):
        stats, first_name, chat_title = asyncio.run(
            get_status_data(is_authorized, str(session_file), api_id, api_hash, chat_id)
        )

    if "error" in stats:
        typer.secho(f"Error getting statistics: {stats['error']}", fg=typer.colors.RED)
        raise typer.Exit(code=1)

    if is_authorized and first_name:
        auth_text = f"[bold green]Authorized[/bold green] (as {first_name})"
    elif is_authorized:
        auth_text = "[bold green]Authorized[/bold green] [yellow](Network issue)[/yellow]"
    else:
        auth_text = "[bold red]Not Authorized (Run 'btt auth')[/bold red]"

    if chat_id:
        chat_display = f"[magenta]{chat_title} ({chat_id})[/magenta]" if chat_title else f"[magenta]{chat_id}[/magenta]"
    else:
        chat_display = "[yellow]Not set[/yellow]"

    if not list_files:
        tg_table = Table(title="Telegram Configuration", box=box.ROUNDED, show_header=False)
        tg_table.add_column("Key", style="cyan")
        tg_table.add_column("Value")
        tg_table.add_row("Account Status", auth_text)
        tg_table.add_row("Target Chat", chat_display)

        db_table = Table(title="Backup Index Status", box=box.ROUNDED)
        db_table.add_column("Metric", style="cyan")
        db_table.add_column("Count", style="magenta", justify="right")
        db_table.add_row("Total files in index", str(stats.get("total", 0)))
        db_table.add_row("Pending upload", str(stats.get("pending", 0)), style="yellow")
        db_table.add_row("Currently uploading", str(stats.get("uploading", 0)), style="blue")
        db_table.add_row("Successfully uploaded", str(stats.get("success", 0)), style="green")
        db_table.add_row("Failed", str(stats.get("failed", 0)), style="red")

        console.print(tg_table)
        console.print(db_table)

        if stats.get("pending", 0) > 0:
            typer.echo(f"\nReady to upload {stats['pending']} files. Run 'btt upload' to start.")
        else:
            typer.echo("\nAll files are up to date!")

    else:
        files = asyncio.run(get_all_files_data())

        if not files:
            typer.echo("No files in index.")
        else:
            files_table = Table(title=f"Indexed Files ({len(files)} total)", box=box.ROUNDED)
            files_table.add_column("ID", style="dim", justify="right")
            files_table.add_column("Path")
            files_table.add_column("Status", justify="center")

            for file in files:
                status_enum = FileStatus(file.status)
                style = STATUS_STYLES.get(status_enum, "")
                files_table.add_row(
                    str(file.id),
                    file.filepath,
                    f"[{style}]{status_enum.name}[/{style}]",
                )

            console.print(files_table)