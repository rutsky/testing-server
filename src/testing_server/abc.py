import asyncio
from abc import ABC, abstractmethod, abstractproperty

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


class AbstractSubscriber(ABC):

    @abstractproperty
    def queue(self) -> asyncio.Queue:
        pass

    @abstractmethod
    def close(self):
        pass

    @abstractmethod
    def __enter__(self):
        pass

    @abstractmethod
    def __exit__(self):
        pass


class AbstracePublisher(ABC):
    @abstractmethod
    def publish(self, topic, message):
        pass

    @abstractmethod
    def subscribe(self, topic) -> AbstractSubscriber:
        pass
