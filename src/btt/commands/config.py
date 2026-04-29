import json
import typer
from pathlib import Path
from typing import Optional
from platformdirs import user_config_path

app = typer.Typer(help="BTT-CLI configuration management")

CONFIG_DIR = user_config_path("btt", "oguzok")
CONFIG_FILE = CONFIG_DIR / "config.json"

def save_config(config_data: dict):
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    with open(CONFIG_FILE, "w") as f:
        json.dump(config_data, f, indent=4)
    typer.echo(f"Configuration saved to {CONFIG_FILE}")

def load_config() -> dict:
    if not CONFIG_FILE.exists():
        return {}
    with open(CONFIG_FILE, "r") as f:
        return json.load(f)

@app.command()
def set(
    api_id: Optional[int] = typer.Option(None, help="Telegram API ID"),
    api_hash: Optional[str] = typer.Option(None, help="Telegram API Hash"),
    chat_id: Optional[str] = typer.Option(None, help="ID of the chat for backup"),
):
    config = load_config()
    
    updates = {
        k: v for k, v in {
            "api_id": api_id,
            "api_hash": api_hash,
            "chat_id": chat_id
        }.items() if v is not None
    }
    
    if not updates:
        typer.echo("No parameters provided to update.")
        return

    config.update(updates)
    save_config(config)

@app.command()
def show():
    config = load_config()
    if not config:
        typer.echo("Configuration is not set yet.")
        return
    
    typer.echo("Current configuration:")
    for key, value in config.items():
        typer.echo(f"  {key}: {value}")