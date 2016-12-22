import asyncio
import contextlib
import logging

import async_timeout

__all__ = ('PeriodicScheduler',)


class PeriodicScheduler:

    def __init__(self, coro, period, name=None, *,
                 start_immediately=True,
                 max_consec_errors=20,
                 crashloop_period=None,
                 timeout=None, loop):
        assert asyncio.iscoroutinefunction(coro)

        self._loop = loop
        self._coro = coro
        self._period = period
        self._start_immediately = start_immediately
        self._max_consec_errors = max_consec_errors
        self._timeout = timeout
        self._num_consec_errors = 0
        self._task = None

        if name is None:
            name = str(self)
        self._name = name

        if crashloop_period is None:
            crashloop_period = 5 * period
        self._crashloop_period = crashloop_period

        self._logger = logging.getLogger(__name__ + '.' + name)

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
                self._logger.debug("Starting periodic function")
                try:
                    with async_timeout.timeout(self._timeout):
                        await self._coro()

                except TimeoutError:
                    self._logger.exception("Periodic function timeout")
                    self._num_consec_errors += 1

                except Exception:
                    self._num_consec_errors += 1
                    self._logger.exception(
                        "Periodic function raise exception "
                        "({} time).".format(self._num_consec_errors))

                else:
                    self._logger.debug("Periodic function finished")
                    self._num_consec_errors = 0

                if self._num_consec_errors >= self._max_consec_errors:
                    self._logger.debug(
                        "Maximum number of consecutive errors reached "
                        "({}), using crashloop period.".format(
                            self._max_consec_errors))

                    await asyncio.sleep(
                        self._crashloop_period, loop=self._loop)

                else:
                    await asyncio.sleep(self._period, loop=self._loop)
