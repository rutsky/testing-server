from abc import ABC, abstractmethod

__all__ = ('AbstractCredentialsChecker', 'AbstractTokenProvider')


class AbstractCredentialsChecker(ABC):

    @abstractmethod
    async def check_password(self, login, password):
        """Returns is password matches login."""


class AbstractTokenProvider(ABC):

    @abstractmethod
    async def generate_token(self, login):
        """Returns: auth token"""

    @abstractmethod
    async def validate_token(self, token):
        """Returns decoded token if it is valid, None otherwise."""
