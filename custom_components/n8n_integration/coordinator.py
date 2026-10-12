"""Metadata refresh and authorization of current published actions."""

from __future__ import annotations

from typing import Any

from homeassistant.exceptions import ConfigEntryAuthFailed, HomeAssistantError
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import (
    N8nIntegrationApiClientAuthenticationError,
    N8nIntegrationApiClientError,
)
from .data import N8nIntegrationConfigEntry
from .selection import WEBHOOK, node_key, selected


class N8nDataUpdateCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    """Retain cached entities when a metadata refresh fails."""

    config_entry: N8nIntegrationConfigEntry

    async def _async_update_data(self) -> dict[str, Any]:
        try:
            return await self.config_entry.runtime_data.client.async_get_workflows()
        except N8nIntegrationApiClientAuthenticationError as err:
            raise ConfigEntryAuthFailed(str(err)) from None
        except N8nIntegrationApiClientError as err:
            raise UpdateFailed(str(err)) from None

    def selected_nodes(self) -> dict[str, tuple[dict[str, Any], dict[str, Any]]]:
        """Resolve entity metadata by stable identities."""
        return selected(self.data or {"data": []}, self.config_entry.options)

    async def async_trigger(
        self,
        workflow_id: str,
        node_id: str,
        payload: dict[str, Any] | None = None,
        method: str | None = None,
    ) -> Any:
        """Re-read before each action; never execute an old cached path."""
        key = node_key(workflow_id, node_id)
        if key not in self.selected_nodes() or not self.last_update_success:
            raise HomeAssistantError("Node is unavailable or no longer selected")
        client = self.config_entry.runtime_data.client
        try:
            raw = await client.async_get_workflow(workflow_id)
            item = selected({"data": [raw]}, self.config_entry.options).get(key)
            if item is None or item[1].get("type") != WEBHOOK:
                raise HomeAssistantError(
                    "Selected webhook is no longer published or enabled"
                )
            # Update just this workflow atomically without deleting unrelated entities.
            self.async_set_updated_data(
                {
                    "data": [w for w in self.data["data"] if w["id"] != workflow_id]
                    + [raw]
                }
            )
            headers = self.config_entry.options.get("webhook_headers", {}).get(key, {})
            return await client.async_trigger_webhook(
                item[1], {"headers": headers}, payload, method
            )
        except N8nIntegrationApiClientError as err:
            raise HomeAssistantError(str(err)) from None
