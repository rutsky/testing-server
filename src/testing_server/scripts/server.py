import asyncio
import contextlib
import functools
import logging
import signal
import sys

import configargparse
import aiohttp.web
import raven
import raven_aiohttp
import yarl
from raven.handlers.logging import SentryHandler
from testing_server import __version__ as PROJECT_VERSION
from testing_server.credentials_checker import HtpasswdCredentialsChecker
from testing_server.server import Server
from testing_server.token_provider import JWTTokenProvider

__all__ = ('main',)


_logger = logging.getLogger(__name__)


def _setup_logging(level=logging.DEBUG):
    format_string = '%(asctime)-15s %(name)s %(levelname)s: %(message)s'
    logging.basicConfig(format=format_string, level=level)


def _setup_termination(*, loop: asyncio.AbstractEventLoop):
    def on_signal(signame):
        _logger.info("Received signal %s. Exiting..." % signame)

        loop.call_soon(lambda: loop.stop())

    for signame in ('SIGINT', 'SIGTERM'):
        loop.add_signal_handler(getattr(signal, signame),
                                functools.partial(on_signal, signame))


def _setup_sentry(*, loop):
    sentry_client = raven.Client(
        transport=functools.partial(raven_aiohttp.AioHttpTransport, loop=loop),
        release=PROJECT_VERSION
    )

    # Pass error messages from log to Sentry.
    handler = SentryHandler(sentry_client, level='ERROR')
    raven.conf.setup_logging(handler)

    prev_loop_exception_handler = loop.get_exception_handler()

    def loop_exception_handler(loop, context):
        if 'exception' in context:
            exc = context['exception']
            exc_info = (type(exc), exc, exc.__traceback__)
            sentry_client.captureException(exc_info, extra=context)
        else:
            sentry_client.captureMessage(
                "Event loop caught unhandled exception: {}".format(
                    context['message']),
                extra=context
            )

        if prev_loop_exception_handler is not None:
            return prev_loop_exception_handler(loop, context)

    loop.set_exception_handler(loop_exception_handler)


def run_server(hostname, port, htpasswd, token_secret, *, enable_cors=False):
    shutdown_timeout = 10

    credentials_checker = HtpasswdCredentialsChecker(htpasswd)
    token_provider = JWTTokenProvider(token_secret)

    loop = asyncio.get_event_loop()
    asyncio.set_event_loop(None)

    _setup_termination(loop=loop)
    _setup_sentry(loop=loop)

    with contextlib.ExitStack() as exit_stack:
        exit_stack.callback(loop.close)

        app = aiohttp.web.Application(loop=loop)

        # Start application server.
        app_server = Server(
            app,
            credentials_checker,
            token_provider,
            loop=loop,
            enable_cors=enable_cors)
        loop.run_until_complete(app_server.start())

        handler = app.make_handler()
        socket_server = loop.run_until_complete(
            loop.create_server(handler, hostname, port))

        def stop_app():
            _logger.info("Stopping web application...")
            socket_server.close()
            loop.run_until_complete(socket_server.wait_closed())
            loop.run_until_complete(app.shutdown())
            loop.run_until_complete(
                handler.finish_connections(shutdown_timeout))
            loop.run_until_complete(app.cleanup())

        # Stop our server first to allow graceful termination of persistent
        # connections (e.g. WebSockets).
        # Notice that top of the stack will be executed earlier.
        exit_stack.callback(stop_app)
        exit_stack.callback(
            lambda: loop.run_until_complete(app_server.stop()))

        url = yarl.URL('http://example.org').\
            with_host(hostname).with_port(port)
        _logger.info("Server started on {}".format(url.human_repr()))

        loop.run_forever()

    return 0


def main():
    parser = configargparse.ArgumentParser(
        description="Testing server",
        auto_env_var_prefix="TESTING_SERVER_")
    parser.add_argument(
        "-l",
        dest="log_level",
        choices=['DEBUG', 'INFO', 'WARNING', 'ERROR', 'CRITICAL'],
        default='INFO',
        help="Set the logging level. Default: %(default)s",
    )
    parser.add_argument(
        "-H", "--hostname",
        default="localhost",
        help="TCP/IP hostname to serve on (default: %(default)r)",
    )
    parser.add_argument(
        "-P", "--port",
        type=int,
        default="8080",
        help="TCP/IP port to serve on (default: %(default)r)",
    )
    parser.add_argument(
        "--htpasswd",
        required=True,
        help="Path to htpasswd file which should be used for authentication."
    )
    parser.add_argument(
        "--enable-cors",
        action='store_true',
        help="Allow API methods to be access from all origins according to "
             "CORS specification."
    )
    parser.add_argument(
        "--token-secret",
        required=True,
        help="Secret used for token generation."
    )

    args = parser.parse_args()

    _setup_logging(args.log_level)

    try:
        return run_server(
            args.hostname,
            args.port,
            args.htpasswd,
            args.token_secret,
            enable_cors=args.enable_cors)

    except Exception:
        _logger.exception("Server failed")
        return 1


if __name__ == '__main__':
    sys.exit(main())
