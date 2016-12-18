import asyncio
import functools
import numbers
import inspect

import async_timeout

from testing_server.pubsub import Publisher


def set_timeout(timeout=30):
    assert isinstance(timeout, numbers.Number)

    def decorator(f):
        assert asyncio.iscoroutinefunction(f)

        @functools.wraps(f)
        async def wrapper(*args, **kwargs):
            loop = inspect.signature(f).bind(*args, **kwargs).arguments['loop']
            with async_timeout.timeout(timeout, loop=loop):
                return await f(*args, **kwargs)

        return wrapper

    return decorator


@set_timeout()
async def test_pubsub(loop):
    pub = Publisher(loop=loop)

    async def read_topic(topic):
        with pub.subscribe(topic) as sub:
            return await sub.queue.get()

    read_topic1_task1 = loop.create_task(read_topic('topic1'))
    read_topic1_task2 = loop.create_task(read_topic('topic1'))

    read_topic2_task1 = loop.create_task(read_topic('topic2'))

    await asyncio.sleep(0)

    pub.publish('topic1', 'test1')
    pub.publish('topic2', 'test2')

    res = await asyncio.gather(
        read_topic1_task1, read_topic1_task2, read_topic2_task1)
    assert res == ['test1', 'test1', 'test2']
