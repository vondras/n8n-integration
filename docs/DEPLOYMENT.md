# Controlled deployment and rollback

Package the exact tested commit and record its SHA256. Install only after automated
behavior checks pass. Do not point two HACS repositories at the same integration domain.
If an upstream install exists, preserve its directory and config-entry settings first,
then switch HACS ownership to this fork. HACS update metadata is repository-specific;
changing documentation/codeowner fields does not transfer its update source.

Start with a dedicated harmless JSON webhook. Verify discovery, button and payload
response, per-node authentication, error handling, a response longer than 10 seconds,
and a timeout with exactly one request. Use this test workflow for publish, rename,
path change, deactivate and remove acceptance checks. Ensure newly saved draft paths
are not exposed. Validate options reload/unload and unrelated HA integrations afterward.

Create a dedicated machine route for exact workflow list/detail GET paths. Restrict
source addresses to HA, never trust arbitrary forwarded IP headers, retain native n8n
API-key authentication, and test missing-key and wrong-source rejection. Do not bypass
editor, credential, execution, history, or modifying workflow endpoints. Keep API discovery
credentials separate from webhook headers.

Keep the existing household relay during the pilot. Only after acceptance, replace
its action in the **single existing automation** with this integration's payload action.
Do not enable a second arrival/event trigger. Keep date window, cooldown and allowance
checks in n8n. Binary audio remains its separately authenticated delivery route.

## Rollback

Restore the existing relay action first; preserve the single trigger path. Unload/disable
the fork entry or reinstall the previous pinned component. Run HA's config check and
restart normally when required. Revoke only the dedicated discovery key and remove only
the new machine-read route/policy if retiring it. Keep existing webhook credentials,
editor/OIDC protections, other integrations and historical data untouched.

Remove a dedicated disposable test workflow and its exact test-only route when the pilot
is retired. Retain per-change rollback source files/settings. No scheduled observation
or migration automation is required.
