"""Workflow modified timestamps, form links and payload actions."""

from __future__ import annotations

from datetime import datetime
from typing import Any
from urllib.parse import quote

import probatio as vol
from homeassistant.components.sensor import SensorDeviceClass, SensorEntity
from homeassistant.core import SupportsResponse
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers import entity_platform
from homeassistant.util import dt as dt_util

from .api import HTTP_METHODS
from .entity import N8nIntegrationEntity, reconcile_entities
from .selection import FORM


async def async_setup_entry(hass: Any, entry: Any, async_add_entities: Any) -> None:
    """Set up sensors and the entity-targeted payload service."""
    reconcile_entities(entry, async_add_entities, N8nIntegrationTriggerSensor)
    platform = entity_platform.async_get_current_platform()
    platform.async_register_entity_service(
        "trigger_webhook",
        {
            vol.Optional("payload"): vol.Schema({cv.string: object}),
            vol.Optional("method"): vol.All(vol.Upper, vol.In(HTTP_METHODS)),
        },
        "async_handle_trigger_webhook",
        supports_response=SupportsResponse.OPTIONAL,
    )


class N8nIntegrationTriggerSensor(N8nIntegrationEntity, SensorEntity):
    """A modified-time sensor, not execution monitoring."""

    _attr_device_class = SensorDeviceClass.TIMESTAMP
    _attr_icon = "mdi:transit-connection-horizontal"
    name_suffix = " modified time"

    def __init__(self, coordinator: Any, workflow_id: str, node_id: str) -> None:
        super().__init__(coordinator, workflow_id, node_id, "sensor")

    @property
    def native_value(self) -> datetime | None:
        item = self.metadata
        value = item[0].get("updatedAt") if item else None
        return dt_util.parse_datetime(value) if value else None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        item = self.metadata
        if item is None:
            return {}
        workflow, node = item
        client = self.coordinator.config_entry.runtime_data.client
        result = {
            "workflow_id": self.workflow_id,
            "workflow_name": workflow["name"],
            "n8n_url": client.webhook_url,
            "type": node["type"],
        }
        if node["type"] == FORM:
            result["form_url"] = (
                f"{client.webhook_url}/form/{quote(node['webhookId'], safe='')}"
            )
        return result

    async def async_handle_trigger_webhook(
        self, payload: dict[str, Any] | None = None, method: str | None = None
    ) -> dict[str, Any]:
        """Return an ephemeral response without storing it in state."""
        return {
            "response": await self.coordinator.async_trigger(
                self.workflow_id, self.node_id, payload, method
            )
        }
