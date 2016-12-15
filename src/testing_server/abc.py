from abc import ABC, abstractmethod

__all__ = ('AbstractCredentialsChecker',)


class AbstractCredentialsChecker(ABC):

    @abstractmethod
    async def check_password(self, login, password):
        """Returns is password matches login."""
