"""Browser-based bid submission helpers for Автора24."""
from __future__ import annotations

import contextlib
import logging
import time
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Callable, Iterable, List, Mapping, MutableMapping, Optional

from playwright.sync_api import Browser, BrowserContext, Error, Page, Playwright, sync_playwright

LOGGER = logging.getLogger(__name__)


class BidStatus(str, Enum):
    """Possible outcomes of the bid submission flow."""

    SUCCESS = "success"
    CAPTCHA_REQUIRED = "captcha_required"
    MODAL_TIMEOUT = "modal_timeout"
    FAILED = "failed"


class BrowserBidError(RuntimeError):
    """Raised when the browser cannot be initialised or the bid submission fails."""


@dataclass(slots=True)
class BrowserBidExecutor:
    """High level API that encapsulates bid submission via a browser driver."""

    base_url: str
    cookies: Iterable[Mapping[str, object]]
    profile_path: Path
    browser_type: str = "chromium"
    headless: bool = True
    slow_mo: Optional[int] = None
    playwright_factory: Callable[[], Any] = field(default=sync_playwright, repr=False)
    _playwright_manager: Optional[Any] = field(default=None, init=False, repr=False)
    _playwright: Optional[Playwright] = field(default=None, init=False, repr=False)
    _browser: Optional[Browser] = field(default=None, init=False, repr=False)
    _context: Optional[BrowserContext] = field(default=None, init=False, repr=False)

    BID_INPUT_SELECTOR: str = "input[name='MakeOffer__inputBid']"
    COMMENT_INPUT_SELECTOR: str = "textarea[name='makeOffer_comment']"
    SUBMIT_BUTTON_SELECTOR: str = "button[data-testid='MakeOffer__submit']"
    SUCCESS_MODAL_SELECTOR: str = "div[data-testid='make-offer-success']"
    CAPTCHA_SELECTOR: str = "iframe[src*='captcha']"

    def __post_init__(self) -> None:
        self.profile_path = Path(self.profile_path)
        self.profile_path.mkdir(parents=True, exist_ok=True)

    # Public API -----------------------------------------------------------------
    def place_bid(self, order: Mapping[str, object], bid: float, message: str) -> BidStatus:
        """Submit a bid for the provided order."""

        page = self._ensure_page()
        order_id = self._extract_order_id(order)
        LOGGER.debug("Opening order %s", order_id)
        page.goto(self._order_url(order_id), wait_until="domcontentloaded")

        try:
            self._fill_bid_form(page, bid, message)
            page.click(self.SUBMIT_BUTTON_SELECTOR)
        except Error as exc:  # pragma: no cover - defensive branch
            LOGGER.exception("Unable to submit bid: %s", exc)
            return BidStatus.FAILED

        status = self._wait_for_completion(page)
        LOGGER.debug("Bid submission finished with status %s", status)
        return status

    def close(self) -> None:
        """Tear down Playwright objects associated with the executor."""

        LOGGER.debug("Closing BrowserBidExecutor for profile %s", self.profile_path)
        with contextlib.suppress(Exception):
            if self._context is not None:
                self._context.close()
        with contextlib.suppress(Exception):
            if self._browser is not None:
                self._browser.close()
        self._context = None
        self._browser = None

        if self._playwright_manager is not None:
            with contextlib.suppress(Exception):
                self._playwright_manager.__exit__(None, None, None)
        self._playwright_manager = None
        self._playwright = None

    # Internal helpers ------------------------------------------------------------
    def _ensure_page(self) -> Page:
        context = self._ensure_context()
        LOGGER.debug("Creating a fresh page for bid submission")
        return context.new_page()

    def _ensure_context(self) -> BrowserContext:
        if self._context is not None:
            return self._context

        browser = self._ensure_browser()
        LOGGER.debug("Opening new browser context at %s", self.profile_path)
        storage_state = self._build_storage_state(self.cookies)
        self._context = browser.new_context(storage_state=storage_state)
        return self._context

    def _ensure_browser(self) -> Browser:
        if self._browser is not None:
            return self._browser

        LOGGER.debug("Launching %s browser for profile %s", self.browser_type, self.profile_path)
        manager = self.playwright_factory()
        self._playwright_manager = manager
        try:
            playwright = manager.__enter__()
        except Exception as exc:  # pragma: no cover - defensive branch
            raise BrowserBidError("Unable to start Playwright") from exc
        self._playwright = playwright

        try:
            browser_launcher = getattr(playwright, self.browser_type)
        except AttributeError as exc:  # pragma: no cover - defensive branch
            raise BrowserBidError(f"Unsupported browser type: {self.browser_type}") from exc

        launch_kwargs = {"headless": self.headless}
        if self.slow_mo is not None:
            launch_kwargs["slow_mo"] = self.slow_mo

        self._browser = browser_launcher.launch(**launch_kwargs)
        return self._browser

    def _build_storage_state(self, cookies: Iterable[Mapping[str, object]]) -> Mapping[str, List[MutableMapping[str, object]]]:
        prepared: List[MutableMapping[str, object]] = []
        for cookie in cookies:
            normalised = dict(cookie)
            normalised.setdefault("sameSite", "Lax")
            prepared.append(normalised)
        return {"cookies": prepared}

    def _fill_bid_form(self, page: Page, bid: float, message: str) -> None:
        LOGGER.debug("Filling bid form: bid=%s", bid)
        page.fill(self.BID_INPUT_SELECTOR, str(bid))
        page.fill(self.COMMENT_INPUT_SELECTOR, message)

    def _wait_for_completion(self, page: Page, timeout: float = 15.0) -> BidStatus:
        start = time.monotonic()
        while time.monotonic() - start < timeout:
            if self._is_captcha_visible(page):
                return BidStatus.CAPTCHA_REQUIRED
            if self._is_success_modal_visible(page):
                return BidStatus.SUCCESS
            time.sleep(0.25)
        return BidStatus.MODAL_TIMEOUT

    def _is_success_modal_visible(self, page: Page) -> bool:
        with contextlib.suppress(Error):
            modal = page.query_selector(self.SUCCESS_MODAL_SELECTOR)
            if modal and modal.is_visible():
                return True
        return False

    def _is_captcha_visible(self, page: Page) -> bool:
        with contextlib.suppress(Error):
            captcha = page.query_selector(self.CAPTCHA_SELECTOR)
            if captcha and captcha.is_visible():
                return True
        return False

    def _extract_order_id(self, order: Mapping[str, object]) -> str:
        for key in ("id", "order_id"):
            if key in order:
                return str(order[key])
        raise BrowserBidError("Order payload is missing an identifier")

    def _order_url(self, order_id: str) -> str:
        return f"{self.base_url.rstrip('/')}/order/{order_id}"

    # Context manager protocol ----------------------------------------------------
    def __enter__(self) -> "BrowserBidExecutor":
        self._ensure_browser()
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.close()


__all__ = ["BrowserBidExecutor", "BidStatus", "BrowserBidError"]
