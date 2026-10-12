"""Diagnostics expose counts and nonsecret tuning settings only."""

from __future__ import annotations

from typing import Any


async def async_get_config_entry_diagnostics(hass: Any, entry: Any) -> dict[str, Any]:
    """Never include tokens, headers, payloads or raw workflow definitions."""
    coordinator = entry.runtime_data.coordinator
    return {
        "entry_id": entry.entry_id,
        "last_update_success": coordinator.last_update_success,
        "workflow_count": len((coordinator.data or {}).get("data", [])),
        "selected_node_count": len(coordinator.selected_nodes()),
        "settings": {
            k: entry.options.get(k, v)
            for k, v in {
                "discovery_timeout": 10,
                "action_timeout": 60,
                "poll_interval": 300,
            }.items()
        },
    }
