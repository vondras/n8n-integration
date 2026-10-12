"""Transport acceptance tests with no production credentials or actions."""

import json
from unittest.mock import patch

import aiohttp
import pytest
from aiohttp import web

from custom_components.n8n_integration import api


class Body:
    def __init__(self, body):
        self.body = body

    async def iter_chunked(self, size):
        for start in range(0, len(self.body), size):
            yield self.body[start : start + size]


class Response:
    def __init__(self, body=b"{}", status=200, mime="application/json", length=True):
        self.status = status
        self.headers = {"Content-Type": mime}
        self.content_length = len(body) if length else None
        self.content = Body(body)
        self.closed = False

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        self.closed = True


class Session:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def request(self, *args, **kwargs):
        self.calls.append((args, kwargs))
        value = self.responses.pop(0)
        if isinstance(value, Exception):
            raise value
        return value


def client(responses):
    session = Session(responses)
    return api.N8nIntegrationApiClient(
        "https://n8n.example", "dummy-discovery-secret", session
    ), session


def node(method="POST", path="test-action"):
    return {"id": "node", "parameters": {"httpMethod": method, "path": path}}


@pytest.mark.parametrize(
    "url",
    [
        "http://example.com",
        "https://user:secret@example.com",
        "https://example.com/#x",
        "https://example.com/?x=1",
        "https://example.com/path",
        "https://example.com:abc",
        "https://example.com\\@evil.com",
    ],
)
def test_invalid_url(url):
    # Backslash userinfo URLs must fail, like ordinary embedded credentials.
    with pytest.raises(api.N8nIntegrationApiClientError):
        api.validate_url(url)


def test_http_opt_in():
    assert (
        api.validate_url("http://internal:5678/", allow_http=True)
        == "http://internal:5678"
    )


async def test_redirect_rejected_and_response_closed():
    response = Response(status=302)
    c, s = client([response])
    with pytest.raises(api.N8nIntegrationApiClientError, match="Redirect"):
        await c.async_get_workflows()
    assert s.calls[0][1]["allow_redirects"] is False
    assert response.closed


async def test_real_redirect_key_does_not_cross_origins(aiohttp_server, socket_enabled):
    leaked = []

    async def destination(request):
        leaked.append(request.headers.get("X-N8N-API-KEY"))
        return web.json_response({"data": []})

    target = web.Application()
    target.router.add_get("/destination", destination)
    target_server = await aiohttp_server(target)

    async def redirect(request):
        raise web.HTTPFound(str(target_server.make_url("/destination")))

    source = web.Application()
    source.router.add_get("/api/v1/workflows", redirect)
    source_server = await aiohttp_server(source)
    async with aiohttp.ClientSession() as session:
        c = api.N8nIntegrationApiClient(
            str(source_server.make_url("/")).rstrip("/"),
            "dummy-only",
            session,
            allow_http=True,
        )
        with pytest.raises(api.N8nIntegrationApiClientError, match="Redirect"):
            await c.async_get_workflows()
    assert leaked == []


async def test_pagination():
    c, s = client(
        [
            Response(
                json.dumps({"data": [{"id": "one"}], "nextCursor": "next"}).encode()
            ),
            Response(b'{"data": []}'),
        ]
    )
    assert (await c.async_get_workflows())["data"] == [{"id": "one"}]
    assert s.calls[1][1]["params"]["cursor"] == "next"
    assert all(
        call[1]["headers"] == {"X-N8N-API-KEY": "dummy-discovery-secret"}
        for call in s.calls
    )


async def test_repeated_cursor_and_page_bound():
    body = b'{"data": [], "nextCursor": "repeat"}'
    c, _ = client([Response(body), Response(body)])
    with pytest.raises(api.N8nIntegrationApiClientError, match="repeated"):
        await c.async_get_workflows()
    c, _ = client([Response(body)])
    with (
        patch.object(api, "MAX_PAGES", 1),
        pytest.raises(api.N8nIntegrationApiClientError, match="page limit"),
    ):
        await c.async_get_workflows()


