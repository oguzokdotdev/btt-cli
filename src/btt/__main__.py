import typer
from btt.commands import config
from btt.commands import auth
from btt.commands import init
from btt.commands import add
from btt.commands import status
from btt.commands import remove
from btt.commands import upload


app = typer.Typer(help="Backup Tool for Telegram", add_completion=False)
app.add_typer(config.app, name="config")
app.add_typer(auth.app, name="auth")
app.add_typer(init.app, name="init")
app.add_typer(add.app, name="add")
app.add_typer(status.app, name="status")
app.add_typer(remove.app, name="remove")
app.add_typer(remove.app, name="rm", hidden=True)
app.add_typer(upload.app, name="upload")

if __name__ == "__main__":
    app()
