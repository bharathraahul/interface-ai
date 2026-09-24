# Mock Bank: discovery and deterministic replay

This extends the existing FastAPI mock bank, Playwright browser tools, reference store,
policy engine and dataclass artifact. The supported workflow is **retrieve the signed-in
member’s savings balance**. There are two synthetic members. No financial writes occur.

Inputs are nonempty `username` and `password` strings; both remain in backend memory.
Success requires the expected route, the requested authenticated member, exactly one
savings account, one visible balance field, valid USD money, and agreement with the
bank’s authenticated verification endpoint. A successful Python call returns
`{"savings_balance": {"amount": "<decimal string>", "currency": "USD"}}` directly to its
caller. The CLI and evidence return only `out:savings_balance`, never the amount.

## Setup

Run commands from this repository root. Python 3.9 or later is required; the clean
verification uses Python 3.9.6 on macOS and a fresh virtual environment. The demo
starts its own loopback server on a free port and stops it afterwards.

```sh
python3 -m venv .venv
. .venv/bin/activate
python -m pip --require-virtualenv install -r requirements.txt
python -m playwright install chromium
python verify.py
python audit.py
```

`python verify.py` runs the browser tests and offline demos and writes sanitized
`evidence/VERIFICATION.md`. For individual tests, use
`python -m unittest discover -s tests -v`.

Linux hosts may need `python -m playwright install --with-deps chromium` and permission
to install system packages. No cloud service, database, or deployment is required.

## Exact offline demos

The fixture command creates a **manual test fixture**, clearly marked `test_fixture`.
It is not evidence of LLM discovery. Subsequent replay logs are actual browser runs.

```sh
python demo.py fixture --artifact evidence/example-artifact.json
python demo.py replay --member first --artifact evidence/example-artifact.json
python demo.py replay --member second --artifact evidence/example-artifact.json
python demo.py replay --member second --scenario zero
python demo.py replay --scenario no_savings --evidence evidence/exceptional-replay.json
python audit.py
```

`no_savings` deliberately exits 1 with a `business_outcome`. Failures never return
partial financial outputs. Each demo gets a fresh browser context, session and server.
Credentials are generated in memory when the app starts; they are not committed or printed.

## Real LLM discovery

Set `ANTHROPIC_API_KEY` and `ANTHROPIC_MODEL` in the process environment. Use a model
available to your account with Messages API tool-use support. Enter the key through
a hidden prompt, not a command containing the key and not a chat message:

```sh
read -r -s ANTHROPIC_API_KEY
export ANTHROPIC_API_KEY
read -r ANTHROPIC_MODEL
export ANTHROPIC_MODEL
python demo.py discover --artifact evidence/discovered-artifact.json --evidence evidence/discovery.json
python demo.py replay --member second --artifact evidence/discovered-artifact.json --evidence evidence/discovered-replay.json
python audit.py
```

Every decision calls the real Anthropic API with the current sanitized observation and
a structured tool schema. There is no production scripted fallback. Missing credentials,
an unavailable service, or an invalid action stop the run. Raw provider output and errors
are discarded. `ANTHROPIC_API_KEY` is unnecessary for replay; tests explicitly disable
model imports during replay. `.env` files are ignored by Git, but are **not auto-loaded**.

## Live human takeover

```sh
python demo.py handoff --artifact evidence/example-artifact.json --evidence evidence/handoff-human.json
```

A headed Chromium window pauses at an operator notice. In that **same window**, click
**Dismiss notice**, then enter `resume` in the originating terminal. Enter `cancel` to
stop. The automation tools reject actions while the operator owns the session. No
credentials or balances are requested in the terminal. The operator can see the bank
screen locally; the model and evidence only receive semantic summaries.

Inactivity after 60 seconds, closure, any manual navigation, a remaining dialog, or
wrong-member state stops the session. A resumed run must revalidate identity and route.
The tests inject an operator to exercise this mechanism; `handoff-simulated.json` is
explicitly simulated operator evidence, not a claim that a person performed the task.

## Configuration and reuse

- `Policy(...)`: exact allowed domains, route regular expressions, action allowlist,
  blocked routes, risky labels and confirmation routes. Empty allowlists deny access.
  The base URL defines one exact permitted origin; redirects must remain within it.
- `surface.py`: reviewed selectors, canonical control labels, action templates and
  surface version. Another tenant with the same contract can reuse an artifact with
  a new base URL, its own policy and its own input references. Different layouts need
  a reviewed adapter/version; the runtime never guesses replacement controls.
