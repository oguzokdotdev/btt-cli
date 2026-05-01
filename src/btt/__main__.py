import typer
from btt.commands import config
from btt.commands import auth


app = typer.Typer(help="Backup Tool for Telegram", add_completion=False)
app.add_typer(config.app, name="config")
app.add_typer(auth.app, name="auth")

if __name__ == "__main__":
    app()