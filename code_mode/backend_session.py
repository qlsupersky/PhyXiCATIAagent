"""One task owns MCP context managers for the whole facade lifetime.

Queued calls are serial. A transport exception poisons the session; never replay
or reconnect implicitly. Backends hold volatile sketch handles, not CAD locks.
"""
import asyncio
from pathlib import Path
import uuid


class BackendSession:
    def __init__(self, factory, config, folder):
        self.factory, self.config, self.folder = factory, config, Path(folder)
        self.session_id = uuid.uuid4().hex
        self.queue = asyncio.Queue()
        self.task = self.ready = None
        self.closed = False
        self.broken = None
        self.leases = 0

    async def ensure(self):
        if self.closed:
            raise RuntimeError('Backend session is closed')
        if self.task is None:
            self.folder.mkdir(parents=True, exist_ok=False)
            self.ready = asyncio.get_running_loop().create_future()
            self.task = asyncio.create_task(self._owner())
        await asyncio.shield(self.ready)
        if self.broken:
            raise RuntimeError('Backend session unavailable; no automatic reconnect') from self.broken
        return self

    async def _owner(self):
        try:
            # anyio cancellation scopes must enter and leave in this SAME task.
            async with self.factory(self.config, self.folder) as backend:
                self.schemas = backend.schemas
                self.ready.set_result(True)
                while True:
                    item = await self.queue.get()
                    if item is None:
                        break
                    args, future = item
                    try:
                        if self.broken:
                            raise RuntimeError('Backend session unavailable; no replay') from self.broken
                        result = await backend.call(*args)
                    except Exception as error:
                        self.broken = error
                        if not future.done(): future.set_exception(error)
                    else:
                        if not future.done(): future.set_result(result)
        except BaseException as error:
            self.broken = error
            if not self.ready.done(): self.ready.set_exception(error)
            # Drain waiting callers if the owning context unexpectedly exits.
            while not self.queue.empty():
                item = self.queue.get_nowait()
                if item is not None and not item[1].done():
                    item[1].set_exception(RuntimeError('Backend owner ended; no replay'))

    async def call(self, *args):
        await self.ensure()
        result = asyncio.get_running_loop().create_future()
        self.queue.put_nowait((args, result))
        return await asyncio.shield(result)

    async def __aenter__(self):
        await self.ensure()
        self.leases += 1
        return self

    async def __aexit__(self, *args):
        # Program end is NOT MCP session end; retain upstream in-memory state.
        pass

    async def aclose(self):
        self.closed = True
        if self.task is not None:
            self.queue.put_nowait(None)
            await self.task
