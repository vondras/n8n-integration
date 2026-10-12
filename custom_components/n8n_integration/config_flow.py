"""Explicit selection and masked credentials for n8n."""

from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any

import probatio as vol
from homeassistant import config_entries
from homeassistant.const import CONF_API_TOKEN, CONF_URL
from homeassistant.core import callback
from homeassistant.helpers import selector
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api import (
    N8nIntegrationApiClient,
    N8nIntegrationApiClientAuthenticationError,
    N8nIntegrationApiClientCommunicationError,
    N8nIntegrationApiClientError,
    validate_headers,
    validate_url,
)
from .const import DOMAIN
from .selection import WEBHOOK, candidates


def connection_schema(defaults: dict[str, Any], *, options: bool = False) -> vol.Schema:
    """Never place stored credentials in form defaults."""
    return vol.Schema(
        {
            vol.Required(CONF_URL, default=defaults.get(CONF_URL, "")): str,
            vol.Required(
                "webhook_url",
                default=defaults.get("webhook_url", defaults.get(CONF_URL, "")),
            ): str,
            (vol.Optional if options else vol.Required)(
                CONF_API_TOKEN
            ): selector.TextSelector(
                selector.TextSelectorConfig(type=selector.TextSelectorType.PASSWORD)
            ),
            vol.Required("allow_http", default=defaults.get("allow_http", False)): bool,
            vol.Required(
                "discovery_timeout", default=defaults.get("discovery_timeout", 10)
            ): vol.All(vol.Coerce(int), vol.Range(min=1, max=60)),
            vol.Required(
                "action_timeout", default=defaults.get("action_timeout", 60)
            ): vol.All(vol.Coerce(int), vol.Range(min=1, max=300)),
            vol.Required(
                "poll_interval", default=defaults.get("poll_interval", 300)
            ): vol.All(vol.Coerce(int), vol.Range(min=30, max=86400)),
        }
    )


class SelectionFlow:
    """Shared workflow, node and per-node auth selection steps."""

    hass: Any
    async_show_form: Any
    _finish: Any
    _connection: dict[str, Any]
    _settings: dict[str, Any]
    _discovered: dict[str, Any]
    _auth_keys: list[str]
    _auth_index: int

    async def _connect(
        self, user_input: dict[str, Any], previous: Mapping[str, Any]
    ) -> None:
        self._connection = {**previous, **user_input}
        if not user_input.get(CONF_API_TOKEN) and previous.get(CONF_API_TOKEN):
            self._connection[CONF_API_TOKEN] = previous[CONF_API_TOKEN]
        self._connection[CONF_URL] = validate_url(
            self._connection[CONF_URL],
            allow_http=self._connection.get("allow_http", False),
        )
        self._connection["webhook_url"] = validate_url(
            self._connection["webhook_url"],
            allow_http=self._connection.get("allow_http", False),
        )
        client = N8nIntegrationApiClient(
            url=self._connection[CONF_URL],
            api_token=self._connection[CONF_API_TOKEN],
            session=async_get_clientsession(self.hass),
            allow_http=self._connection.get("allow_http", False),
            webhook_url=self._connection["webhook_url"],
            discovery_timeout=self._connection["discovery_timeout"],
            action_timeout=self._connection["action_timeout"],
        )
        self._discovered = await client.async_get_workflows()
        for field in ("discovery_timeout", "action_timeout", "poll_interval"):
            self._settings[field] = self._connection.pop(field)

    async def async_step_workflows(
        self, user_input: dict[str, Any] | None = None
    ) -> Any:
        """Default to no workflows; choose only eligible published definitions."""
        choices = {w["id"]: w["name"] for w, _ in candidates(self._discovered).values()}
        errors = {}
        if user_input is not None:
            values = user_input.get("workflows", [])
            if not set(values) <= choices.keys():
                errors["base"] = "invalid_selection"
            else:
                self._settings["workflows"] = values
                return await self.async_step_nodes()
        return self.async_show_form(
            step_id="workflows",
            data_schema=vol.Schema(
                {
                    vol.Required(
                        "workflows",
                        default=[
                            v
                            for v in self._settings.get("workflows", [])
                            if v in choices
                        ],
                    ): selector.SelectSelector(
                        selector.SelectSelectorConfig(
                            options=[
                                selector.SelectOptionDict(value=k, label=v)
                                for k, v in choices.items()
                            ],
                            multiple=True,
                        )
                    )
                }
            ),
            errors=errors,
        )

    async def async_step_nodes(self, user_input: dict[str, Any] | None = None) -> Any:
        """Require per-node selection, including form links."""
        choices = {
            k: f"{w['name']}: {n.get('name', n['id'])}"
            for k, (w, n) in candidates(self._discovered).items()
            if w["id"] in self._settings["workflows"]
        }
        errors = {}
        if user_input is not None:
            values = user_input.get("nodes", [])
            if not set(values) <= choices.keys():
                errors["base"] = "invalid_selection"
            else:
                self._settings["nodes"] = values
                self._settings["webhook_headers"] = {
                    k: v
                    for k, v in self._settings.get("webhook_headers", {}).items()
                    if k in values
                }
                self._auth_keys = [
                    k
                    for k in values
                    if candidates(self._discovered)[k][1]["type"] == WEBHOOK
                ]
                self._auth_index = 0
                return await self.async_step_auth()
        return self.async_show_form(
            step_id="nodes",
            data_schema=vol.Schema(
                {
                    vol.Required(
                        "nodes",
                        default=[
                            v for v in self._settings.get("nodes", []) if v in choices
                        ],
                    ): selector.SelectSelector(
                        selector.SelectSelectorConfig(
                            options=[
                                selector.SelectOptionDict(value=k, label=v)
                                for k, v in choices.items()
                            ],
                            multiple=True,
                        )
                    )
                }
            ),
            errors=errors,
        )

    async def async_step_auth(self, user_input: dict[str, Any] | None = None) -> Any:
        """Masked JSON header map per selected action; blank preserves auth."""
        if self._auth_index >= len(self._auth_keys):
            return self._finish()
        key = self._auth_keys[self._auth_index]
        errors = {}
        if user_input is not None:
            try:
                if user_input.get("clear_auth", False):
                    self._settings.setdefault("webhook_headers", {}).pop(key, None)
                elif user_input.get("headers"):
                    headers = validate_headers(json.loads(user_input["headers"]))
                    if self._connection[CONF_API_TOKEN] in headers.values():
                        raise N8nIntegrationApiClientError(
                            "Discovery key cannot be webhook auth"
                        )
                    self._settings.setdefault("webhook_headers", {})[key] = headers
            except ValueError, N8nIntegrationApiClientError:
                errors["base"] = "invalid_headers"
            else:
                self._auth_index += 1
                return await self.async_step_auth()
        workflow, node = candidates(self._discovered)[key]
        return self.async_show_form(
            step_id="auth",
            description_placeholders={
                "node": f"{workflow['name']}: {node.get('name', node['id'])}"
            },
            data_schema=vol.Schema(
                {
                    vol.Optional("headers"): selector.TextSelector(
                        selector.TextSelectorConfig(
                            type=selector.TextSelectorType.PASSWORD
                        )
                    ),
                    vol.Required("clear_auth", default=False): bool,
                }
            ),
            errors=errors,
        )


