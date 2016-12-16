import logging

import aiohttp.hdrs
import aiohttp.web
import aiohttp_cors

from . import abc
from .jsend import JSendFail, jsend_handler
from .auth_mixin import AuthMixin, requires_login

__all__ = ('Server',)


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
            '/users', self.handler_not_implemented)
        self._app.router.add_get(
            '/users/{username}/{home_assignment}/{revision}/',
            self.handler_not_implemented)

        self._app.router.add_get('/ws', self.handler_not_implemented)

    async def stop(self):
        pass

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
    async def post_login(self, request: aiohttp.web.Request):
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

    @jsend_handler
    async def handler_not_implemented(self, request):
        raise JSendFail("Not implemented")
