from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from .browser_bid import BrowserBidError, BrowserBidExecutor, CaptchaRequiredError
from .config import AccountConfig
from .graphql import add_comment, fetch_orders, get_bid_params, get_order_for_bid, mark_order_as_read
from .http import GraphQLClient
from .models import Order
from .queue import OrderQueue
from .scheduler import FollowUpScheduler
from .state import AccountState, StateRepository

logger = logging.getLogger(__name__)


class AccountWorker:
    def __init__(
        self,
        config: AccountConfig,
        *,
        state_repo: StateRepository,
        scheduler: FollowUpScheduler,
    ) -> None:
        self._config = config
        self._state_repo = state_repo
        self._scheduler = scheduler
        self._queue = OrderQueue()
        self._last_bid_at: Optional[datetime] = None
        self._stop_event = asyncio.Event()
        auth = self._config.data.auth
        self._browser_executor = BrowserBidExecutor(
            base_url=self._config.data.base_url,
            cookie_header=auth.cookie,
            user_agent=auth.user_agent,
            browser_config=self._config.data.browser,
        )

    @property
    def login(self) -> str:
        return self._config.login

    async def run(self) -> None:
        account_state = self._state_repo.get(self.login)
        auth = self._config.data.auth
        async with self._browser_executor:
            async with GraphQLClient(
                base_url=self._config.data.base_url,
                cookie=auth.cookie,
                user_agent=auth.user_agent,
            ) as client:
                poll_interval = self._config.data.poll_interval_seconds
                min_between_bids = self._config.data.min_seconds_between_bids
                while not self._stop_event.is_set():
                    try:
                        await self._refresh_queue(client)
                        await self._process_next_order(client, account_state, min_between_bids)
                    except Exception:  # pragma: no cover - logging path
                        logger.exception("Worker %s iteration failed", self.login)
                    await asyncio.sleep(poll_interval)

    def stop(self) -> None:
        self._stop_event.set()

    async def _refresh_queue(self, client: GraphQLClient) -> None:
        filters = self._build_filters()
        data = await fetch_orders(
            client,
            limit=30,
            page=1,
            filters=filters,
            constraints={"withoutMyBids": True, **filters},
        )
        orders_block = data.get("orders", {})
        for payload in orders_block.get("orders", []):
            order = Order.from_graphql(payload)
            if not self._matches_filters(order):
                continue
            self._queue.push_or_update(order)

    async def _process_next_order(
        self,
        client: GraphQLClient,
        account_state: AccountState,
        min_between_bids: float,
    ) -> None:
        if not len(self._queue):
            return
        if self._last_bid_at:
            delta = datetime.now(timezone.utc) - self._last_bid_at
            if delta.total_seconds() < min_between_bids:
                return
        order = self._queue.pop()
        if order is None:
            return
        if order.author_has_offer:
            return
        await self._execute_pipeline(client, account_state, order)
        self._last_bid_at = datetime.now(timezone.utc)
        self._state_repo.save()

    async def _execute_pipeline(
        self,
        client: GraphQLClient,
        account_state: AccountState,
        order: Order,
    ) -> None:
        logger.info("Processing order %s", order.id)
        await mark_order_as_read(client, order.id)
        order_details = await get_order_for_bid(client, order.id)
        bid_params = {}
        type_info = order_details.get("type") or {}
        category_info = order_details.get("category") or {}
        type_id = str(type_info.get("id")) if type_info else order.type_id
        category_id = str(category_info.get("id")) if category_info else order.subject_id
        if type_id and category_id:
            bid_params = await get_bid_params(
                client,
                order_id=order.id,
                type_id=type_id,
                category_id=category_id,
                is_first_offer=order.count_offers == 0,
            )
        bid = self._calculate_bid(order, order_details, bid_params)
        try:
            await self._browser_executor.place_bid(
                order,
                bid,
                self._render_initial_message(order),
            )
        except CaptchaRequiredError as exc:
            logger.warning("Order %s: captcha required (%s)", order.id, exc)
            return
        except BrowserBidError as exc:
            logger.error("Order %s: browser bid failed: %s", order.id, exc)
            return
        account_state.mark_bid_sent(order.id)
        task_id = self._scheduler.schedule(
            self._config.data.followup_delay_seconds,
            lambda: self._send_followup(client, account_state, order),
        )
        account_state.attach_task(order.id, task_id)

    async def _send_followup(
        self,
        client: GraphQLClient,
        account_state: AccountState,
        order: Order,
    ) -> None:
        logger.info("Sending follow-up for %s", order.id)
        await add_comment(client, order.id, self._render_followup_message(order))
        account_state.mark_followup_sent(order.id)
        self._state_repo.save()

    def _render_initial_message(self, order: Order) -> str:
        return self._config.data.messages.initial.format(order_title=order.title)

    def _render_followup_message(self, order: Order) -> str:
        return self._config.data.messages.followup.format(order_title=order.title)

    def _calculate_bid(
        self,
        order: Order,
        order_details: Dict[str, Any],
        bid_params: Dict[str, Any],
    ) -> int:
        bid_cfg = self._config.data.bid
        recommended = (
            (bid_params.get("getOrderParams") or {}).get("recommendPrice")
            if bid_params
            else None
        )
        base = (
            recommended
            or order_details.get("recommendedBudget")
            or order.recommended_budget
            or order.budget
            or bid_cfg.min_bid
        )
        bid_value = int(base * bid_cfg.multiplier)
        bid_value = max(bid_value, bid_cfg.min_bid)
        bid_value = min(bid_value, bid_cfg.max_bid)
        return bid_value

    def _matches_filters(self, order: Order) -> bool:
        filters = self._config.data.filters
        if filters.subject_ids and order.subject_id not in filters.subject_ids:
            return False
        if filters.type_ids and order.type_id not in filters.type_ids:
            return False
        budget = order.budget or 0
        if budget < filters.min_budget or budget > filters.max_budget:
            return False
        return True

    def _build_filters(self) -> Dict[str, Any]:
        filters = self._config.data.filters
        return {
            "types": filters.type_ids,
            "categories": filters.subject_ids,
            "isFastOrder": False,
            "noBids": False,
            "hasFile": False,
            "less3bids": False,
            "customerOnline": False,
            "orderIsPaid": False,
            "contractual": True,
            "isFamiliarCustomer": False,
            "withoutMyBids": True,
            "budgetFrom": filters.min_budget,
            "budgetTo": filters.max_budget,
            "deadlineFrom": 0,
            "deadlineTo": 365,
            "uniqueValueFrom": 0,
            "uniqueValueTo": 100,
            "bidCountFrom": 0,
            "bidCountTo": 200,
            "query": "",
            "title": "",
            "categoryName": "",
            "typeName": "",
            "customerName": "",
        }
