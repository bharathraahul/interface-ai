# Architecture

The existing FastAPI bank, templates, reference store, policy layer, browser wrapper
and dataclass artifact remain the foundation. The banking flow is unchanged: sign in,
open savings, read balance. A shared runner now connects those parts to real iterative
LLM discovery and deterministic replay. Both paths use `executor.execute`; neither has
a separate path that bypasses policy or verification. Two synthetic members demonstrate
parameter reuse without a database or additional backend service.

The surface abstraction is a reviewed mapping of semantic control IDs to stable CSS
selectors, canonical labels, and parameterized actions. Observations contain only these
IDs, their visibility/enabled state, and a canonical route name. Arbitrary body text,
titles, hrefs, input values and accessibility labels are excluded. A model selects one
structured action ID from currently offered actions on each observe–decide–act cycle.
The backend validates that ID, resolves its trusted template and fills secret references
locally. The model never supplies a literal credential, selector, URL or output value.

Success means more than seeing a number. The live authenticated backend must identify
the input member and exactly one savings account. The rendered member and account
markers must agree, the route must match, and one visible balance must parse as USD
money and equal the backend’s freshly read balance. Decimal arithmetic accepts zero and
negative values. Outputs return directly to the authorized Python caller; telemetry
contains only an output reference.

# Artifact schema

Schema version 1 records workflow name/version, UTC creation time, sensitive typed
input definitions, money output definition, ordered parameterized actions, stable
selectors, exact route checkpoints, explicit success conditions, surface version,
provenance, outcome classification rules and recovery rules. Password and username
steps reference `secret:password` and `secret:username`. Artifacts contain no input
values, member identities, account numbers, balances or tenant origin.

Validation rejects unknown versions, fields, contracts, arbitrary selectors, literal
values, unsupported sequences and missing checkpoints before replay starts. Version 1
supports either credential-fill order and at most two optional balance waits; navigation,
submission, savings selection and extraction retain their required order. This narrow
grammar makes artifacts reviewable and prevents an edited artifact from expanding the
read-only workflow. The example’s `test_fixture` provenance distinguishes it from an
artifact produced by successful `llm_discovery`. No automatic schema migration is
performed: incompatible artifacts require review and rediscovery against a new version.

# Determinism & error handling

Replay does not import or call the model. It resolves the same parameters into a fresh
browser context and executes validated steps with backend state checks. Locators must
match exactly one visible, enabled element; there is no first-match, index or approximate
fallback. Important navigation steps verify route and identity before continuing.
Business outcomes cover unsuccessful sign-in, multiple matching members, no savings
account and multiple savings accounts. Permission/policy violations, wrong-member
navigation, ambiguous locators, invalid money and incompatible artifacts are hard
failures. Session, load and service problems produce recoverable stops with fixed codes.

The runtime enforces step, wall-clock and browser-operation limits plus repeated-action
detection. Only read-only observation verification retries, twice at most. Uncertain
clicks, submissions, fills and navigations never repeat automatically. Missing output,
changed layout and expired sessions stop instead of guessing or returning stale data.
Known alerts are dismissed; unknown dialogs stop. Frames and new tabs are unsupported
and stop safely. The README maps every requested edge case to automatic handling,
a business outcome, a recoverable stop or a hard failure.

Tests use actual Chromium against the mock app, including both users, zero/negative
outputs, privacy canaries, injection text, redirects, ambiguity, failure scenarios,
retry bounds and exclusive handoff. Model and operator doubles are labelled explicitly.
Replay tests disable model imports. A clean virtual environment verifies dependencies,
and saved evidence is scanned using a closed vocabulary and secret-pattern checks.
Live LLM discovery requires configured model credentials; its evidence must come from
an actual successful call sequence, never from the test decider.

# Heterogeneity & multi-tenant

Artifacts parameterize credentials and omit the origin, so both mock members and tenants
sharing the same surface contract can reuse one artifact. Each run has a separate browser
context, cookie jar, reference store and policy. The configured base URL and exact domain,
route and action allowlists bind execution to one tenant origin. Cross-origin redirects,
query payloads, unexpected methods and unapproved routes are denied before requests run.

Different bank layouts need a reviewed surface mapping and compatible artifact version;
this demo deliberately avoids self-healing selectors. Authentication and independent
verification endpoints are bank-specific contracts. There is no claim of universal bank
support or hosted multi-tenant isolation: the local demo server uses global in-memory
scenario/session state and is intended for serial demos. Production tenancy would need
per-tenant app state, caller authorization, secrets management and deployment isolation.

# Escalation & handoff

The supported resumable escalation is a known operator notice. Automation pauses and
transfers exclusive tool ownership to the local operator in the same live Chromium
page and context. The operator dismisses the notice and requests resume through the
terminal. Browser event capture records only trusted semantic control IDs and event
kinds, never field contents. Resume verifies the original route, authenticated member,
account cardinality and absence of unresolved dialogs. Automation calls fail while
human ownership is active.

Cancellation, inactivity, closure, any manual navigation or unresolved state terminates
the run; no silent resume occurs. Unknown dialogs, expired sessions and uncertain action
effects stop for review and a new run rather than attempting generic recovery. Simulated
operator evidence proves the mechanism under test; the separate headed demo produces
actual operator evidence when a person performs the interaction. Remote operator login,
a shared control service and arbitrary authentication recovery are outside this scope.

# Safety

Privacy uses exclusion rather than regex redaction as the principal boundary. Raw goals
are mapped locally to the single supported intent. Page content is untrusted and cannot
extend the action vocabulary or override policy. The model receives no member values,
balances, raw URLs, screenshot pixels, HTML, transcripts or raw errors. Library errors
map to an allowlisted code; output values remain in backend memory. Risky operations
are blocked in this read-only workflow, including policy decisions requiring approval.

Context-wide interception validates requests and redirects, service workers are disabled,
WebSockets are blocked, and new pages are closed. The verification request uses a fixed
same-origin endpoint without redirects. Evidence consists of semantic snapshots and
constructed events. Raw screenshots, HARs and browser traces are deliberately disabled.
The file audit validates artifact structure and evidence vocabulary in addition to
checking token patterns. It is not a proof against arbitrary future logging changes;
new sinks and adapters must preserve these boundaries and add privacy tests.

# Cuts

The implementation keeps one workflow and the original local bank architecture. There
are no transfers, payments, persistent vault, generalized browser agent, automatic
artifact migration, fuzzy locator repair, multi-currency inference, iframe traversal,
remote operator portal or production authentication system. Member search ambiguity is
represented by a synthetic backend scenario; this is a member sign-in workflow, not a
staff directory search. Sensitive reference values last only for the run; Python memory
is not explicitly zeroized. The caller must protect returned outputs and process memory.

These cuts keep the additions focused on the missing execution, verification, privacy,
policy, replay, evidence and handoff requirements. Missing live model or human evidence
is disclosed rather than synthesized. Real-bank deployment would require tenant-owned
adapters, independent authorization and verification contracts, and further operational
hardening beyond this demonstrator.
