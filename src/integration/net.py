import contextlib

import httpx

_UA = "Xeria-Launcher/2.504"

_client = None


def client():
    global _client
    if _client is None:
        _client = httpx.Client(
            headers={"User-Agent": _UA},
            timeout=httpx.Timeout(30.0, connect=10.0),
            follow_redirects=True,
            limits=httpx.Limits(
                max_connections=32,
                max_keepalive_connections=24,
                keepalive_expiry=60.0,
            ),
            http2=True,
        )
    return _client


def get(url, **kwargs):
    return client().get(url, **kwargs)


def post(url, data=None, json=None, **kwargs):
    return client().post(url, data=data, json=json, **kwargs)


def stream(method, url, **kwargs):
    return client().stream(method, url, **kwargs)


def close():
    global _client
    if _client is not None:
        with contextlib.suppress(Exception):
            _client.close()
        _client = None
