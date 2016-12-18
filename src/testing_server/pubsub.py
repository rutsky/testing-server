import asyncio

from .abc import AbstracePublisher, AbstractSubscriber

__all__ = ('Publisher',)

import aiohttp.pytest_plugin


class Publisher(AbstracePublisher):
    class _Subscriber(AbstractSubscriber):
        def __init__(self, publisher, topic, *, loop):
            self._publisher = publisher
            self._topic = topic
            self._loop = loop

            self._queue = asyncio.Queue(loop=loop)
            self._subscribed = False

        @property
        def topic(self):
            return self._topic

        @property
        def queue(self):
            assert self._subscribed
            return self._queue

        def close(self):
            assert self._subscribed
            self._publisher._unsubscribe(self)

        def __enter__(self):
            return self

        def __exit__(self, *_):
            if self._subscribed:
                self.close()

    def __init__(self, *, loop):
        # topic -> set of subscribers
        self._loop = loop
        self._subscribers = {}

    def publish(self, topic, message):
        for sub in list(self._subscribers.get(topic, [])):
            sub.queue.put_nowait(message)

    def subscribe(self, topic):
        sub = self._Subscriber(self, topic, loop=self._loop)
        self._subscribers.setdefault(topic, set()).add(sub)
        sub._subscribed = True

        return sub

    def _unsubscribe(self, sub):
        sub._subscribed = False
        self._subscribers[sub.topic].remove(sub)
