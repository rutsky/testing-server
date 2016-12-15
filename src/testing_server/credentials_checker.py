from passlib.apache import HtpasswdFile

from .abc import AbstractCredentialsChecker


class HtpasswdCredentialsChecker(AbstractCredentialsChecker):

    def __init__(self, htpasswd_file):
        self._ht = HtpasswdFile(htpasswd_file)

    async def check_password(self, login, password):
        return self._ht.check_password(login, password)
