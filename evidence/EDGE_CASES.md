# Edge-case verification

This matrix covers the defined savings-balance workflow against the local synthetic bank.
The current automated run is recorded in [VERIFICATION.md](VERIFICATION.md). Tests use real
Chromium. Discovery tests inject a deterministic test decider; provider protocol tests
exercise the production Anthropic request builder/parser with a mocked transport. No
successful live model run or real-person handoff is claimed.

## Issues found and fixed

| Issue | Fix | Regression check |
| --- | --- | --- |
| Only `role="dialog"` was detected; native HTML dialogs, alert dialogs and modal attributes could be missed | Inspect visible `dialog[open]`, dialog/alertdialog roles and `aria-modal`; ignore hidden dialogs; check again before returning an output | `test_html_dialog_variants_and_hidden_dialog`, `test_native_prompt_and_confirm_stop` |
| Backend verification trusted loosely typed JSON; e.g. boolean member counts could compare equal to 1 | Strict session/account schema; reject malformed or unexpected fields before identity/account decisions | `test_backend_schema_rejects_ambiguous_types` |
| Verification HTTP 403/429/5xx had generic classification | Permission denial stops; transient read failures use the existing bounded observation retry path; redirects and malformed JSON are rejected | `test_verification_http_errors_and_recovery`, `test_read_retry_limit` |
| Invalid provider response shapes were sometimes reported as service outages | Separate transport errors from response validation; reject truncated, missing, multiple, unknown and unoffered actions | `test_provider_malformed_responses`, `test_provider_unavailable_and_deadline` |
| The outgoing model boundary assumed every caller supplied a safe observation; SDK debug logs could expose raw diagnostics | Independently validate the outgoing semantic payload; suppress SDK/HTTP diagnostic log propagation | `test_model_boundary_rejects_untrusted_metadata`, `test_provider_payload_and_valid_response`, `test_sdk_diagnostics_do_not_emit_private_values` |
| Artifacts could accept booleans/numeric lookalikes in some fields, invalid calendar dates, duplicate JSON keys, or waits after output extraction | Strict nested records, bounded file loading, normalized errors, calendar validation, and stricter step order | `test_artifact_nested_types_and_wait_order`, `test_artifact_file_errors_do_not_echo_contents` |
| A timed-out/cancelled handoff could leave a daemon thread waiting on terminal input; snapshot failure could leave ownership marked human | Nonblocking Unix terminal polling; no background reader; terminal ownership on any handoff failure | `test_console_reader_handles_partial_input_and_eof`, `test_operator_idle_and_wrong_member`, `test_handoff_snapshot_failure_never_leaves_human_ownership` |
| Direct browser startup failure could leave the Playwright driver active; cold startup used an overly short action timeout | Cleanup inside public `start()`; separate 30-second startup cap bounded by the run deadline | `test_failed_browser_start_cleans_up_driver` |
| Numeric runtime limits and money parsing accepted overly permissive forms | Reject boolean/fractional step limits, nonfinite deadlines, oversized amounts and non-ASCII money digits | `test_numeric_limits_are_strict`, `test_money` |

## Coverage of the requested cases

“Stop” means no balance is returned and no uncertain action is automatically repeated.
A recoverable outcome indicates that a corrected/new run may succeed; it does not imply
automatic recovery in the current session.