class N8nFlowHandler(SelectionFlow, config_entries.ConfigFlow, domain=DOMAIN):
    """Initial connection and explicit selections."""

    VERSION = 1

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> Any:
        errors = {}
        if user_input is not None:
            self._settings = {}
            try:
                await self._connect(user_input, {})
            except N8nIntegrationApiClientAuthenticationError:
                errors["base"] = "auth"
            except N8nIntegrationApiClientCommunicationError:
                errors["base"] = "connection"
            except N8nIntegrationApiClientError:
                errors["base"] = "invalid_config"
            else:
                await self.async_set_unique_id(self._connection[CONF_URL])
                self._abort_if_unique_id_configured()
                return await self.async_step_workflows()
        return self.async_show_form(
            step_id="user",
            data_schema=connection_schema(user_input or {}),
            errors=errors,
        )

    def _finish(self) -> Any:
        return self.async_create_entry(
            title=self._connection[CONF_URL],
            data=self._connection,
            options=self._settings,
        )

    @staticmethod
    @callback
    def async_get_options_flow(
        config_entry: config_entries.ConfigEntry,
    ) -> N8nOptionsFlowHandler:
        return N8nOptionsFlowHandler()


class N8nOptionsFlowHandler(SelectionFlow, config_entries.OptionsFlowWithReload):
    """Options reload cleanly while entry/node identifiers stay stable."""

    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> Any:
        errors = {}
        if user_input is not None:
            self._settings = dict(self.config_entry.options)
            self._settings["webhook_headers"] = dict(
                self._settings.get("webhook_headers", {})
            )
            try:
                await self._connect(user_input, self.config_entry.data)
            except N8nIntegrationApiClientAuthenticationError:
                errors["base"] = "auth"
            except N8nIntegrationApiClientCommunicationError:
                errors["base"] = "connection"
            except N8nIntegrationApiClientError:
                errors["base"] = "invalid_config"
            else:
                return await self.async_step_workflows()
        return self.async_show_form(
            step_id="init",
            data_schema=connection_schema(
                {
                    **self.config_entry.data,
                    **self.config_entry.options,
                    **(user_input or {}),
                },
                options=True,
            ),
            errors=errors,
        )

    def _finish(self) -> Any:
        self.hass.config_entries.async_update_entry(
            self.config_entry, title=self._connection[CONF_URL], data=self._connection
        )
        return self.async_create_entry(title="", data=self._settings)
