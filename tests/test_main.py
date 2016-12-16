import asyncio

import pytest
import aiohttp

from testing_server.server import Server


@pytest.fixture
def client(loop: asyncio.BaseEventLoop, test_server, test_client):
    app = aiohttp.web.Application(loop=loop)
    app_server = Server(app, loop=loop)
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
