import typer
import asyncio
from pathlib import Path
from platformdirs import user_config_path
from hydrogram import Client

from btt.commands.config import load_config

app = typer.Typer(help="Hydrogram Authorization")

CONFIG_DIR = user_config_path("btt", "oguzok")
CONFIG_DIR.mkdir(parents=True, exist_ok=True)

SESSION_FILE = CONFIG_DIR / "btt.session"

@app.callback(invoke_without_command=True)
def auth_main(ctx: typer.Context):
    """Start Telegram authorization"""
    
    if ctx.invoked_subcommand is not None:
        return
    
    config_data = load_config()
    
    if not config_data:
        typer.secho("Configuration is not set yet. Please run 'btt config set' first.", fg=typer.colors.RED)
        raise typer.Exit(code=1)
        
    api_id = config_data.get("api_id")
    api_hash = config_data.get("api_hash")
    
    if not api_id or not api_hash:
        typer.secho("Missing 'api_id' or 'api_hash' in configuration.", fg=typer.colors.RED)
        typer.secho("Please set them using: btt config set --api-id <ID> --api-hash <HASH>", fg=typer.colors.YELLOW)
        raise typer.Exit(code=1)

    async def run_auth():
        async with Client(str(SESSION_FILE), api_id=api_id, api_hash=api_hash) as tg_client:
            me = await tg_client.get_me()
            typer.secho(f"Logged in successfully as {me.first_name}!", fg=typer.colors.GREEN)

    asyncio.run(run_auth())