- `runner.discover(...)` and `runner.replay(...)`: `timeout` in milliseconds (default
  3000), `step_limit` (16), `deadline` in seconds (60), `headless`, `policy`, `handoff`.
  Only observation verification can retry, at most twice. Click/fill/navigation
  effects are never automatically repeated when uncertain.
- `BANK_SCENARIO` selects a standalone app scenario; `demo.py --scenario` selects it
  for one isolated demo. `python demo.py --help` lists all available scenarios.
- `DEMO_MEMBER_ONE_PASSWORD` / `DEMO_MEMBER_TWO_PASSWORD` optionally provide local
  mock credentials through the environment. Otherwise they are generated at startup.
  For the standalone UI, configure these before `python main.py`; fixture usernames
  are in `data.py`. Never use real member information with this synthetic app.

The trusted caller supplies parameters directly:

```python
from artifact import Artifact
from runner import replay

# credentials come from the authorized caller's backend secret store
result = replay(Artifact.load("evidence/example-artifact.json"), credentials,
                base_url="http://127.0.0.1:8000")
if result.ok:
    deliver_to_authorized_caller(result.outputs)  # do not log or send to an LLM
```

The caller is authorized through credentials verified against the live bank session;
this demo does not expose a public agent API or a separate operator authentication system.

## Edge-case behavior

| Condition / scenario | Behavior |
| --- | --- |
| Missing, empty, wrong-type or extra inputs | Hard failure before browser/model startup |
| Nonexistent member / invalid credentials / login validation error | Business outcome `invalid_credentials`; no credential guessing |
| Multiple members / no savings / multiple savings | Business outcome; never choose the first match |
| Zero / negative balance | Success if fresh backend verification agrees |
| Unexpected currency / malformed number | Hard failure; USD grammar only, no guessing locale |
| Missing output / partial load / changed layout | Recoverable stop, no output; requires a reviewed fix or new run |
| Wrong member / ambiguous or duplicate controls | Hard failure; never positional fallback |
| Hidden / disabled / missing control | Recoverable stop; no forced clicks |
| Stale element / uncertain click or navigation | Stop; never retry an action with uncertain effects |
| Slow load within timeout | Wait normally; deadline remains enforced |
| Network / application error | Recoverable stop; no automatic action replay |
| Verification endpoint temporarily unavailable during observation | At most two read-only retries, then recoverable stop |
| Permission denial | Hard failure; no bypass |
| Session expiry / unexpected login | Recoverable stop; fresh authenticated run required |
| Known native session alert | Dismiss automatically |
| Known operator notice | Pause and transfer control when a handoff handler is configured; otherwise recoverable stop |
| Unknown native or HTML dialog | Dismiss native dialog if needed to unblock browser; stop, never accept an unknown confirmation |
| Iframe | Hard failure; v1 intentionally does not traverse frames |
| Changed route / prohibited redirect / new tab | Block and stop; validate every network hop, close new tabs |
| Malformed model response / repeated action / step or time limit | Hard failure with a fixed code |
| Unavailable model | Recoverable stop; no fabricated discovery |
| Unsupported or modified artifact | Reject before browser startup |
| Page instruction / sensitive-data exposure attempt | Discard free text and unknown metadata; restrict action IDs and network access |
| Operator inactivity / cancellation / closure / navigation / unresolved issue | Stop and close the session; never resume silently |

## Evidence and privacy checks

`evidence/` contains the example fixture, genuine browser replay logs for both members,
an exceptional replay, scenario outcomes, sanitized failure snapshots, and simulated
handoff events. Live discovery and human evidence must be generated with the commands
above. Their provenance is explicit; unavailable discovery is not presented as success.

No raw screenshots, HTML dumps, HAR files, Playwright traces or model transcripts are
saved. Failure “snapshots” consist only of semantic route/control state. `audit.py` checks
saved text files for assigned secrets and provider tokens, validates artifacts, and
requires evidence to use a closed vocabulary. It does not print offending values.
Runtime secret files and ignored dependency/VCS directories are excluded intentionally;
synthetic account data in `data.py` is documented test data, not production member data.

The network guard uses context-level routing, disables service workers and blocks
WebSockets, following the [Playwright context routing API](https://playwright.dev/python/docs/api/class-browsercontext#browser-context-route).
The expanded edge-case coverage and remaining live checks are listed in
[evidence/EDGE_CASES.md](evidence/EDGE_CASES.md).
See [REPORT.md](REPORT.md) for architecture, scope and remaining limitations.
