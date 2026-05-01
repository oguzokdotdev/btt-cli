import json
import typer
from pathlib import Path
from typing import Optional
from platformdirs import user_config_path

app = typer.Typer(help="Configuration management")

CONFIG_DIR = user_config_path("btt", "oguzok")
CONFIG_FILE = CONFIG_DIR / "config.json"

def save_config(config_data: dict):
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    with open(CONFIG_FILE, "w") as f:
        json.dump(config_data, f, indent=4)

def load_config() -> dict:
    if not CONFIG_FILE.exists():
        return {}
    with open(CONFIG_FILE, "r") as f:
        return json.load(f)

@app.callback(invoke_without_command=True)
def main(
    ctx: typer.Context,
    key: Optional[str] = typer.Argument(None, help="Config key (e.g., api.id, api.hash, chat.id)"),
    value: Optional[str] = typer.Argument(None, help="Value to set"),
    show_list: bool = typer.Option(False, "--list", "-l", help="List all configuration values")
):
    
    if ctx.invoked_subcommand is not None:
        return

    config = load_config()

    if show_list:
        if not config:
            typer.echo("Configuration is not set yet.")
            return
        for k, v in config.items():
            typer.echo(f"{k.replace('_', '.')}={v}")
        return

    if not key:
        typer.echo(ctx.get_help())
        return

    internal_key = key.replace(".", "_")

    if key and value is None:
        if internal_key in config:
            typer.echo(config[internal_key])
        return

    if key and value is not None:
        if internal_key == "api_id":
            try:
                value = int(value)
            except ValueError:
                typer.secho(f"Error: {key} must be an integer.", fg=typer.colors.RED)
                raise typer.Exit(code=1)
        
        config[internal_key] = value
        save_config(config)