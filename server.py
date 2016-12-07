import logging
import argparse
import asyncio
import signal
import functools
import contextlib


_logger = logging.getLogger(__name__)


def _setup_logging(level=logging.DEBUG):
    format_string = '%(asctime)-15s %(name)s %(levelname)s: %(message)s'
    logging.basicConfig(format=format_string, level=level)


def _setup_termination(loop: asyncio.AbstractEventLoop):
    def on_signal(signame):
        _logger.info("Got signal %s. Exiting..." % signame)

        loop.call_soon(lambda: loop.stop())

    for signame in ('SIGINT', 'SIGTERM'):
        loop.add_signal_handler(getattr(signal, signame),
                                functools.partial(on_signal, signame))


def main():
    parser = argparse.ArgumentParser(description="Testing server")
    parser.add_argument(
        "-l",
        dest="log_level",
        choices=['DEBUG', 'INFO', 'WARNING', 'ERROR', 'CRITICAL'],
        default='INFO',
        help="Set the logging level. Default: %(default)s.")

    args = parser.parse_args()

    _setup_logging(args.log_level)

    loop = asyncio.get_event_loop()
    asyncio.set_event_loop(None)

    _setup_termination(loop)

    with contextlib.closing(loop):
        pass


if __name__ == '__main__':
    main()
