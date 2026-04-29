import typer
from btt.commands import config


app = typer.Typer(help="Backup Tool for Telegram")
app.add_typer(config.app, name="config")

if __name__ == "__main__":
    app()