"""Actual HA setup, reconciliation, selection, service and unload tests."""

import json
from unittest.mock import AsyncMock, patch

import pytest
from homeassistant.const import CONF_API_TOKEN, CONF_URL
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.n8n_integration.api import N8nIntegrationApiClientError
from custom_components.n8n_integration.const import DOMAIN
from custom_components.n8n_integration.diagnostics import (
    async_get_config_entry_diagnostics,
)
from custom_components.n8n_integration.selection import candidates


def workflow(path="pilot", name="Pilot", active=True, nodes=None):
    nodes = (
        nodes
        if nodes is not None
        else [
            {
                "id": "node",
                "name": "Action",
                "type": "n8n-nodes-base.webhook",
                "parameters": {"httpMethod": "POST", "path": path},
            }
        ]
    )
    return {
        "id": "workflow",
        "name": name,
        "active": active,
        "activeVersionId": "published",
        "versionId": "draft",
        "updatedAt": "2026-10-12T12:00:00Z",
        "nodes": [{"id": "node", "parameters": {"path": "unpublished-draft"}}],
        "activeVersion": {"versionId": "published", "nodes": nodes},
    }


def entry(entry_id=None):
    kwargs = {"entry_id": entry_id} if entry_id else {}
    return MockConfigEntry(
        domain=DOMAIN,
        data={CONF_URL: "https://n8n.example", CONF_API_TOKEN: "secret-discovery"},
        options={
            "workflows": ["workflow"],
            "nodes": ["workflow:node", "workflow:second"],
            "webhook_headers": {"workflow:node": {"X-Token": "secret-webhook"}},
        },
        **kwargs,
    )


@pytest.fixture
def transport():
    with (
        patch(
            "custom_components.n8n_integration.api.N8nIntegrationApiClient.async_get_workflows",
            new_callable=AsyncMock,
            return_value={"data": [workflow()]},
        ) as listing,
        patch(
            "custom_components.n8n_integration.api.N8nIntegrationApiClient.async_get_workflow",
            new_callable=AsyncMock,
            side_effect=lambda wid: workflow(),
        ) as detail,
        patch(
            "custom_components.n8n_integration.api.N8nIntegrationApiClient.async_trigger_webhook",
            new_callable=AsyncMock,
            return_value={"secret": "ephemeral"},
        ) as action,
    ):
        yield listing, detail, action


async def setup(hass, item):
    item.add_to_hass(hass)
    assert await hass.config_entries.async_setup(item.entry_id)
    await hass.async_block_till_done()
    return item.runtime_data.coordinator


def test_binary_disabled_and_default_empty():
    raw = workflow(
        nodes=[
            {
                "id": "binary",
                "type": "n8n-nodes-base.webhook",
                "parameters": {"path": "halloween-audio"},
            },
            {
                "id": "disabled",
                "disabled": True,
                "type": "n8n-nodes-base.webhook",
                "parameters": {"path": "disabled"},
            },
            {
                "id": "ok",
                "type": "n8n-nodes-base.webhook",
                "parameters": {"path": "ok"},
            },
        ]
    )
    assert set(candidates({"data": [raw]})) == {"workflow:ok"}
    raw["activeVersion"] = None
    assert candidates({"data": [raw]}) == {}


