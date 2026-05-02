import asyncio
import hashlib
from pathlib import Path

import typer
from rich.progress import track

from btt.database.manager import DatabaseManager as db, is_db_initialized

app = typer.Typer(help="Add files to the backup index")


def get_file_hash(filepath: Path) -> str:
    """Calculates SHA-256 hash of a file. Reads in 64 KB chunks to avoid loading large media into RAM."""
    sha256_hash = hashlib.sha256()
    with open(filepath, "rb") as f:
        for byte_block in iter(lambda: f.read(65536), b""):
            sha256_hash.update(byte_block)
    return sha256_hash.hexdigest()


async def process_and_add_files(files: list[Path]) -> tuple[int, int]:
    """Asynchronously adds a list of files to the database."""
    added = 0
    skipped = 0

    for filepath in track(files, description="Indexing files..."):
        file_hash = await asyncio.to_thread(get_file_hash, filepath)
        success = await db.add_file(str(filepath.resolve()), file_hash)

        if success:
            added += 1
        else:
            skipped += 1

    return added, skipped


@app.callback(invoke_without_command=True)
def add_command(
    ctx: typer.Context,
    path: Path = typer.Argument(
        ...,
        exists=True,
        help="Path to a file or directory to backup"
    ),
):
    if ctx.invoked_subcommand is not None:
        return

    if not is_db_initialized():
        typer.secho("Database index is not created yet.", fg=typer.colors.RED)
        typer.secho("Run 'btt init' to create it.", fg=typer.colors.YELLOW)
        raise typer.Exit(code=1)

    files_to_process = []

    if path.is_file():
        files_to_process.append(path)
    elif path.is_dir():
        files_to_process.extend([p for p in path.rglob("*") if p.is_file()])

    if not files_to_process:
        typer.secho(f"No files found in '{path}'.", fg=typer.colors.YELLOW)
        raise typer.Exit()

    typer.echo(f"Found {len(files_to_process)} files. Preparing to add to index...")

    added, skipped = asyncio.run(process_and_add_files(files_to_process))

    typer.secho(
        f"✅ Done! Added: {added} | Skipped (already exist or error): {skipped}",
        fg=typer.colors.GREEN
    )