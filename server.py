import logging
import argparse
import asyncio
import signal
import functools
import contextlib
import traceback
import json

import aiohttp.web
import yarl


_logger = logging.getLogger(__name__)


def _setup_logging(level=logging.DEBUG):
    format_string = '%(asctime)-15s %(name)s %(levelname)s: %(message)s'
    logging.basicConfig(format=format_string, level=level)


def _setup_termination(loop: asyncio.AbstractEventLoop):
    def on_signal(signame):
        _logger.info("Received signal %s. Exiting..." % signame)

        loop.call_soon(lambda: loop.stop())

    for signame in ('SIGINT', 'SIGTERM'):
        loop.add_signal_handler(getattr(signal, signame),
                                functools.partial(on_signal, signame))


JSEND_DUMP_TRACEBACKS = True


class JSendError(Exception):
    """Internal server error wrapper"""

    def __init__(self, message, code=None, data=None, http_code=500):
        self.message = message
        self.code = code
        self.data = data
        self.http_code = http_code


class JSendFail(Exception):
    """Bad request error wrapper"""

    def __init__(self, message, data=None, http_code=400):
        self.message = message
        self.data = data
        self.http_code = http_code


def jsend_handler(handler):
    @functools.wraps(handler)
    async def wrapper(*args):
        response = {
            'status': 'success'
        }

        http_code = 200

        try:
            response['data'] = await handler(*args)

        except JSendFail as ex:
            http_code = ex.http_code
            response['status'] = 'fail'
            response['message'] = ex.message

        except JSendError as ex:
            http_code = ex.http_code
            response['status'] = 'error'
            response['message'] = ex.message

            if ex.code is not None:
                response['code'] = ex.code
            if ex.data is not None:
                response['data'] = ex.data

        except Exception:
            http_code = 500
            response['status'] = 'error'
            message = "Internal server error."

            if JSEND_DUMP_TRACEBACKS:
                message += "\n" + traceback.format_exc()

            response['message'] = message

        return aiohttp.web.Response(
            text=json.dumps(response),
            content_type='application/json',
            status=http_code
        )

    return wrapper


class Server:
    def __init__(self, app, *, loop):
        self._app = app
        self._loop = loop

    async def start(self):
        self._app.router.add_get('/', self.handler_default)

    async def stop(self):
        pass

    @jsend_handler
    async def handler_default(self, request):
        return "Testing server."


def main():
    parser = argparse.ArgumentParser(description="Testing server")
    parser.add_argument(
        "-l",
        dest="log_level",
        choices=['DEBUG', 'INFO', 'WARNING', 'ERROR', 'CRITICAL'],
        default='INFO',
        help="Set the logging level. Default: %(default)s."
    )
    parser.add_argument(
        "-H", "--hostname",
        help="TCP/IP hostname to serve on (default: %(default)r)",
        default="localhost"
    )
    parser.add_argument(
        "-P", "--port",
        help="TCP/IP port to serve on (default: %(default)r)",
        type=int,
        default="8080"
    )

    args = parser.parse_args()

    shutdown_timeout = 10

    _setup_logging(args.log_level)

    loop = asyncio.get_event_loop()
    asyncio.set_event_loop(None)

    _setup_termination(loop)

    with contextlib.ExitStack() as exit_stack:
        exit_stack.callback(loop.close)

        app = aiohttp.web.Application(loop=loop)

        # Start application server.
        app_server = Server(app, loop=loop)
        loop.run_until_complete(app_server.start())

        handler = app.make_handler()
        socket_server = loop.run_until_complete(
            loop.create_server(handler, args.hostname, args.port))

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
        exit_stack.callback(lambda: stop_app)
        exit_stack.callback(lambda: loop.run_until_complete(app_server.stop()))

        url = yarl.URL('http://example.org').\
            with_host(args.hostname).with_port(args.port)
        _logger.info("Server started on {}".format(url.human_repr()))

        loop.run_forever()


if __name__ == '__main__':
    main()
