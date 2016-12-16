import functools

from aiohttp import web, hdrs

from .abc import AbstractTokenProvider

__all__ = ('AuthMixin', 'requires_login')

AUTH_HEADERS = {
    hdrs.WWW_AUTHENTICATE: 'Bearer'
}


def requires_login(f):
    @functools.wraps(f)
    async def hanlder_wrapper(self: AuthMixin, request: web.Request):
        if hdrs.AUTHORIZATION not in request.headers:
            raise web.HTTPUnauthorized(
                text="'Authorization' header is missing.",
                headers=AUTH_HEADERS,
            )
        auth_type, *token = request.headers[hdrs.AUTHORIZATION].split(
            maxsplit=1)
        if not token or auth_type.lower() != 'bearer':
            raise web.HTTPUnauthorized(
                text="'Authorization' header is not in 'Bearer TOKEN' "
                     "format.",
                headers=AUTH_HEADERS,
            )
        token = token[0].strip()

        token_payload = await self.token_provider.validate_token(token)
        if token_payload is None:
            raise web.HTTPUnauthorized(
                text="Invalid token",
                headers=AUTH_HEADERS,
            )

        return await f(self, request, token_payload)

    return hanlder_wrapper


class AuthMixin:
    def __init__(self, token_provider: AbstractTokenProvider):
        self.__token_provider = token_provider

    @property
    def token_provider(self):
        return self.__token_provider
