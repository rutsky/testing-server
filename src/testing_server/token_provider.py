import datetime
import logging

import jwt

import testing_server
from .abc import AbstractTokenProvider

__all__ = ("JWTTokenProvider",)


_logger = logging.getLogger(__name__)


class JWTTokenProvider(AbstractTokenProvider):

    def __init__(self,
                 secret,
                 token_expire_period=datetime.timedelta(days=30)):
        self._secret = secret
        self._token_expire_period = token_expire_period

    async def generate_token(self, login):
        issuer = testing_server.__name__ + ':' + testing_server.__version__
        payload = {
            'login': login,
            'iat': datetime.datetime.utcnow(),
            'exp': datetime.datetime.now() + self._token_expire_period,
            'iss': issuer,
        }
        return jwt.encode(payload, self._secret)

    async def validate_token(self, token):
        try:
            return jwt.decode(token, self._secret)
        except jwt.InvalidTokenError:
            return None