async def test_result_bound_and_invalid_page():
    c, _ = client([Response(b'{"data": [{"id":"one"},{"id":"two"}]}')])
    with (
        patch.object(api, "MAX_WORKFLOWS", 1),
        pytest.raises(api.N8nIntegrationApiClientError, match="result limit"),
    ):
        await c.async_get_workflows()
    c, _ = client([Response(b'{"wrong":[]}')])
    with pytest.raises(api.N8nIntegrationApiClientError):
        await c.async_get_workflows()


@pytest.mark.parametrize(
    ("body", "status", "mime", "expected"),
    [
        (b'{"ok": true}', 200, "application/json; charset=utf-8", {"ok": True}),
        (b'{"ok": true}', 200, "application/problem+json", {"ok": True}),
        (b"hello", 200, "text/plain", "hello"),
        (b"", 204, "", None),
        (b"", 200, "text/plain", None),
    ],
)
async def test_supported_responses(body, status, mime, expected):
    response = Response(body, status, mime)
    c, s = client([response])
    assert (
        await c.async_trigger_webhook(
            node(),
            {"headers": {"X-Halloween-Token": "dummy-webhook-secret"}},
            {"message": "hi"},
        )
        == expected
    )
    call = s.calls[0][1]
    assert call["headers"] == {"X-Halloween-Token": "dummy-webhook-secret"}
    assert call["json"] == {"message": "hi"}
    assert "_last_triggered_at" not in (call["params"] or {})
    assert response.closed


@pytest.mark.parametrize(
    ("body", "mime", "length", "match"),
    [
        (b"invalid", "application/json", True, "Malformed"),
        (b"MP3", "audio/mpeg", True, "Binary"),
        (b"x" * 12, "text/plain", True, "size"),
        (b"x" * 12, "text/plain", False, "size"),
    ],
)
async def test_bad_responses(body, mime, length, match):
    response = Response(body, mime=mime, length=length)
    c, _ = client([response])
    with (
        patch.object(api, "MAX_ACTION_BYTES", 10),
        pytest.raises(api.N8nIntegrationApiClientError, match=match),
    ):
        await c.async_trigger_webhook(node(), {})
    assert response.closed


async def test_timeout_one_action_no_secrets():
    c, s = client([TimeoutError("dummy-discovery-secret dummy-webhook-secret")])
    with pytest.raises(
        api.N8nIntegrationApiClientCommunicationError, match="completion is unknown"
    ) as error:
        await c.async_trigger_webhook(
            node(), {"headers": {"X-Token": "dummy-webhook-secret"}}
        )
    assert len(s.calls) == 1
    assert "dummy-" not in str(error.value)


async def test_get_query_and_method_validation():
    c, s = client([Response()])
    await c.async_trigger_webhook(node(["GET", "POST"]), {}, {"count": 3}, "GET")
    assert s.calls[0][1]["params"] == {"count": "3"}
    assert s.calls[0][1]["json"] is None
    with pytest.raises(api.N8nIntegrationApiClientError, match="method"):
        await c.async_trigger_webhook(node("POST"), {}, {}, "DELETE")
    with pytest.raises(api.N8nIntegrationApiClientError, match="object"):
        await c.async_trigger_webhook(node(), {}, ["bad"])
    with pytest.raises(api.N8nIntegrationApiClientError, match="scalars"):
        await c.async_trigger_webhook(node("GET"), {}, {"nested": {}})
    assert len(s.calls) == 1


@pytest.mark.parametrize(
    "path",
    [
        "../api/v1",
        "/absolute",
        "x?token=y",
        "https://evil",
        "x%2fy",
        "{{ $json.path }}",
    ],
)
def test_invalid_webhook_path(path):
    with pytest.raises(api.N8nIntegrationApiClientError):
        api.webhook_path(node(path=path))


@pytest.mark.parametrize(
    "headers",
    [{"X-N8N-API-KEY": "x"}, {"Host": "evil"}, {"X-Token": "x\r\ny"}, {"X Token": "x"}],
)
def test_invalid_auth(headers):
    with pytest.raises(api.N8nIntegrationApiClientError):
        api.validate_headers(headers)
