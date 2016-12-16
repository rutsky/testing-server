import functools
import json
import logging
import traceback

import aiohttp.web
from aiohttp import hdrs

__all__ = ('JSendError', 'JSendFail', 'jsend_handler')

JSEND_DUMP_TRACEBACKS = False

_logger = logging.getLogger(__name__)


class JSendError(Exception):
    """Internal server error wrapper"""

    def __init__(self, message, code=None, data=None, http_code=500):
        self.message = message
        self.code = code
        self.data = data
        self.http_code = http_code


class JSendFail(Exception):
    """Bad request error wrapper"""

    def __init__(self, message=None, data=None, http_code=400):
        if message is not None:
            if data is None:
                self.data = dict(message=message)
            else:
                self.data = dict(message=message).update(self.data)
        else:
            self.data = data
        self.http_code = http_code


def jsend_handler(handler):
    @functools.wraps(handler)
    async def wrapper(*args):
        response = {
            'status': 'success'
        }

        http_code = 200
        headers = None

        try:
            response['data'] = await handler(*args)

        except JSendFail as ex:
            http_code = ex.http_code
            response['status'] = 'fail'
            if ex.data is not None:
                response['data'] = ex.data

        except JSendError as ex:
            http_code = ex.http_code
            response['status'] = 'error'
            response['message'] = ex.message

            if ex.code is not None:
                response['code'] = ex.code
            if ex.data is not None:
                response['data'] = ex.data

            _logger.exception(
                "Handler raised exception: {}".format(ex.message))

        except aiohttp.web.HTTPException as ex:
            headers = ex.headers
            if hdrs.CONTENT_TYPE in headers:
                del headers[hdrs.CONTENT_TYPE]

            http_code = ex.status_code

            response['status'] = 'fail'
            response['data'] = dict(message=ex.text)

        except Exception:
            http_code = 500
            response['status'] = 'error'
            message = "Internal server error."

            if JSEND_DUMP_TRACEBACKS:
                message += "\n" + traceback.format_exc()

            response['message'] = message

            _logger.exception(
                "Handler raised unknown exception.")

        try:
            text = json.dumps(response)
        except TypeError:
            _logger.exception("Response serialization failed.")

            return aiohttp.web.json_response(
                data={
                    'status': 'error',
                    'message': "Internal server error: failed to "
                               "JSON-serialize response."
                },
                status=500)

        return aiohttp.web.json_response(
            text=text,
            status=http_code,
            headers=headers
        )

    return wrapper
