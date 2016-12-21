import asyncio
import contextlib
import logging

__all__ = ('PeriodicScheduler',)

_logger = logging.getLogger(__name__)


class PeriodicScheduler:

    def __init__(self, coro, period, *,
                 start_immediately=True, max_consec_errors=20, loop):
        self._loop = loop
        self._coro = coro
        self._period = period
        self._start_immediately = start_immediately
        self._max_consec_errors = max_consec_errors
        self._num_consec_errors = 0
        self._task = None

    async def start(self):
        assert self._task is None
        self._task = self._loop.create_task(self._runner())

    async def stop(self):
        assert self._task is not None
        self._task.cancel()
        await self._task
        self._task = None
        self._num_consec_errors = 0

    async def _runner(self):
        with contextlib.suppress(asyncio.CancelledError):
            if not self._start_immediately:
                await asyncio.sleep(self._period)

            while True:
                try:
                    await self._coro()
                except Exception:
                    self._num_consec_errors += 1
                    _logger.exception(
                        "Periodic function raise exception "
                        "({} time).".format(self._num_consec_errors))

                    if self._num_consec_errors >= self._max_consec_errors:
                        _logger.error(
                            "Maximum number of consecutive errors reached "
                            "({}), stopping periodic scheduler.".format(
                                self._max_consec_errors))
                else:
                    self._num_consec_errors = 0

                await asyncio.sleep(self._period, loop=self._loop)
