"""Entities resolve live metadata by stable workflow/node identity."""

from __future__ import annotations

from typing import Any

from homeassistant.core import callback
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import ATTRIBUTION, DOMAIN
from .coordinator import N8nDataUpdateCoordinator
from .selection import node_key


class N8nIntegrationEntity(CoordinatorEntity[N8nDataUpdateCoordinator]):
    """Unavailable tombstones retain registry customizations after removal."""

    _attr_attribution = ATTRIBUTION

    def __init__(
        self,
        coordinator: N8nDataUpdateCoordinator,
        workflow_id: str,
        node_id: str,
        kind: str,
    ) -> None:
        super().__init__(coordinator)
        self.workflow_id = workflow_id
        self.node_id = node_id
        self.key = node_key(workflow_id, node_id)
        self._attr_unique_id = (
            f"{coordinator.config_entry.entry_id}-{workflow_id}-{node_id}-{kind}"
        )

    @property
    def metadata(self) -> tuple[dict[str, Any], dict[str, Any]] | None:
        """Current selected published definition, never an initialization snapshot."""
        return self.coordinator.selected_nodes().get(self.key)

    @property
    def available(self) -> bool:
        return super().available and self.metadata is not None

    @property
    def name(self) -> str:
        item = self.metadata
        if item:
            return f"{item[0]['name']}: {item[1].get('name', self.node_id)}{self.name_suffix}"
        return f"n8n {self.workflow_id}: {self.node_id}{self.name_suffix}"

    name_suffix = ""

    @property
    def device_info(self) -> DeviceInfo:
        item = self.metadata
        return DeviceInfo(
            identifiers={
                (DOMAIN, f"{self.coordinator.config_entry.entry_id}:{self.workflow_id}")
            },
            name=item[0]["name"] if item else self.workflow_id,
            manufacturer="n8n",
        )


def reconcile_entities(
    entry: Any,
    async_add_entities: Any,
    entity_class: Any,
    *,
    node_type: str | None = None,
) -> None:
    """Add selected entities on refresh; missing entities become unavailable."""
    coordinator = entry.runtime_data.coordinator
    known: set[str] = set()

    @callback
    def reconcile() -> None:
        additions = []
        for key, (workflow, node) in coordinator.selected_nodes().items():
            if key not in known and (node_type is None or node["type"] == node_type):
                known.add(key)
                additions.append(entity_class(coordinator, workflow["id"], node["id"]))
        if additions:
            async_add_entities(additions)

    reconcile()
    entry.async_on_unload(coordinator.async_add_listener(reconcile))
