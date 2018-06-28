import re
import requests
import time

from checkout_sdk import errors, constants, HttpResponse
from urllib.parse import urljoin

http_headers_default = {
    'user-agent': 'checkout-sdk-python/{}'.format(constants.VERSION)
}

SNAKE_CASE_REGEX = re.compile(r'_([a-z])')


class HttpClient:
    def __init__(self, config):
        self.config = config

        # init Http Session (for pooling)
        self._session = requests.Session()

        # interceptor call is a mirror by default
        self.interceptor = lambda url, headers, request: (
            url, headers, request)

    @property
    def config(self):
        return self._config

    @config.setter
    def config(self, value):
        self._config = value

    @property
    def headers(self):
        headers = http_headers_default.copy()
        headers['authorization'] = self.config.secret_key
        return headers

    def get(self, path):
        return self._request(path)

    def post(self, path, request):
        return self._request(path, request)

    def close_session(self):
        self._session.close()

    def _request(self, path, request=None):
        start = time.time()

        # convert all snake-case to camelCase
        if request is not None:
            request = self._convert_json(request, self._snake_to_camel_case)

        # call the interceptor as a hook to override the url, headers and/or request
        url, headers, request = self.interceptor(
            urljoin(self.config.api_base_url, path), self.headers, request)

        try:
            r = self._session.request(
                method='POST' if request else 'GET',
                url=url,
                json=request,
                headers=headers,
                timeout=self.config.timeout/1000)
            elapsed = '{0:.2f}'.format((time.time() - start)*1000)

            r.raise_for_status()
            try:
                body = r.json()
            except ValueError:
                body = None

            return HttpResponse(r.status_code, r.headers, body, elapsed)
        except requests.exceptions.HTTPError as e:
            status_code_switch = {
                400: lambda: errors.BadRequestError,
                401: lambda: errors.AuthenticationError,
                404: lambda: errors.ResourceNotFoundError,
                422: lambda: errors.TooManyRequestsError,
                500: lambda: errors.ApiError
            }
            jsonResponse = e.response.json()
            errorCls = status_code_switch.get(e.response.status_code,
                                              errors.ApiError)()
            raise errorCls(
                event_id=jsonResponse['eventId'],
                http_status=e.response.status_code,
                error_code=jsonResponse['errorCode'],
                message=jsonResponse['message'],
                elapsed=elapsed)
        except requests.exceptions.Timeout as e:
            elapsed = time.time() - start
            raise errors.Timeout(elapsed=elapsed)
        except requests.exceptions.RequestException:
            raise errors.ApiError(
                message='Unexpected API connection error - please contact support@checkout.com')

    def _snake_to_camel_case(self, name):
        return SNAKE_CASE_REGEX.sub(lambda x: x.group(1).upper(), name)

    def _convert_json(self, json, convert):
        output = {}
        for k, v in json.items():
            output[convert(k)] = self._convert_json(
                v, convert) if isinstance(v, dict) else v
        return output
