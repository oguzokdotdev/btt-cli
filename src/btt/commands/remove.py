import asyncio
from pathlib import Path

import typer
from rich.progress import track

from btt.database.manager import DatabaseManager as db, is_db_initialized

app = typer.Typer(help="Remove files from the backup index")


async def process_and_remove_files(files: list[Path]) -> tuple[int, int]:
    """Asynchronously removes a list of files from the database."""
    removed = 0
    not_found = 0

    for filepath in track(files, description="Removing files from index..."):
        success = await db.delete_by_filepath(str(filepath.resolve()))

        if success:
            removed += 1
        else:
            not_found += 1

    return removed, not_found


@app.callback(invoke_without_command=True)
def remove_command(
    ctx: typer.Context,
    path: Path = typer.Argument(
        ...,
        help="Path to a file or directory to remove from backup index"
    ),
):
    if ctx.invoked_subcommand is not None:
        return

    if not is_db_initialized():
        typer.secho("Database index is not created yet.", fg=typer.colors.RED)
        typer.secho("Run 'btt init' to create it.", fg=typer.colors.YELLOW)
        raise typer.Exit(code=1)

    files_to_process = []

    if path.is_dir():
        files_to_process.extend([p for p in path.rglob("*") if p.is_file()])
    else:
        files_to_process.append(path)

    if not files_to_process:
        typer.secho(f"No files targeted for '{path}'.", fg=typer.colors.YELLOW)
        raise typer.Exit()

    typer.echo(f"Found {len(files_to_process)} target paths. Preparing to remove from index...")

    removed, not_found = asyncio.run(process_and_remove_files(files_to_process))

    typer.secho(
        f"✅ Done! Removed: {removed} | Not found in index: {not_found}",
        fg=typer.colors.GREEN
    )