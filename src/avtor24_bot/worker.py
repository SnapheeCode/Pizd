"""Worker primitives for interacting with Автора24 orders."""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Mapping, Protocol

from .browser_bid import BidStatus, BrowserBidExecutor

LOGGER = logging.getLogger(__name__)


class Scheduler(Protocol):
    """Minimal protocol for objects that can schedule follow-up jobs."""

    def schedule(self, payload: Mapping[str, Any]) -> None:  # pragma: no cover - structural protocol
        """Schedule another job for processing."""


@dataclass
class AccountWorker:
    """Processes orders for a single account."""

    scheduler: Scheduler
    bid_executor: BrowserBidExecutor

    def submit_bid(self, order: Mapping[str, Any], bid: float, message: str) -> BidStatus:
        """Submit a bid and propagate the workflow depending on the result."""

        LOGGER.debug("Submitting bid for order %s", order.get("id") or order.get("order_id"))
        status = self.bid_executor.place_bid(order, bid, message)
        if status is BidStatus.SUCCESS:
            LOGGER.info("Bid submitted successfully, scheduling follow-up")
            self.scheduler.schedule(order)
        elif status is BidStatus.CAPTCHA_REQUIRED:
            LOGGER.warning("Captcha required for order %s", order)
        elif status is BidStatus.MODAL_TIMEOUT:
            LOGGER.warning("Timeout while waiting for confirmation modal for order %s", order)
        else:
            LOGGER.error("Bid submission failed for order %s", order)
        return status

    def close(self) -> None:
        """Release resources held by the worker."""

        self.bid_executor.close()


__all__ = ["AccountWorker", "Scheduler"]