| Requested case | Implemented behavior | Automated verification |
| --- | --- | --- |
| Missing/invalid inputs | Reject before browser/model startup | `test_parameters_rejected_before_browser_start`, `test_numeric_limits_are_strict` |
| Nonexistent member / invalid credentials / login validation error | Generic `invalid_credentials` business outcome; no credential guessing or account enumeration | Both scenario matrices |
| Multiple matching members | Business outcome from the mock bank's member-match contract | Both scenario matrices; strict backend-schema tests |
| Missing/multiple savings accounts | Business outcome; never select the first match | Both scenario matrices |
| Zero/negative balances | Return success only when the fresh backend value agrees | Both-member replay/output tests and discovery matrix |
| Unexpected currency/number format | Reject unsupported currency, separators, exponents, special values and digit formats | `test_money`, `test_numeric_limits_are_strict`, both matrices |
| Missing output fields | Stop with no output | Both matrices |
| Wrong-member navigation / inconsistent output | Reject both backend identity and rendered identity mismatch; verify displayed amount independently | Both matrices, `test_output_requires_backend_agreement`, operator wrong-member test |
| Permission denials | Hard failure at browser and verification endpoint | Both matrices, verification HTTP tests |
| Session expiry / unexpected login | Stop; require a fresh authenticated run | Both matrices and verification HTTP 401 test |
| Known dialogs | Dismiss the exact known native alert; known operator notice supports exclusive handoff | Both matrices and handoff tests |
| Unknown native/HTML dialogs | Dismiss unknown native dialogs to unblock the browser, then stop; stop on visible HTML modals | Both matrices, native prompt/confirm and HTML variant tests |
| Disabled/hidden controls | Stop; never force-click | Both matrices |
| Duplicate labels / hidden duplicate elements | Require exactly one matching control | `test_locator_labels_and_hidden_duplicates`, existing ambiguity tests and both matrices |
| Stale elements / uncertain effects | Stop without repeating the action | Both matrices and `test_uncertain_action_not_repeated` |
| Iframes | Reject; v1 does not traverse frames | Both matrices |
| Changed routes/layouts | Block changed routes; stop on missing/ambiguous layout controls | Both matrices |
| Slow/partial loads | Normal slow loads wait within the operation budget; incomplete pages stop; artifacts can include a bounded explicit balance wait | Both matrices, `test_optional_wait_replay_and_repetition_bound` |
| Network failures / application errors | Stop; transport and action timeout may report `network_failure` or `uncertain_action`, respectively; neither retries the action | Both matrices, request-guard failure and uncertain-action tests |
| Safe retry limits | Only verification reads during observation retry, twice at most | `test_verification_http_errors_and_recovery`, `test_read_retry_limit` |
| Malformed model actions | Reject unexpected shapes, fields, tool names, truncated responses and unoffered actions | Production parser tests plus existing decider tests |
| Unavailable model service | Stop, no scripted production fallback and no transport retry | `test_provider_unavailable_and_deadline`, existing model-error tests |
| Repeated actions / step and time limits | Reject repeated actions; cap optional waits; refuse actions after deadline even if a model returns late | Existing model-limit tests, optional-wait test, `test_model_returning_after_deadline_cannot_act` |
| Unsupported/invalid artifact versions and parameters | Reject before replay can start; no model fallback | Artifact contract tests, `test_invalid_replay_never_loads_model` |
| Prohibited navigation, redirect, new tab and risky action | Block by origin/route/action policy; abort denied requests before transport; close new tabs; reject confirmation-required actions in this read-only workflow | Both matrices, `test_request_guard_never_sends_denied_requests`, `test_policy_applies_to_both_execution_modes`, `test_risky_label_and_tampered_login_form` |
| Sensitive-data exposure / page injection | Exclude arbitrary goals/text/URLs/metadata, validate outbound model requests, sanitize errors, block invalid evidence before writing | Existing privacy/injection tests, model-boundary/parser/log tests, artifact-file error test |
| Screenshots/traces | Raw screenshots, HTML/HAR dumps and traces are not captured; evidence uses semantic snapshots and a closed vocabulary | `test_evidence_audit_rejects_private_data`, `test_evidence_sink_blocks_before_writing`, saved-file audit |
| Human takeover / resumption | Same browser/context; automation tools reject actions while human-owned; resume revalidates route, member and absence of modal | `test_exclusive_handoff_resumption` |
| Operator inactivity / cancellation / closure / navigation / unresolved issue | Stop and close the run; no silent resumption or leftover reader | `test_handoff_stops`, `test_operator_idle_and_wrong_member`, console-reader and handoff-snapshot tests |
| Parameter reuse and fresh outputs | Same artifact works for both members; no model import/access during replay | `test_reuse_fresh_outputs_without_model_access` |

All 32 configured mock scenarios are explicitly enumerated by
`test_discovery_scenario_matrix`; the test fails if a new scenario is added without an
expectation. Replay exercises the same scenarios through its existing success/failure
and uncertain-action tests. Artifact, policy, provider and handoff edge cases are tested
separately in the same suite.

## Remaining live checks and limits

1. **Successful live LLM discovery and replay of that resulting artifact remain pending.**
   The execution environment has no configured Anthropic key/model. Mocked transport
   tests verify parsing and privacy boundaries, not provider availability or model quality.
2. **A real person completing headed handoff remains pending.** Automated tests exercise
   browser interaction, exclusive ownership, terminal command polling and resumption,
   but an injected operator is not a real-person acceptance test.
3. **The supported recovery contract is intentionally narrow.** Iframes, unknown layouts,
   unexpected dialogs and expired sessions stop. There is no automatic cross-bank
   adaptation, reauthentication, or rediscovery; the README documents those limits.
4. **Member ambiguity is synthetic and the demo server is serial.** There is no staff
   directory search, MFA/CAPTCHA flow, remote operator authentication, or concurrent
   production tenant isolation. Those would require additional scope and tests.

The user requested completion of automated verification with the two live checks
explicitly left pending. No external model call or real-person evidence is fabricated.
