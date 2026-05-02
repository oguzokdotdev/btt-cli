import asyncio
import typer

from btt.database.manager import init_db

app = typer.Typer(help="Initialize the database index")

@app.callback(invoke_without_command=True)
def init_command(ctx: typer.Context):
    if ctx.invoked_subcommand is not None:
        return

    try:
        asyncio.run(init_db())
        typer.secho("✅ Database initialized successfully.", fg=typer.colors.GREEN)
    except Exception as e:
        typer.secho(f"❌ Failed to initialize database: {e}", fg=typer.colors.RED)
        raise typer.Exit(code=1)