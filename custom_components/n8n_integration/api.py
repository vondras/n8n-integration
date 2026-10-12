"""Bounded transport with separate discovery and action credentials."""

from __future__ import annotations

import asyncio
import json
import re
from typing import Any
from urllib.parse import quote, urlsplit

import aiohttp

MAX_PAGES = 100
MAX_WORKFLOWS = 5000
MAX_DISCOVERY_BYTES = 8 * 1024 * 1024
MAX_ACTION_BYTES = 256 * 1024
HTTP_METHODS = {"GET", "HEAD", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"}


class N8nIntegrationApiClientError(Exception):
    """Safe, credential-free API error."""


class N8nIntegrationApiClientCommunicationError(N8nIntegrationApiClientError):
    """Request failed or completion is ambiguous."""


class N8nIntegrationApiClientAuthenticationError(N8nIntegrationApiClientError):
    """Authentication was rejected."""


def validate_url(url: str, *, allow_http: bool = False) -> str:
    """Require an origin URL with normal TLS verification."""
    try:
        parts = urlsplit(url)
        valid = (
            parts.scheme in ({"https", "http"} if allow_http else {"https"})
            and parts.hostname
            and parts.port != 0
            and not parts.username
            and not parts.password
            and not parts.fragment
            and not parts.query
            and parts.path in ("", "/")
            and not any(c.isspace() or ord(c) < 32 for c in url)
        )
    except ValueError:
        valid = False
    if not valid:
        raise N8nIntegrationApiClientError(
            "Use an HTTPS origin without credentials, path, query or fragment. "
            "HTTP requires explicit internal-endpoint opt-in."
        )
    return url.rstrip("/")


def validate_headers(headers: Any) -> dict[str, str]:
    """Validate explicit webhook authentication headers."""
    if not isinstance(headers, dict):
        raise N8nIntegrationApiClientError("Webhook headers must be an object")
    forbidden = {
        "x-n8n-api-key",
        "host",
        "content-length",
        "transfer-encoding",
        "connection",
        "cookie",
    }
    for key, value in headers.items():
        if (
            not isinstance(key, str)
            or not re.fullmatch(r"[!#$%&'*+.^_`|~0-9A-Za-z-]+", key)
            or key.lower() in forbidden
            or not isinstance(value, str)
            or any(ord(c) < 32 or ord(c) > 126 for c in value)
        ):
            raise N8nIntegrationApiClientError("Invalid or prohibited webhook header")
    return dict(headers)


def webhook_path(node: dict[str, Any]) -> str:
    """Keep literal paths inside the production webhook route."""
    path = node.get("parameters", {}).get("path")
    if (
        not isinstance(path, str)
        or not path
        or path.startswith("/")
        or any(p in {".", ".."} for p in path.split("/"))
        or any(c in path for c in ("?", "#", "%", "\\", ":"))
        or any(c.isspace() or ord(c) < 32 for c in path)
        or "{{" in path
    ):
        raise N8nIntegrationApiClientError("Webhook requires a literal production path")
    return quote(path, safe="/-_~")


def supported_methods(node: dict[str, Any]) -> list[str]:
    """Read single and multiple-method definitions."""
    params = node.get("parameters", {})
    value = params.get("httpMethod", "GET")
    if params.get("multipleMethods"):
        value = params.get("httpMethods", value)
    values = value if isinstance(value, list) else [value]
    if not values or any(
        not isinstance(v, str) or v.upper() not in HTTP_METHODS for v in values
    ):
        raise N8nIntegrationApiClientError("Webhook has unsupported methods")
    return [v.upper() for v in values]


class N8nIntegrationApiClient:
    """Shared session, bounded bodies, no redirects or retries."""

    def __init__(
        self,
        url: str,
        api_token: str,
        session: aiohttp.ClientSession,
        *,
        allow_http: bool = False,
        discovery_timeout: int = 10,
        action_timeout: int = 60,
        webhook_url: str | None = None,
    ) -> None:
        self._url = validate_url(url, allow_http=allow_http)
        self._webhook_url = validate_url(webhook_url or url, allow_http=allow_http)
        if not 1 <= discovery_timeout <= 60 or not 1 <= action_timeout <= 300:
            raise N8nIntegrationApiClientError("Timeout is outside supported bounds")
        self._api_token = api_token
        self._session = session
        self._discovery_timeout = discovery_timeout
        self._action_timeout = action_timeout

    @property
    def url(self) -> str:
        """Discovery origin."""
        return self._url

    @property
    def webhook_url(self) -> str:
        """Action origin."""
        return self._webhook_url

    async def async_get_workflows(self) -> dict[str, Any]:
        """Fetch pages atomically; a failure never becomes an empty result."""
        workflows: list[dict[str, Any]] = []
        seen: set[str] = set()
        params = {"active": "true", "excludePinnedData": "true", "limit": "100"}
        for _ in range(MAX_PAGES):
            page = await self._request(
                "GET", f"{self._url}/api/v1/workflows", discovery=True, params=params
            )
            if not isinstance(page, dict) or not isinstance(page.get("data"), list):
                raise N8nIntegrationApiClientError("Invalid workflow list response")
            if any(
                not isinstance(w, dict) or not isinstance(w.get("id"), str)
                for w in page["data"]
            ):
                raise N8nIntegrationApiClientError("Invalid workflow metadata")
            workflows.extend(page["data"])
            if len(workflows) > MAX_WORKFLOWS:
                raise N8nIntegrationApiClientError("Workflow result limit exceeded")
            cursor = page.get("nextCursor")
            if cursor is None or cursor == "":
                return {"data": workflows}
            if not isinstance(cursor, str) or cursor in seen:
                raise N8nIntegrationApiClientError(
                    "Invalid or repeated pagination cursor"
                )
            seen.add(cursor)
            params = {**params, "cursor": cursor}
        raise N8nIntegrationApiClientError("Workflow page limit exceeded")

    async def async_get_workflow(self, workflow_id: str) -> dict[str, Any]:
        """Read current metadata immediately before triggering."""
        result = await self._request(
            "GET",
            f"{self._url}/api/v1/workflows/{quote(workflow_id, safe='')}",
            discovery=True,
            params={"excludePinnedData": "true"},
        )
        if not isinstance(result, dict) or result.get("id") != workflow_id:
            raise N8nIntegrationApiClientError("Invalid workflow detail response")
        return result

    async def async_trigger_webhook(
        self,
        webhook_node: dict[str, Any],
        options: dict[str, Any],
        payload: dict[str, Any] | None = None,
        method: str | None = None,
    ) -> Any:
        """Send one request; coordinator checks authorization and selection."""
        available = supported_methods(webhook_node)
        chosen = method.upper() if method else available[0]
        if chosen not in available:
            raise N8nIntegrationApiClientError(
                "Requested method is not supported by this node"
            )
        if payload is not None and (
            not isinstance(payload, dict)
            or any(not isinstance(k, str) for k in payload)
        ):
            raise N8nIntegrationApiClientError(
                "Payload must be an object with string keys"
            )
        try:
            json.dumps(payload, allow_nan=False)
        except (TypeError, ValueError) as err:
            raise N8nIntegrationApiClientError(
                "Payload must contain JSON-compatible values"
            ) from err
        params = None
        if chosen in {"GET", "HEAD"}:
            if payload and any(isinstance(v, (dict, list)) for v in payload.values()):
                raise N8nIntegrationApiClientError(
                    "GET/HEAD query values must be scalars"
                )
            params = {
                k: json.dumps(v) if not isinstance(v, str) else v
                for k, v in (payload or {}).items()
            }
        return await self._request(
            chosen,
            f"{self._webhook_url}/webhook/{webhook_path(webhook_node)}",
            headers=validate_headers(options.get("headers", {})),
            params=params,
            data=None if chosen in {"GET", "HEAD"} else payload,
        )

    async def _request(
        self,
        method: str,
        url: str,
        *,
        discovery: bool = False,
        headers: dict[str, str] | None = None,
        params: dict[str, str] | None = None,
        data: dict[str, Any] | None = None,
    ) -> Any:
        limit = MAX_DISCOVERY_BYTES if discovery else MAX_ACTION_BYTES
        timeout = self._discovery_timeout if discovery else self._action_timeout
        try:
            async with asyncio.timeout(timeout):
                async with self._session.request(
                    method,
                    url,
                    headers={"X-N8N-API-KEY": self._api_token}
                    if discovery
                    else headers,
                    params=params,
                    json=data,
                    allow_redirects=False,
                ) as response:
                    if 300 <= response.status < 400:
                        raise N8nIntegrationApiClientError(
                            "Redirect rejected; configure a direct API/webhook endpoint"
                        )
                    if response.status in {401, 403}:
                        raise N8nIntegrationApiClientAuthenticationError(
                            "Endpoint rejected authentication"
                        )
                    if response.status >= 400:
                        raise N8nIntegrationApiClientError(
                            f"Endpoint returned HTTP {response.status}"
                        )
                    mime = (
                        response.headers.get("Content-Type", "")
                        .split(";", 1)[0]
                        .strip()
                        .lower()
                    )
                    is_json = mime == "application/json" or mime.endswith("+json")
                    if response.status == 204 or method == "HEAD":
                        return None
                    if (
                        not discovery
                        and not is_json
                        and not mime.startswith("text/")
                        and response.content_length != 0
                    ):
                        raise N8nIntegrationApiClientError(
                            "Binary or unspecified action response is unsupported"
                        )
                    if (
                        response.content_length is not None
                        and response.content_length > limit
                    ):
                        raise N8nIntegrationApiClientError(
                            "Response size limit exceeded"
                        )
                    body = bytearray()
                    async for chunk in response.content.iter_chunked(65536):
                        body.extend(chunk)
                        if len(body) > limit:
                            raise N8nIntegrationApiClientError(
                                "Response size limit exceeded"
                            )
                    if not body:
                        if discovery:
                            raise N8nIntegrationApiClientError(
                                "Empty discovery response"
                            )
                        return None
                    if discovery and not is_json:
                        raise N8nIntegrationApiClientError(
                            "Discovery endpoint must return JSON"
                        )
                    try:
                        text = body.decode("utf-8")
                        return json.loads(text) if is_json else text
                    except (UnicodeError, ValueError) as err:
                        raise N8nIntegrationApiClientError(
                            "Malformed endpoint response"
                        ) from err
        except TimeoutError:
            message = (
                "Discovery timed out"
                if discovery
                else "Action timed out; completion is unknown. The workflow may still run. No retry was sent."
            )
            raise N8nIntegrationApiClientCommunicationError(message) from None
        except aiohttp.ClientError:
            raise N8nIntegrationApiClientCommunicationError(
                "Endpoint communication failed; action completion may be unknown"
            ) from None
