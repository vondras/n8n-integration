# n8n Integration for Home Assistant — hardened fork

Discover selected **published** n8n workflows, expose action buttons and form links,
and send payloads using `n8n_integration.trigger_webhook`.

Fork of [libstash/n8n-integration](https://github.com/libstash/n8n-integration), based
on `ce0a7d186a8a761e934bc02fbeafe76591ddf9c9`. Original MIT license and attribution
are preserved. This fork uses the same `n8n_integration` domain and replaces the
upstream component; install one copy. Minimum supported HA: **2026.10.1**.
Published metadata requires n8n's `activeVersion` and `activeVersionId`; missing or
mismatched published metadata fails closed. Tested n8n target: **2.41.7**.

## Install and update

Use `VonDras/n8n-integration` as the HACS custom Integration repository, or copy
`custom_components/n8n_integration` to `/config/custom_components/` and restart HA.
Keep the prior directory/settings for rollback. HACS tracks its configured repository,
not the manifest documentation link; remove the upstream HACS repository before
installing this fork. A manual install has no automatic update source. Pin upgrades
to a verified commit/package; the version number alone does not pin source contents.

## Configure

1. Use a discovery key with **only `workflow:list` and `workflow:read`**. Never use
   credential CRUD, workflow editing or execution administration for this integration.
2. Provide direct HTTPS discovery and webhook origins, which may differ. Redirects
   are rejected. Embedded credentials, paths, query strings and fragments are rejected.
   HTTP requires explicit opt-in for an internal endpoint. TLS verification stays enabled.
3. Choose workflows, then individual webhook actions/form links. **Nothing is selected
   by default.** Select only safe actions; selecting an action permits its execution.
4. For each webhook, enter a masked JSON header object, for example
   `{"X-Halloween-Token":"your-webhook-secret"}`. Blank keeps existing authentication;
   Clear authentication removes it. Discovery keys cannot be used as webhook auth.
   Header configuration supports explicit Basic/Authorization values if needed, but
   never retrieves encrypted n8n credentials. HA config-entry storage holds secrets.
5. Tune discovery timeout (1–60 seconds, default 10), action timeout (1–300 seconds,
   default 60), and metadata polling (30–86400 seconds, default 300). Options reload
   the entry without restarting HA. Blank discovery token in Options preserves it.

Machine routing must allow only GET `/api/v1/workflows` and GET
`/api/v1/workflows/<id>` from HA's actual source address, retaining native n8n API-key
checks. Preserve interactive authentication for other API/editor routes. HA cannot
use Kubernetes service DNS directly. See [deployment and rollback](docs/DEPLOYMENT.md).

## Actions and responses

Buttons execute the current selected published node once. Payload action example:

```yaml
action: n8n_integration.trigger_webhook
target:
  entity_id: sensor.my_workflow_action_modified_time
data:
  payload:
    message: hello
  method: POST
response_variable: result
```

Returned service data contains `response`. JSON (including `+json` MIME types), UTF-8
text and empty/204 responses are supported. Responses/payloads are **never stored
in entity attributes**. Automation traces can still retain service response/payload
variables; configure sensitive automations accordingly. Binary delivery is unsupported,
known binary webhooks and `halloween-audio` are omitted, and other binary responses
are rejected after a request. Inspect actions before selecting them: a delivery route
using a Respond to Webhook node may not advertise binary behavior in its trigger.
No optional persistent response mode is provided.

GET/HEAD payloads become scalar query parameters; other methods use a JSON object.
The requested method must be supported by the published node. No timestamp is injected.
Dynamic/expression webhook paths are not supported. Actions re-read metadata immediately
before sending, preventing cached draft/removed paths from being triggered. A workflow
can still change between that read and the request; this is not an atomic n8n operation.

**Timeout means completion is unknown.** The workflow may continue. There is no automatic
retry or cancellation. Workflow-side deduplication remains the application's responsibility.
Action bodies are bounded at 256 KiB, discovery pages at 8 MiB, lists at 100 pages/5000
workflows. Malformed/oversized responses fail without retaining their contents.

Sensors show **workflow modified time**, not last execution, success, spend or health.
Form links are read-only. Refresh adds newly selected nodes and uses current names/paths.
Removed, disabled, inactive or unselected entities become unavailable. Registry entries
retain user customizations and may be manually removed once no longer needed. IDs include
config-entry/workflow/node identities, isolating multiple connections. Discovery failures
preserve cached definitions but mark entities unavailable until successful recovery.

## Development

Use Python 3.14 in a separate environment, never install dev dependencies into HA Core:

```sh
python -m pip install -r requirements.txt
python -m pytest -q
python -m ruff check .
python -m ruff format . --check
python -m mypy custom_components/n8n_integration
```

Tests use HA 2026.10.1 and aiohttp 3.14.4, fake transports, and two loopback origins
with a dummy redirect key. CI also runs hassfest and HACS validation. The fork intentionally
contains no AI agent, speech provider, execution monitoring or binary-audio button support.
