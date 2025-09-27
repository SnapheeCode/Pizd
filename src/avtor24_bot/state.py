from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Dict, Optional


@dataclass(slots=True)
class OrderRuntimeState:
    order_id: str
    status: str = "new"
    last_attempt: Optional[datetime] = None
    followup_task_id: Optional[str] = None


@dataclass(slots=True)
class AccountState:
    login: str
    orders: Dict[str, OrderRuntimeState] = field(default_factory=dict)

    def mark_bid_sent(self, order_id: str) -> None:
        state = self.orders.setdefault(order_id, OrderRuntimeState(order_id))
        state.status = "bid_sent"
        state.last_attempt = datetime.utcnow()

    def mark_followup_sent(self, order_id: str) -> None:
        state = self.orders.setdefault(order_id, OrderRuntimeState(order_id))
        state.status = "followup_sent"
        state.last_attempt = datetime.utcnow()
        state.followup_task_id = None

    def attach_task(self, order_id: str, task_id: str) -> None:
        state = self.orders.setdefault(order_id, OrderRuntimeState(order_id))
        state.followup_task_id = task_id

    def detach_task(self, order_id: str) -> None:
        state = self.orders.get(order_id)
        if state:
            state.followup_task_id = None


class StateRepository:
    def __init__(self, path: Path) -> None:
        self._path = path
        self._data: Dict[str, AccountState] = {}
        if path.exists():
            self._load()

    def _load(self) -> None:
        with self._path.open("r", encoding="utf-8") as fh:
            raw = json.load(fh)
        for login, value in raw.items():
            orders = {
                order_id: OrderRuntimeState(
                    order_id=order_id,
                    status=item.get("status", "new"),
                    last_attempt=datetime.fromisoformat(item["last_attempt"]) if item.get("last_attempt") else None,
                    followup_task_id=item.get("followup_task_id"),
                )
                for order_id, item in value.get("orders", {}).items()
            }
            self._data[login] = AccountState(login=login, orders=orders)

    def save(self) -> None:
        payload = {
            login: {
                "orders": {
                    order_id: {
                        "status": state.status,
                        "last_attempt": state.last_attempt.isoformat() if state.last_attempt else None,
                        "followup_task_id": state.followup_task_id,
                    }
                    for order_id, state in account.orders.items()
                }
            }
            for login, account in self._data.items()
        }
        self._path.parent.mkdir(parents=True, exist_ok=True)
        with self._path.open("w", encoding="utf-8") as fh:
            json.dump(payload, fh, ensure_ascii=False, indent=2)

    def get(self, login: str) -> AccountState:
        return self._data.setdefault(login, AccountState(login=login))

    def reset_order(self, login: str, order_id: str) -> None:
        account = self.get(login)
        account.orders.pop(order_id, None)
