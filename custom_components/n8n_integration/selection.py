"""Published trigger selection shared by flows, entities and action checks."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from .api import N8nIntegrationApiClientError, supported_methods, webhook_path

WEBHOOK = "n8n-nodes-base.webhook"
FORM = "n8n-nodes-base.formTrigger"


def node_key(workflow_id: str, node_id: str) -> str:
    """Collision-free key for configuration mappings."""
    return f"{workflow_id}:{node_id}"


def published_workflow(workflow: dict[str, Any]) -> dict[str, Any] | None:
    """Fail closed when the published version cannot be identified."""
    version = workflow.get("activeVersion")
    if (
        not workflow.get("active")
        or workflow.get("isArchived")
        or not isinstance(version, dict)
        or not isinstance(version.get("nodes"), list)
        or not workflow.get("activeVersionId")
        or version.get("versionId") != workflow["activeVersionId"]
    ):
        return None
    return {
        "id": workflow["id"],
        "name": workflow.get("name", "n8n"),
        "updatedAt": workflow.get("updatedAt"),
        "nodes": version["nodes"],
        "activeVersionId": workflow["activeVersionId"],
    }


def form_path(node: dict[str, Any]) -> str:
    """Resolve v2 custom form paths before falling back to the webhook ID."""
    parameters = node.get("parameters", {})
    path = (
        parameters.get("path")
        or parameters.get("options", {}).get("path")
        or node.get("webhookId")
    )
    return webhook_path({"parameters": {"path": path}})


def eligible_node(node: dict[str, Any]) -> bool:
    """Exclude disabled, dynamic and known binary delivery nodes."""
    if node.get("disabled") or not isinstance(node.get("id"), str):
        return False
    if node.get("type") == FORM:
        try:
            form_path(node)
        except N8nIntegrationApiClientError:
            return False
        return True
    if node.get("type") != WEBHOOK:
        return False
    params = node.get("parameters", {})
    if params.get("responseData") == "firstEntryBinary" or params.get(
        "options", {}
    ).get("binaryData"):
        return False
    try:
        path = webhook_path(node)
        supported_methods(node)
    except N8nIntegrationApiClientError:
        return False
    return path != "halloween-audio"


def candidates(
    data: dict[str, Any],
) -> dict[str, tuple[dict[str, Any], dict[str, Any]]]:
    """Only published metadata can become an entity candidate."""
    result = {}
    for raw in data.get("data", []):
        workflow = published_workflow(raw)
        if workflow is not None:
            for node in workflow["nodes"]:
                if eligible_node(node):
                    result[node_key(workflow["id"], node["id"])] = (workflow, node)
    return result


def selected(
    data: dict[str, Any], options: Mapping[str, Any]
) -> dict[str, tuple[dict[str, Any], dict[str, Any]]]:
    """Both workflow and node require explicit consent."""
    workflows = set(options.get("workflows", []))
    nodes = set(options.get("nodes", []))
    return {
        key: item
        for key, item in candidates(data).items()
        if key in nodes and item[0]["id"] in workflows
    }
