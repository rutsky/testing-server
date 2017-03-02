import asyncio
import tempfile
import json
import os

import pytest
import aiohttp
from aiohttp import hdrs

from testing_server.server import Server
from testing_server.token_provider import JWTTokenProvider
from testing_server.credentials_checker import HtpasswdCredentialsChecker


@pytest.fixture
def token_provider():
    return JWTTokenProvider(secret='secret')


@pytest.fixture
def credentials_checker():
    with tempfile.NamedTemporaryFile() as f:
        f.write(b'user:password\n')
        f.flush()
        os.fsync(f.fileno())

        yield HtpasswdCredentialsChecker(f.name)


@pytest.fixture
def client(loop: asyncio.BaseEventLoop, test_server, test_client,
           credentials_checker, token_provider):
    app = aiohttp.web.Application(loop=loop)
    db = None  # TODO
    app_server = Server(app, credentials_checker, token_provider, db, loop=loop)
    loop.run_until_complete(app_server.start())
    server = loop.run_until_complete(test_server(app))
    client = loop.run_until_complete(test_client(server))

    yield client

    loop.run_until_complete(app_server.stop())


async def get_success_resp_data(resp: aiohttp.ClientResponse):
    assert resp.status // 100 == 2, resp
    data = await resp.json()
    assert 'status' in data, resp
    assert data['status'] == 'success', resp
    assert 'data' in data
    return data['data']


async def test_server_setup(client):
    resp = await client.get('/')
    data = await get_success_resp_data(resp)
    assert "Testing server" in data


async def test_server_auth(client):
    resp = await client.post(
        '/api/login',
        data=json.dumps(dict(login='user', password='password')),
        headers={'Content-Type': 'application/json'})
    token = await get_success_resp_data(resp)
    assert token

    resp = await client.get(
        '/api/check_token',
        headers={hdrs.AUTHORIZATION: 'Bearer {}'.format(token)})
    message = await get_success_resp_data(resp)
    assert 'valid' in message
