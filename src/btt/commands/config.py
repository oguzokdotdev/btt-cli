import json
import typer
from pathlib import Path
from typing import Optional
from platformdirs import user_config_path

app = typer.Typer(help="Configuration management")

CONFIG_DIR = Path(user_config_path("btt", "oguzok"))
CONFIG_FILE = CONFIG_DIR / "config.json"

DEFAULT_CONFIG = {
    "api": {
        "id": None,
        "hash": None,
    },
    "chat": {
        "id": None,
    }
}


def save_config(config_data: dict):
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    with open(CONFIG_FILE, "w") as f:
        json.dump(config_data, f, indent=4)


def merge_defaults(user_config: dict, default_config: dict):
    result = default_config.copy()
    for k, v in user_config.items():
        if isinstance(v, dict) and k in result:
            result[k] = merge_defaults(v, result[k])
        else:
            result[k] = v
    return result


def load_config() -> dict:
    if not CONFIG_FILE.exists():
        return DEFAULT_CONFIG.copy()

    with open(CONFIG_FILE, "r") as f:
        user_config = json.load(f)

    return merge_defaults(user_config, DEFAULT_CONFIG)


def set_nested(config: dict, key: str, value):
    keys = key.split(".")
    d = config
    for k in keys[:-1]:
        d = d.setdefault(k, {})
    d[keys[-1]] = value


def get_nested(config: dict, key: str):
    keys = key.split(".")
    d = config
    for k in keys:
        if k not in d:
            return None
        d = d[k]
    return d


def flatten(config: dict, parent_key=""):
    items = {}
    for k, v in config.items():
        new_key = f"{parent_key}.{k}" if parent_key else k
        if isinstance(v, dict):
            items.update(flatten(v, new_key))
        else:
            items[new_key] = v
    return items


@app.callback(invoke_without_command=True)
def main(
    ctx: typer.Context,
    key: Optional[str] = typer.Argument(None, help="Config key (e.g., api.id, api.hash, chat.id)"),
    value: Optional[str] = typer.Argument(None, help="Value to set"),
    show_list: bool = typer.Option(False, "--list", "-l", help="List all configuration values"),
):
    """
    Manage configuration.

    Examples:

    \b
    btt config api.id 12345
    btt config api.hash abc123
    btt config chat.id 777
    btt config api.id
    btt config --list
    """

    if ctx.invoked_subcommand is not None:
        return

    config = load_config()

    if show_list:
        flat = flatten(config)
        for k, v in flat.items():
            value = v if v is not None else "<not set>"
            typer.echo(f"{k}={value}")
        return

    if not key:
        typer.echo(ctx.get_help())
        return

    if key and value is None:
        result = get_nested(config, key)
        if result is not None:
            typer.echo(result)
        else:
            typer.secho(f"Key '{key}' not found.", fg=typer.colors.RED)
        return

    if key and value is not None:
        if key == "api.id":
            try:
                value = int(value)
            except ValueError:
                typer.secho(f"Error: {key} must be an integer.", fg=typer.colors.RED)
                raise typer.Exit(code=1)

        set_nested(config, key, value)
        save_config(config)
        typer.echo(f"Set {key}={value}")
