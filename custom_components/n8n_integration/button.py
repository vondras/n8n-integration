"""Buttons for explicitly selected action webhooks."""

from __future__ import annotations

from typing import Any

from homeassistant.components.button import ButtonEntity

from .entity import N8nIntegrationEntity, reconcile_entities
from .selection import WEBHOOK


async def async_setup_entry(hass: Any, entry: Any, async_add_entities: Any) -> None:
    """Install dynamic discovery listener."""
    reconcile_entities(entry, async_add_entities, N8nWorkflowButton, node_type=WEBHOOK)


class N8nWorkflowButton(N8nIntegrationEntity, ButtonEntity):
    """No response or payload is retained in entity attributes."""

    _attr_icon = "mdi:gesture-tap"

    def __init__(self, coordinator: Any, workflow_id: str, node_id: str) -> None:
        super().__init__(coordinator, workflow_id, node_id, "button")

    async def async_press(self, **kwargs: Any) -> None:
        """Trigger the current published node once."""
        await self.coordinator.async_trigger(self.workflow_id, self.node_id)
