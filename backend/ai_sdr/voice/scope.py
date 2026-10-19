"""Every background task of a call belongs to its CallScope and dies with the call (plan root cause 4: timers that
fired after the call had closed, and exceptions nobody saw)."""
from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable, Coroutine
from typing import Any

log = logging.getLogger("ai_sdr.voice")


class CallScope:
    def __init__(self, on_error: Callable[[str, BaseException], None] | None = None):
        self._tasks: set[asyncio.Task] = set()
        self._keep: set[asyncio.Task] = set()   # short bookkeeping that must finish even when the call closes
        self._closed = False
        self._on_error = on_error

    @property
    def closed(self) -> bool:
        return self._closed

    def spawn(self, coro: Coroutine[Any, Any, Any], name: str, *, keep_on_close: bool = False) -> asyncio.Task | None:
        """Run coro in the background, owned by this call. Returns None (and drops coro) once the call is closing.
        keep_on_close: not cancelled when the call closes (bounded bookkeeping such as logging an event)."""
        if self._closed:
            coro.close()
            return None
        task = asyncio.get_running_loop().create_task(coro, name=name)
        self._tasks.add(task)
        if keep_on_close:
            self._keep.add(task)
        task.add_done_callback(self._done)
        return task

    def timer(self, delay: float, fn: Callable[[], Awaitable[Any] | None], name: str) -> asyncio.Task | None:
        async def run():
            await asyncio.sleep(delay)
            result = fn()
            if asyncio.iscoroutine(result):
                await result
        return self.spawn(run(), name)

    def _done(self, task: asyncio.Task) -> None:
        self._tasks.discard(task)
        self._keep.discard(task)
        if task.cancelled():
            return
        exc = task.exception()
        if exc is not None:
            log.error("call task %s failed: %r", task.get_name(), exc, exc_info=exc)
            if self._on_error is not None:
                self._on_error(task.get_name(), exc)

    def cancel_all(self) -> None:
        """Cancel every task except the one calling this (a task must not cancel itself mid-way)."""
        current = asyncio.current_task()
        for task in list(self._tasks):
            if task is not current and task not in self._keep:
                task.cancel()

    def close(self) -> None:
        self._closed = True
        self.cancel_all()

    def __len__(self) -> int:
        return len(self._tasks)
