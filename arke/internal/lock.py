import asyncio

class Lock(asyncio.Event):
    async def __aenter__(self):
        await self.wait()
        return self

    async def __aexit__(self, *_):
        pass

    def lock_for(self, time: float):
        if not self.is_set():
            return

        self.clear()
        asyncio.create_task(self._unlock(time))

    async def _unlock(self, time: float):
        await asyncio.sleep(time)
        self.set()
