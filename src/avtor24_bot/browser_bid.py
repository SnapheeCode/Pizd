from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from http.cookies import SimpleCookie
from typing import Iterable, Optional
from urllib.parse import urlparse

from playwright.async_api import (
    Browser,
    BrowserContext,
    Error as PlaywrightError,
    Page,
    Playwright,
    TimeoutError as PlaywrightTimeout,
    async_playwright,
)

from .config import BrowserModel
from .models import Order

logger = logging.getLogger(__name__)


class BrowserBidError(RuntimeError):
    """Base error for browser bid executor."""


class CaptchaRequiredError(BrowserBidError):
    """Raised when the smart captcha is visible and blocks submission."""


@dataclass(slots=True)
class _BrowserRuntime:
    browser: Browser
    context: BrowserContext
    page: Page


class BrowserBidExecutor:
    """Drive браузер для отправки ставок через интерфейс сайта."""

    def __init__(
        self,
        *,
        base_url: str,
        cookie_header: str,
        user_agent: str,
        browser_config: BrowserModel,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._cookie_header = cookie_header
        self._user_agent = user_agent
        self._config = browser_config
        self._runtime: Optional[_BrowserRuntime] = None
        self._lock = asyncio.Lock()
        self._playwright: Optional[Playwright] = None

    async def __aenter__(self) -> "BrowserBidExecutor":
        await self.start()
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        await self.stop()

    async def start(self) -> None:
        if self._runtime is not None:
            return
        playwright = await async_playwright().start()
        try:
            browser = await playwright.chromium.launch(headless=self._config.headless, slow_mo=self._config.slow_mo)
            context = await browser.new_context(user_agent=self._user_agent)
            await context.add_cookies(list(self._build_cookies()))
            page = await context.new_page()
            await page.goto(self._base_url, wait_until="domcontentloaded")
            self._runtime = _BrowserRuntime(browser=browser, context=context, page=page)
            self._playwright = playwright
        except Exception:
            await playwright.stop()
            raise

    async def stop(self) -> None:
        runtime = self._runtime
        if runtime is None:
            return
        self._runtime = None
        try:
            await runtime.page.close()
        except PlaywrightError:  # pragma: no cover - best effort
            logger.debug("Failed to close page", exc_info=True)
        try:
            await runtime.context.close()
        except PlaywrightError:  # pragma: no cover - best effort
            logger.debug("Failed to close context", exc_info=True)
        try:
            await runtime.browser.close()
        except PlaywrightError:  # pragma: no cover - best effort
            logger.debug("Failed to close browser", exc_info=True)
        if self._playwright is not None:
            await self._playwright.stop()
            self._playwright = None

    async def place_bid(self, order: Order, bid_value: int, message: str) -> None:
        runtime = self._runtime
        if runtime is None:
            raise BrowserBidError("Browser executor is not started")
        url = f"{self._base_url}/order/{order.id}"
        timeout = self._config.navigation_timeout_ms
        async with self._lock:
            try:
                await runtime.page.goto(url, wait_until="domcontentloaded", timeout=timeout)
            except PlaywrightTimeout as exc:
                raise BrowserBidError(f"Не удалось открыть страницу заказа {order.id}: {exc}") from exc

            await self._open_bid_modal(runtime.page, timeout)
            await self._fill_bid_form(runtime.page, bid_value, message, timeout)
            await self._submit(runtime.page, timeout)

    async def _open_bid_modal(self, page: Page, timeout: int) -> None:
        bid_input = await page.query_selector("input#MakeOffer__inputBid")
        if bid_input:
            return
        button = await page.query_selector("button:has-text('Сделать ставку')")
        if button is None:
            raise BrowserBidError("Не найдена кнопка открытия модалки ставки")
        await button.click()
        try:
            await page.wait_for_selector("input#MakeOffer__inputBid", state="visible", timeout=timeout)
        except PlaywrightTimeout as exc:
            raise BrowserBidError("Поле суммы ставки не появилось") from exc

    async def _fill_bid_form(self, page: Page, bid_value: int, message: str, timeout: int) -> None:
        bid_selector = "input#MakeOffer__inputBid"
        field = await page.wait_for_selector(bid_selector, state="visible", timeout=timeout)
        await field.fill("")
        await field.type(str(bid_value))

        textarea = await page.query_selector("textarea#makeOffer_comment")
        if textarea is None:
            logger.warning("Не найдено поле комментария к ставке")
        else:
            await textarea.fill("")
            await textarea.type(message)

    async def _submit(self, page: Page, timeout: int) -> None:
        submit = await page.query_selector("button:has-text('Поставить ставку')")
        if submit is None:
            raise BrowserBidError("Не найдена кнопка отправки ставки")

        captcha = await page.query_selector(".smart-captcha")
        if captcha and await captcha.is_visible():
            raise CaptchaRequiredError("Для отправки требуется смарт-капча")

        await submit.click()
        try:
            await page.wait_for_selector("button:has-text('Поставить ставку')", state="detached", timeout=timeout)
        except PlaywrightTimeout:
            # Проверим, не показалась ли капча после клика
            captcha = await page.query_selector(".smart-captcha")
            if captcha and await captcha.is_visible():
                raise CaptchaRequiredError("Появилась капча при отправке ставки")
            raise BrowserBidError("Модалка ставки не закрылась после отправки")

    def _build_cookies(self) -> Iterable[dict]:
        cookie = SimpleCookie()
        cookie.load(self._cookie_header)
        parsed = urlparse(self._base_url)
        domain = parsed.hostname or "avtor24.ru"
        for key, morsel in cookie.items():
            yield {
                "name": key,
                "value": morsel.value,
                "domain": domain,
                "path": morsel["path"] or "/",
                "httpOnly": False,
                "secure": parsed.scheme == "https",
            }
