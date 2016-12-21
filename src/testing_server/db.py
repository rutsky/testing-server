import aiopg

from .abc import AbstractDatabase

__all__ = ('Database',)


class Database(AbstractDatabase):

    def __init__(self, dsn, *, loop):
        self._dsn = dsn
        self._loop = loop
        self._pool = None

    @property
    def pool(self):
        assert self._pool is not None
        return self._pool

    async def start(self):
        self._pool = await aiopg.create_pool(self._dsn, loop=self._loop)

    async def stop(self):
        self._pool.terminate()
        await self._pool.wait_closed()
        self._pool = None