async def test_live_metadata_add_rename_remove_and_failure(
    hass: HomeAssistant, transport
):
    listing, detail, action = transport
    item = entry()
    coordinator = await setup(hass, item)
    sensors = hass.states.async_all("sensor")
    buttons = hass.states.async_all("button")
    assert len(sensors) == len(buttons) == 1
    assert "modified time" in sensors[0].name
    sensor_id = sensors[0].entity_id
    button_id = buttons[0].entity_id
    latest = workflow(path="published-new", name="Renamed")
    detail.side_effect = None
    detail.return_value = latest
    response = await hass.services.async_call(
        DOMAIN,
        "trigger_webhook",
        {"entity_id": sensor_id, "payload": {"hello": "world"}},
        blocking=True,
        return_response=True,
    )
    assert "ephemeral" in json.dumps(response)
    assert action.call_args.args[0]["parameters"]["path"] == "published-new"
    assert action.call_args.args[1] == {"headers": {"X-Token": "secret-webhook"}}
    assert action.call_args.args[2] == {"hello": "world"}
    await hass.async_block_till_done()
    assert "ephemeral" not in json.dumps(dict(hass.states.get(sensor_id).attributes))
    assert "ephemeral" not in json.dumps(dict(hass.states.get(button_id).attributes))
    latest["activeVersion"]["nodes"].append(
        {
            "id": "second",
            "name": "Second",
            "type": "n8n-nodes-base.webhook",
            "parameters": {"path": "second", "httpMethod": "POST"},
        }
    )
    coordinator.async_set_updated_data({"data": [latest]})
    await hass.async_block_till_done()
    assert len(hass.states.async_all("button")) == 2
    listing.side_effect = N8nIntegrationApiClientError("Transient failure")
    await coordinator.async_refresh()
    await hass.async_block_till_done()
    assert len(coordinator.data["data"][0]["activeVersion"]["nodes"]) == 2
    with pytest.raises(HomeAssistantError):
        await coordinator.async_trigger("workflow", "node")
    listing.side_effect = None
    listing.return_value = {"data": [latest]}
    await coordinator.async_refresh()
    await hass.async_block_till_done()
    assert hass.states.get(button_id).state != "unavailable"
    detail.return_value = workflow(active=False)
    with pytest.raises(HomeAssistantError, match="published"):
        await hass.services.async_call(
            "button", "press", {"entity_id": button_id}, blocking=True
        )
    assert action.call_count == 1
    coordinator.async_set_updated_data({"data": []})
    await hass.async_block_till_done()
    assert hass.states.get(button_id).state == "unavailable"
    assert await hass.config_entries.async_unload(item.entry_id)
    await hass.async_block_till_done()
    assert all(s.state == "unavailable" for s in hass.states.async_all("button"))
    assert not coordinator._listeners


async def test_multiple_entries_reload_and_auth_isolation(hass, transport):
    _listing, _detail, action = transport
    first, second = entry("first"), entry("second")
    await setup(hass, first)
    await setup(hass, second)
    assert len(hass.states.async_all("button")) == 2
    assert len(hass.states.async_all("sensor")) == 2
    diagnostics = await async_get_config_entry_diagnostics(hass, first)
    assert "secret" not in json.dumps(diagnostics)
    await hass.config_entries.async_unload(first.entry_id)
    await hass.async_block_till_done()
    sensor_id = next(
        s.entity_id for s in hass.states.async_all("sensor") if s.state != "unavailable"
    )
    await hass.services.async_call(
        DOMAIN,
        "trigger_webhook",
        {"entity_id": sensor_id},
        blocking=True,
        return_response=True,
    )
    assert action.call_count == 1
    old_ids = {s.entity_id for s in hass.states.async_all("button")}
    assert await hass.config_entries.async_reload(second.entry_id)
    await hass.async_block_till_done()
    assert {s.entity_id for s in hass.states.async_all("button")} == old_ids
    hass.config_entries.async_update_entry(
        second, options={**second.options, "nodes": []}
    )
    await hass.config_entries.async_reload(second.entry_id)
    await hass.async_block_till_done()
    assert all(s.state == "unavailable" for s in hass.states.async_all("button"))
    assert action.call_count == 1


async def test_no_selection_creates_no_entities(hass, transport):
    item = MockConfigEntry(
        domain=DOMAIN,
        data={CONF_URL: "https://n8n.example", CONF_API_TOKEN: "dummy"},
        options={},
    )
    await setup(hass, item)
    assert all(s.state == "unavailable" for s in hass.states.async_all("button"))
    assert not hass.states.async_all("sensor")


async def test_published_form_custom_path_is_read_only(hass, transport):
    listing, detail, action = transport
    raw = workflow(
        nodes=[
            {
                "id": "node",
                "name": "Form",
                "type": "n8n-nodes-base.formTrigger",
                "webhookId": "fallback-id",
                "parameters": {"options": {"path": "custom-form"}},
            }
        ]
    )
    listing.return_value = {"data": [raw]}
    detail.side_effect = None
    detail.return_value = raw
    item = entry()
    await setup(hass, item)
    sensor = hass.states.async_all("sensor")[0]
    assert sensor.attributes["form_url"] == "https://n8n.example/form/custom-form"
    assert not hass.states.async_all("button")
    with pytest.raises(HomeAssistantError, match="webhook"):
        await hass.services.async_call(
            DOMAIN,
            "trigger_webhook",
            {"entity_id": sensor.entity_id},
            blocking=True,
            return_response=True,
        )
    action.assert_not_called()
