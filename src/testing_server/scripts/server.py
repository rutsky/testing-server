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
from aioxmlrpc.client import ServerProxy

from testing_server import __version__ as PROJECT_VERSION
from testing_server.credentials_checker import HtpasswdCredentialsChecker
from testing_server.server import Server
from testing_server.token_provider import JWTTokenProvider
from testing_server.db import (
    Database, LINKED_PTR_ASSIGNMENT_ID, LINKED_PTR_PATH)
from testing_server.trac import sync_tickets
from testing_server.svn import sync_svn
from testing_server.scheduler import PeriodicScheduler
from testing_server.test_runner import check_solutions
from testing_server.trac_reporter import report_solutions

__all__ = ('main',)


_logger = logging.getLogger(__name__)

_DEBUG_SYNC_TICKETS = False
_DEBUG_SYNC_SVN = False


def _setup_logging(level=logging.DEBUG):
    format_string = '%(asctime)-15s %(name)s %(levelname)s: %(message)s'
    logging.basicConfig(format=format_string, level=level)

    # Asyncio is too spammy.
    logging.getLogger('asyncio').setLevel(logging.WARNING)


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


def run_server(hostname, port, htpasswd, token_secret, postgres_uri,
               trac_xmlrpc_uri,
               *,
               svn_uri,
               svn_username=None,
               svn_password=None,
               worker_ssh_params,
               enable_cors=False):
    shutdown_timeout = 10

    credentials_checker = HtpasswdCredentialsChecker(htpasswd)
    token_provider = JWTTokenProvider(token_secret)

    loop = asyncio.get_event_loop()
    if False:
        # TODO: asyncssh currently broken due to this
        asyncio.set_event_loop(None)
        # See <https://github.com/python/asyncio/issues/478#issuecomment-268476438>
        # for details.
        asyncio.get_child_watcher().attach_loop(loop)

    _setup_termination(loop=loop)
    _setup_sentry(loop=loop)

    with contextlib.ExitStack() as exit_stack:
        exit_stack.callback(loop.close)

        db = Database(postgres_uri, loop=loop)
        loop.run_until_complete(db.start())
        exit_stack.callback(
            lambda: loop.run_until_complete(db.stop()))

        trac_rpc = ServerProxy(trac_xmlrpc_uri, loop=loop)
        exit_stack.callback(trac_rpc.close)

        async def do_tickets_sync():
            await sync_tickets(
                db, trac_rpc, {'HA#3 linked_ptr': LINKED_PTR_ASSIGNMENT_ID})

        async def do_svn_sync():
            await sync_svn(
                db,
                {LINKED_PTR_PATH: LINKED_PTR_ASSIGNMENT_ID},
                svn_uri=svn_uri,
                svn_username=svn_username,
                svn_password=svn_password,
                loop=loop)

        async def do_check_solutions():
            await check_solutions(db, LINKED_PTR_ASSIGNMENT_ID,
                                  ssh_params=worker_ssh_params, loop=loop)

        async def do_post_reports():
            await report_solutions(
                db, trac_rpc, LINKED_PTR_ASSIGNMENT_ID, loop=loop)

        if False:
            loop.run_until_complete(
                db.get_checkable_solutions(LINKED_PTR_ASSIGNMENT_ID))
            return
        if False:
            loop.run_until_complete(
                check_solutions(db, LINKED_PTR_ASSIGNMENT_ID,
                                ssh_params=worker_ssh_params, loop=loop))
            return
        if False:
            loop.run_until_complete(
                report_solutions(db, trac_rpc, LINKED_PTR_ASSIGNMENT_ID,
                                 loop=loop))
            return

        if _DEBUG_SYNC_TICKETS:
            loop.run_until_complete(do_tickets_sync())
        if _DEBUG_SYNC_SVN:
            loop.run_until_complete(do_svn_sync())

        svn_sync = PeriodicScheduler(do_svn_sync, 30, loop=loop)
        loop.run_until_complete(svn_sync.start())
        exit_stack.callback(lambda: loop.run_until_complete(svn_sync.stop()))

        trac_sync = PeriodicScheduler(do_tickets_sync, 600, loop=loop)
        loop.run_until_complete(trac_sync.start())
        exit_stack.callback(lambda: loop.run_until_complete(trac_sync.stop()))

        check_solutions_sync = PeriodicScheduler(do_check_solutions, 30, loop=loop)
        loop.run_until_complete(check_solutions_sync.start())
        exit_stack.callback(lambda: loop.run_until_complete(check_solutions_sync.stop()))

        #post_reports = PeriodicScheduler(do_post_reports, 30, loop=loop)
        #loop.run_until_complete(post_reports.start())
        #exit_stack.callback(lambda: loop.run_until_complete(post_reports.stop()))

        app = aiohttp.web.Application(loop=loop)

        # Start application server.
        app_server = Server(
            app,
            credentials_checker,
            token_provider,
            db,
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
        "--htpasswd-file",
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
        "--token-secret-file",
        required=True,
        help="Secret used for token generation."
    )
    parser.add_argument(
        "--postgres-uri",
        required=True,
        help="libpq connection string for PostgreSQL."
    )
    parser.add_argument(
        "--trac-xmlrpc-uri",
        required=True,
        help="XMLRPC Trac endpoint with authorization information."
    )
    parser.add_argument(
        "--svn-uri",
        required=True,
        help="Subversion URI."
    )
    parser.add_argument(
        "--svn-username",
        help="Subversion username (if needed)."
    )
    parser.add_argument(
        "--svn-password",
        help="Subversion password (if needed)."
    )
    parser.add_argument(
        "--worker-ssh-host",
    )
    parser.add_argument(
        "--worker-ssh-port",
    )
    parser.add_argument(
        "--worker-ssh-username",
    )
    parser.add_argument(
        "--worker-ssh-known-hosts-file",
    )
    parser.add_argument(
        "--worker-ssh-key",
    )

    args = parser.parse_args()

    _setup_logging(args.log_level)

    try:
        return run_server(
            args.hostname,
            args.port,
            args.htpasswd_file,
            args.token_secret_file,
            args.postgres_uri,
            args.trac_xmlrpc_uri,
            svn_uri=args.svn_uri,
            svn_username=args.svn_username,
            svn_password=args.svn_password,
            worker_ssh_params=dict(
                host=args.worker_ssh_host,
                port=args.worker_ssh_port,
                username=args.worker_ssh_username,
                known_hosts=args.worker_ssh_known_hosts_file,
                client_keys=[args.worker_ssh_key],
            ),
            enable_cors=args.enable_cors)

    except Exception:
        _logger.exception("Server failed")
        return 1


if __name__ == '__main__':
    sys.exit(main())
