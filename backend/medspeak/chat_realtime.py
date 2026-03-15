from __future__ import annotations

import asyncio
import contextlib
from collections import defaultdict
from collections.abc import AsyncIterator, Awaitable, Callable

from medspeak.chat_schema import ChatStreamEvent


class ChatRealtimeManager:
    def __init__(self) -> None:
        self._loop: asyncio.AbstractEventLoop | None = None
        self._subscribers: dict[str, set[asyncio.Queue[ChatStreamEvent | None]]] = defaultdict(set)
        self._tasks: dict[int, asyncio.Task[None]] = {}

    async def start(self) -> None:
        self._loop = asyncio.get_running_loop()

    async def stop(self) -> None:
        for task in list(self._tasks.values()):
            task.cancel()
        if self._tasks:
            await asyncio.gather(*self._tasks.values(), return_exceptions=True)
        self._tasks.clear()

        for queues in self._subscribers.values():
            for queue in queues:
                with contextlib.suppress(asyncio.QueueFull):
                    queue.put_nowait(None)
        self._subscribers.clear()

    async def subscribe(self, chat_session_id: str) -> AsyncIterator[ChatStreamEvent | None]:
        queue: asyncio.Queue[ChatStreamEvent | None] = asyncio.Queue()
        self._subscribers[chat_session_id].add(queue)
        try:
            while True:
                try:
                    event = await asyncio.wait_for(queue.get(), timeout=15.0)
                except asyncio.TimeoutError:
                    yield None
                    continue
                yield event
                if event is None:
                    break
        finally:
            self._subscribers[chat_session_id].discard(queue)
            if not self._subscribers[chat_session_id]:
                self._subscribers.pop(chat_session_id, None)

    def publish(self, event: ChatStreamEvent) -> None:
        if self._loop is None:
            return
        self._loop.call_soon_threadsafe(self._publish_now, event)

    def _publish_now(self, event: ChatStreamEvent) -> None:
        for queue in list(self._subscribers.get(event.chat_session_id, set())):
            with contextlib.suppress(asyncio.QueueFull):
                queue.put_nowait(event)

    def submit_refinement(self, assistant_message_id: int, runner: Callable[[], Awaitable[None]]) -> None:
        if self._loop is None:
            return
        self._loop.call_soon_threadsafe(self._submit_now, assistant_message_id, runner)

    def _submit_now(self, assistant_message_id: int, runner: Callable[[], Awaitable[None]]) -> None:
        if assistant_message_id in self._tasks and not self._tasks[assistant_message_id].done():
            return
        task = asyncio.create_task(self._run_task(assistant_message_id, runner))
        self._tasks[assistant_message_id] = task
        task.add_done_callback(lambda _: self._tasks.pop(assistant_message_id, None))

    async def _run_task(self, assistant_message_id: int, runner: Callable[[], Awaitable[None]]) -> None:
        try:
            await runner()
        except asyncio.CancelledError:
            raise
        except Exception:
            # The caller handles persistence and publishes any user-visible failure.
            return
