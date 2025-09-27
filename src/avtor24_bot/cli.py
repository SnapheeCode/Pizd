from __future__ import annotations

import asyncio
import logging
from pathlib import Path
import typer
from rich.console import Console
from rich.table import Table

from .config import AccountConfig, ConfigRepository
from .scheduler import FollowUpScheduler
from .state import StateRepository
from .worker import AccountWorker

app = typer.Typer(help="Avtor24 autobidder")
console = Console()


def configure_logging(verbose: bool) -> None:
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
    )


@app.command()
def list_accounts(config_dir: Path = typer.Argument(Path("./configs"))) -> None:
    repo = ConfigRepository(config_dir)
    table = Table(title="Аккаунты")
    table.add_column("Файл")
    table.add_column("Логин")
    for config in repo.list_configs():
        table.add_row(config.path.name, config.login)
    console.print(table)


@app.command()
def run(
    config_dir: Path = typer.Argument(Path("./configs")),
    state_path: Path = typer.Option(Path("./state.json"), help="Путь к файлу состояния"),
    verbose: bool = typer.Option(False, "--verbose", "-v"),
) -> None:
    configure_logging(verbose)
    repo = ConfigRepository(config_dir)
    configs = list(repo.list_configs())
    if not configs:
        console.print("[red]Нет доступных конфигов[/red]")
        raise typer.Exit(code=1)

    async def runner() -> None:
        loop = asyncio.get_running_loop()
        scheduler = FollowUpScheduler(loop=loop)
        state_repo = StateRepository(state_path)
        workers = [AccountWorker(config, state_repo=state_repo, scheduler=scheduler) for config in configs]
        await asyncio.gather(*(worker.run() for worker in workers))

    try:
        asyncio.run(runner())
    except KeyboardInterrupt:
        console.print("[yellow]Остановка по запросу пользователя[/yellow]")


if __name__ == "__main__":  # pragma: no cover
    app()
