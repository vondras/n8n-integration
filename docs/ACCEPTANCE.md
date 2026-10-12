# Acceptance evidence — version 0.2.0

The initial action/lifecycle implementation was validated at
`05ce3f1a30bd13e4ac9e368cc18bc2d7e4a812cd`; the final form-path correction
adds a read-only form fixture and a runtime guard against discovery-key reuse
after credential rotation. The fork is based on upstream
`ce0a7d186a8a761e934bc02fbeafe76591ddf9c9`. Validation performed October 12, 2026.

- 44 isolated behavior tests passed on HA 2026.10.1 / Python 3.14 / aiohttp 3.14.4.
- Ruff lint/format and Mypy passed. Official HA 2026.10.1 hassfest: zero invalid integrations.
- Official HACS custom-repository checks: information, hacs.json and integration manifest passed.
  This is not a claim of inclusion in HACS's default catalog. The new fork's GitHub Actions
  had no runs at inspection; local validation supplied the evidence.
- Manual deployment: installed source files matched the tested commit exactly; HA config check passed.
- Live HA 2026.10.1 / n8n 2.41.7 pilot: button, JSON payload, correct per-node header, HTTP failure,
  no persistent response attributes, and a delayed response completed successfully in 14.42 seconds.
- A deliberate one-second action timeout left exactly one running pilot execution. Timeout text
  explains ambiguous completion; the default 60-second timeout was restored through Options.
- Live unpublish rejected actions; publish/rename/path change/add/remove preserved existing IDs,
  exposed newly selected nodes and made removed nodes unavailable without another HA restart.
- Published-versus-draft selection was verified against installed n8n source and isolated fixtures.
  A live draft edit was not performed through the editor; this remains a limitation of the report.
- The machine route allowed only exact workflow list/detail GETs from HA's single source IP.
  Missing keys received native 401; the editor and credential API still required interactive login.
- OpenAI, all three Wyoming config entries and InfluxDB remained loaded after restart; a recent
  v3 sensor timestamp was read back. Existing n8n household definitions/OIDC were preserved.
- Only the existing Halloween action was selected, using its existing HA secret. Binary audio
  was omitted. Outside-window requests returned skipped/outside_window; the estimated allowance
  and attempt/success counters were unchanged. No charged manual preview was performed.

The live relay cutover requires explicit production authorization. Its existing REST action
remains in place until that approval; the installed fork and selected action are ready.
Physical speaker audibility, costume samples and long observation remain separate household
acceptance items. No scheduled prompts or execution-monitoring subsystem were added.

Version 0.2.0 is available as a pinned manual package. No GitHub tag/release was created;
manual deployment has no automatic update source. See the deployment guide before upgrades.
