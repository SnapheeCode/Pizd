"""Command line helpers for Автора24 bot."""
from __future__ import annotations

import argparse
import atexit
import contextlib
import json
import logging
import signal
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, List, Mapping, Sequence

from .browser_bid import BrowserBidExecutor
from .worker import AccountWorker, Scheduler

LOGGER = logging.getLogger(__name__)
DEFAULT_PROFILES_ROOT = Path(".avtor24/profiles")


@dataclass
class AccountConfig:
    """Configuration describing how to authenticate an account."""

    name: str
    base_url: str
    cookies: Sequence[Mapping[str, object]]


def create_account_worker(
    config: AccountConfig, scheduler: Scheduler, profiles_root: Path = DEFAULT_PROFILES_ROOT
) -> AccountWorker:
    """Instantiate :class:`AccountWorker` with a dedicated browser executor."""

    profiles_root.mkdir(parents=True, exist_ok=True)
    profile_path = profiles_root / config.name
    executor = BrowserBidExecutor(
        base_url=config.base_url,
        cookies=config.cookies,
        profile_path=profile_path,
    )
    worker = AccountWorker(scheduler=scheduler, bid_executor=executor)
    atexit.register(worker.close)
    return worker


def load_cookies(path: Path) -> List[Mapping[str, object]]:
    """Load cookies from a JSON file."""

    LOGGER.debug("Loading cookies from %s", path)
    with path.open("r", encoding="utf-8") as stream:
        data = json.load(stream)
    if isinstance(data, Mapping):
        cookies = data.get("cookies", [])
    else:
        cookies = data
    if not isinstance(cookies, list):  # pragma: no cover - data validation
        raise ValueError("Cookies file must contain a list of cookies")
    return cookies


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Автора24 bidding bot")
    parser.add_argument(
        "--account",
        action="append",
        metavar="NAME=COOKIES",
        help="Account name and path to cookies JSON file (name=/path/to/cookies.json)",
    )
    parser.add_argument("--base-url", required=True, help="Base URL of the Автора24 platform")
    return parser


def parse_accounts(entries: Iterable[str], base_url: str) -> List[AccountConfig]:
    configs: List[AccountConfig] = []
    for entry in entries:
        if "=" not in entry:
            raise ValueError("--account must be in NAME=COOKIES_PATH format")
        name, cookies_path = entry.split("=", 1)
        cookies = load_cookies(Path(cookies_path))
        configs.append(AccountConfig(name=name, base_url=base_url, cookies=cookies))
    return configs


def install_shutdown_hooks(workers: Iterable[AccountWorker]) -> None:
    def _shutdown_handler(signum, frame):  # pragma: no cover - signal handler
        LOGGER.info("Received signal %s, shutting down", signum)
        for worker in workers:
            with contextlib.suppress(Exception):
                worker.close()
        sys.exit(0)

    for signame in (signal.SIGINT, signal.SIGTERM):
        signal.signal(signame, _shutdown_handler)


def main(argv: Sequence[str] | None = None, scheduler: Scheduler | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if not args.account:
        parser.error("At least one --account must be provided")

    if scheduler is None:
        scheduler = _LoggingScheduler()

    configs = parse_accounts(args.account, args.base_url)
    workers = [create_account_worker(config, scheduler) for config in configs]
    install_shutdown_hooks(workers)

    LOGGER.info("Workers initialised: %s", ", ".join(config.name for config in configs))
    parser.print_help()
    return 0


class _LoggingScheduler:
    """Fallback scheduler used when none is provided."""

    def schedule(self, payload: Mapping[str, object]) -> None:  # pragma: no cover - simple logger
        LOGGER.info("Scheduled follow-up for %s", payload)


if __name__ == "__main__":  # pragma: no cover - CLI entrypoint
    sys.exit(main())
