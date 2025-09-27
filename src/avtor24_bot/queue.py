from __future__ import annotations

import heapq
from dataclasses import dataclass, field
from typing import Dict, Iterable, List, Optional

from .models import Order


@dataclass(order=True)
class _QueueItem:
    priority: tuple[int, float]
    order: Order = field(compare=False)


class OrderQueue:
    def __init__(self) -> None:
        self._heap: List[_QueueItem] = []
        self._index: Dict[str, _QueueItem] = {}

    def __len__(self) -> int:
        return len(self._heap)

    def all_orders(self) -> Iterable[Order]:
        return (item.order for item in sorted(self._heap))

    def push_or_update(self, order: Order) -> None:
        priority = self._build_priority(order)
        existing = self._index.get(order.id)
        if existing:
            existing.order = order
            existing.priority = priority
            heapq.heapify(self._heap)
        else:
            item = _QueueItem(priority=priority, order=order)
            heapq.heappush(self._heap, item)
            self._index[order.id] = item

    def pop(self) -> Optional[Order]:
        while self._heap:
            item = heapq.heappop(self._heap)
            order = item.order
            self._index.pop(order.id, None)
            return order
        return None

    @staticmethod
    def _build_priority(order: Order) -> tuple[int, float]:
        is_new = 1 if order.is_new else 0
        timestamp = order.creation.timestamp()
        return (-is_new, -timestamp)
