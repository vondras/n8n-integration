"""
Custom integration to integrate n8n with Home Assistant.

For more details about this integration, please refer to
https://github.com/libstash/n8n-integration
"""

from __future__ import annotations

from datetime import timedelta
from typing import TYPE_CHECKING

from homeassistant.const import CONF_API_TOKEN, CONF_URL, Platform
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.loader import async_get_loaded_integration

from .api import N8nIntegrationApiClient
from .const import DOMAIN, LOGGER
from .coordinator import N8nDataUpdateCoordinator
from .data import N8nIntegrationData

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant

    from .data import N8nIntegrationConfigEntry

PLATFORMS: list[Platform] = [
    Platform.SENSOR,
    Platform.BUTTON,
]


# https://developers.home-assistant.io/docs/config_entries_index/#setting-up-an-entry
async def async_setup_entry(
    hass: HomeAssistant,
    entry: N8nIntegrationConfigEntry,
) -> bool:
    """Set up this integration using UI."""
    coordinator = N8nDataUpdateCoordinator(
        hass=hass,
        logger=LOGGER,
        name=DOMAIN,
        update_interval=timedelta(seconds=entry.options.get("poll_interval", 300)),
        config_entry=entry,
    )
    entry.runtime_data = N8nIntegrationData(
        client=N8nIntegrationApiClient(
            url=entry.data[CONF_URL],
            api_token=entry.data[CONF_API_TOKEN],
            session=async_get_clientsession(hass),
            allow_http=entry.data.get("allow_http", False),
            webhook_url=entry.data.get("webhook_url"),
            discovery_timeout=entry.options.get("discovery_timeout", 10),
            action_timeout=entry.options.get("action_timeout", 60),
        ),
        integration=async_get_loaded_integration(hass, entry.domain),
        coordinator=coordinator,
    )

    # https://developers.home-assistant.io/docs/integration_fetching_data#coordinated-single-api-poll-for-data-for-all-entities
    await coordinator.async_config_entry_first_refresh()

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    return True


async def async_unload_entry(
    hass: HomeAssistant,
    entry: N8nIntegrationConfigEntry,
) -> bool:
    """Handle removal of an entry."""
    unloaded = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unloaded and not any(
        other.entry_id != entry.entry_id
        for other in hass.config_entries.async_loaded_entries(DOMAIN)
    ):
        hass.services.async_remove(DOMAIN, "trigger_webhook")
    return unloaded


async def async_reload_entry(
    hass: HomeAssistant,
    entry: N8nIntegrationConfigEntry,
) -> None:
    """Reload config entry."""
    await hass.config_entries.async_reload(entry.entry_id)
