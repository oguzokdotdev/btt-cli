import typer
from btt.commands import config
from btt.commands import auth
from btt.commands import init
from btt.commands import add
from btt.commands import status


app = typer.Typer(help="Backup Tool for Telegram", add_completion=False)
app.add_typer(config.app, name="config")
app.add_typer(auth.app, name="auth")
app.add_typer(init.app, name="init")
app.add_typer(add.app, name="add")
app.add_typer(status.app, name="status")

if __name__ == "__main__":
    app()