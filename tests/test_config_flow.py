"""Exercise HA's actual multi-step flow and masked credentials."""

from unittest.mock import AsyncMock, patch

from homeassistant import data_entry_flow
from homeassistant.const import CONF_API_TOKEN, CONF_URL
from homeassistant.helpers.selector import TextSelectorType

from custom_components.n8n_integration.config_flow import connection_schema
from custom_components.n8n_integration.const import DOMAIN
from tests.test_lifecycle import entry, workflow

INPUT = {
    CONF_URL: "https://n8n.example",
    "webhook_url": "https://n8n.example",
    CONF_API_TOKEN: "dummy",
    "allow_http": False,
    "discovery_timeout": 10,
    "action_timeout": 60,
    "poll_interval": 300,
}


def test_initial_and_options_mask_secrets():
    for options in [False, True]:
        schema = connection_schema({CONF_API_TOKEN: "secret"}, options=options)
        fields = {key.schema: value for key, value in schema.schema.items()}
        assert fields[CONF_API_TOKEN].config["type"] == TextSelectorType.PASSWORD
        token_marker = next(k for k in schema.schema if k.schema == CONF_API_TOKEN)
        assert token_marker.default != "secret"


async def test_initial_select_and_auth(hass):
    with (
        patch(
            "custom_components.n8n_integration.api.N8nIntegrationApiClient.async_get_workflows",
            new_callable=AsyncMock,
            return_value={"data": [workflow()]},
        ),
        patch("custom_components.n8n_integration.async_setup_entry", return_value=True),
    ):
        result = await hass.config_entries.flow.async_init(
            DOMAIN, context={"source": "user"}, data=INPUT
        )
        assert result["step_id"] == "workflows"
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {"workflows": ["workflow"]}
        )
        assert result["step_id"] == "nodes"
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {"nodes": ["workflow:node"]}
        )
        assert result["step_id"] == "auth"
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            {"headers": '{"X-Halloween-Token":"dummy-webhook"}', "clear_auth": False},
        )
        assert result["type"] == data_entry_flow.FlowResultType.CREATE_ENTRY
        assert result["options"]["webhook_headers"] == {
            "workflow:node": {"X-Halloween-Token": "dummy-webhook"}
        }


async def test_default_empty_selection(hass):
    with (
        patch(
            "custom_components.n8n_integration.api.N8nIntegrationApiClient.async_get_workflows",
            new_callable=AsyncMock,
            return_value={"data": [workflow()]},
        ),
        patch("custom_components.n8n_integration.async_setup_entry", return_value=True),
    ):
        result = await hass.config_entries.flow.async_init(
            DOMAIN, context={"source": "user"}, data=INPUT
        )
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {"workflows": []}
        )
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {"nodes": []}
        )
        assert result["type"] == data_entry_flow.FlowResultType.CREATE_ENTRY
        assert result["options"]["nodes"] == []


async def test_options_preserve_credentials_and_reload(hass):
    item = entry()
    item.add_to_hass(hass)
    original_id = item.entry_id
    with patch(
        "custom_components.n8n_integration.api.N8nIntegrationApiClient.async_get_workflows",
        new_callable=AsyncMock,
        return_value={"data": [workflow()]},
    ):
        result = await hass.config_entries.options.async_init(item.entry_id)
        options_input = {
            key: value for key, value in INPUT.items() if key != CONF_API_TOKEN
        }
        result = await hass.config_entries.options.async_configure(
            result["flow_id"], options_input
        )
        result = await hass.config_entries.options.async_configure(
            result["flow_id"], {"workflows": ["workflow"]}
        )
        result = await hass.config_entries.options.async_configure(
            result["flow_id"], {"nodes": ["workflow:node"]}
        )
        result = await hass.config_entries.options.async_configure(
            result["flow_id"], {"clear_auth": False}
        )
        assert result["type"] == data_entry_flow.FlowResultType.CREATE_ENTRY
        assert item.data[CONF_API_TOKEN] == "secret-discovery"
        assert item.options["webhook_headers"] == {
            "workflow:node": {"X-Token": "secret-webhook"}
        }
        assert item.entry_id == original_id
