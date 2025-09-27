from __future__ import annotations

import asyncio
import itertools
from dataclasses import dataclass
from typing import Awaitable, Callable, Dict, Optional


@dataclass(slots=True)
class ScheduledTask:
    id: str
    handle: asyncio.TimerHandle


class FollowUpScheduler:
    def __init__(self, loop: Optional[asyncio.AbstractEventLoop] = None) -> None:
        if loop is None:
            try:
                loop = asyncio.get_running_loop()
            except RuntimeError:  # no running loop
                loop = asyncio.new_event_loop()
        self._loop = loop
        self._tasks: Dict[str, ScheduledTask] = {}
        self._counter = itertools.count()

    def schedule(self, delay: float, callback: Callable[[], Awaitable[None]]) -> str:
        task_id = f"followup-{next(self._counter)}"

        async def runner() -> None:
            try:
                await callback()
            finally:
                self._tasks.pop(task_id, None)

        handle = self._loop.call_later(delay, lambda: asyncio.create_task(runner()))
        self._tasks[task_id] = ScheduledTask(id=task_id, handle=handle)
        return task_id

    def cancel(self, task_id: str) -> None:
        task = self._tasks.pop(task_id, None)
        if task:
            task.handle.cancel()
