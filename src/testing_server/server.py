import asyncio
import logging
import json

import aiohttp
import aiohttp.hdrs
from aiohttp import web
from aiohttp import WSMsgType
import aiohttp_cors
import async_timeout

from . import abc
from .jsend import JSendFail, jsend_handler
from .auth_mixin import AuthMixin, requires_login

__all__ = ('Server',)

_PING_INTERVAL = 30
_WS_AUTH_TIMEOUT = 30

_logger = logging.getLogger(__name__)


class Server(AuthMixin):

    def __init__(self,
                 app,
                 credentials_checker: abc.AbstractCredentialsChecker,
                 token_provider: abc.AbstractTokenProvider,
                 *,
                 loop,
                 enable_cors=False):
        super().__init__(token_provider)

        self._app = app
        self._credentials_checker = credentials_checker
        self._loop = loop
        self._enable_cors = enable_cors

        self._websockets = set()

    async def start(self):
        if self._enable_cors:
            cors = aiohttp_cors.setup(self._app, defaults={
                "*": aiohttp_cors.ResourceOptions(
                    allow_credentials=True,
                    expose_headers="*",
                    allow_headers="*"),
            })

            def wrap(route):
                cors.add(route)
        else:
            wrap = lambda route: route

        wrap(self._app.router.add_get('/', self.get_default))

        api_prefix = '/api'
        wrap(self._app.router.add_post(
            api_prefix + '/login', self.post_login))

        wrap(self._app.router.add_get(
            api_prefix + '/check_token', self.get_check_token))

        self._app.router.add_get(
            api_prefix + '/ws', self.get_ws)

        self._app.router.add_get(
            '/users', self.handler_not_implemented)
        self._app.router.add_get(
            '/users/{username}/{home_assignment}/{revision}/',
            self.handler_not_implemented)

        self._app.router.add_get('/ws', self.handler_not_implemented)

    async def stop(self):
        while self._websockets:
            ws = self._websockets.pop()
            await ws.close(
                code=aiohttp.WSCloseCode.GOING_AWAY,
                message='Server shutdown')

    async def _json_body(self, request):
        ctype = request.headers.get(aiohttp.hdrs.CONTENT_TYPE, '').lower()
        if 'json' not in ctype:
            raise JSendFail("Expected Content-Type header value "
                            "'application/json'")

        try:
            json_body = await request.json()
        except Exception:
            raise JSendFail("Failed to parse JSON request body.")

        return json_body

    @jsend_handler
    async def get_default(self, request):
        return "Testing server."

    @jsend_handler
    @requires_login
    async def get_check_token(self, request, token_payload):
        return "Token is valid."

    @jsend_handler
    async def post_login(self, request: web.Request):
        json_body = await self._json_body(request)

        if not isinstance(json_body, dict):
            raise JSendFail("Request JSON body is not object.")

        login = json_body.get('login')
        if login is None:
            raise JSendFail(
                "Request JSON body doesn't have 'login' attribute.")

        password = json_body.get('password')
        if password is None:
            raise JSendFail(
                "Request JSON body doesn't have 'password' attribute.")

        valid = await self._credentials_checker.check_password(login, password)
        if not valid:
            logging.info("Authentication failed for user {!r}".format(login))
            raise JSendFail(
                "Your user name and password don't match.",
                http_code=400)
        else:
            logging.info("Authentication succeed for user {!r}".format(login))

        token = (await self.token_provider.generate_token(login)).decode()

        return token

    async def get_ws(self, request: web.Request):
        ws = web.WebSocketResponse()
        await ws.prepare(request)

        self._websockets.add(ws)

        async def send_pings(ws: web.WebSocketResponse,
                             ping_interval=_PING_INTERVAL):
            while True:
                try:
                    await ws.ping()

                except asyncio.CancelledError:
                    return

                except RuntimeError:
                    _logger.exception(
                        "Exception during ws.ping(). "
                        "May be closing web socket? Skipping...")

                try:
                    await asyncio.sleep(ping_interval)
                except asyncio.CancelledError:
                    return

        ping_sender_task = self._loop.create_task(send_pings(ws))

        def get_msg_payload(msg):
            assert msg.tp == WSMsgType.TEXT
            try:
                json_body = json.loads(msg.data)
            except json.JSONDecodeError:
                _logger.exception(
                    "Can't decode JSON from web socket: {!r}".format(
                        msg.data
                    ))
                return None

            required_keys = frozenset(['token', 'type'])
            if required_keys.difference(frozenset(json_body.keys())):
                _logger.error(
                    "Web socket message doesn't have all required fields: "
                    "{!r}".format(json_body))
                return None

            return json_body

        try:
            try:
                with async_timeout.timeout(_WS_AUTH_TIMEOUT, loop=self._loop):
                    auth_msg = await ws.receive()
            except TimeoutError:
                _logger.error(
                    "Timeout obtaining authentication message in WS. "
                    "Closing WS.")
                return ws

            if auth_msg.type != WSMsgType.TEXT:
                _logger.error(
                    "Authentication WS message has type {!r}, "
                    "but expected {!r}. Closing WS.".format(
                        auth_msg.type, WSMsgType.TEXT))
                return ws

            auth_data = get_msg_payload(auth_msg)
            if auth_data is None:
                return ws

            auth_type_string = 'AUTH'

            if auth_data['type'] != auth_type_string:
                _logger.error(
                    "Authentication WS message payload has type field {!r}, "
                    "but expected {!r}. Closing WS.".format(
                        auth_data['type'], auth_type_string))
                return ws

            payload = self.token_provider.validate_token(auth_data['token'])
            if payload is None:
                _logger.error(
                    "Token sent over WS is invalid.")
                await ws.send_json({
                    'status': 'fail',
                    'data': {
                        'message': 'Invalid token.',
                    },
                })
                return ws
            else:
                _logger.info(
                    "User {!r} authenticated.".format(payload['login']))
                await ws.send_json({
                    'status': 'success',
                    'message': 'Token is valid.',
                })

            async for msg in ws:
                if msg.tp == WSMsgType.TEXT:
                    json_body = get_msg_payload(msg)
                    if json_body is None:
                        continue

                    _logger.debug("Got Web Socket message: {!r}".format(
                        json_body))

                elif msg.tp == aiohttp.WSMsgType.ERROR:
                    _logger.error(
                        "Got an exception in web socket",
                        exc_info=ws.exception())

                else:
                    _logger.error(
                        "Unhandled web socket message with type {!r}".format(
                            msg.tp))

        finally:
            ping_sender_task.cancel()
            await ping_sender_task

            await ws.close()

            # May be already removed is server is shutting down.
            self._websockets.discard(ws)

        return ws

    @jsend_handler
    async def handler_not_implemented(self, request):
        raise JSendFail("Not implemented")
