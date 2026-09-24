"""LLM discovery and model-free replay over the same tools and verification rules."""
import re
import copy
import time
from dataclasses import replace
from datetime import datetime, timezone
from decimal import Decimal
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field, ValidationError
from playwright.sync_api import Error as PlaywrightError, TimeoutError as PlaywrightTimeout

from artifact import Artifact, Checkpoint
from browser import Browser, ControlNotFound
from executor import execute
from outcomes import Result, BusinessOutcome, RecoverableError, HardFailure, safe_code
from secrets_store import SecretStore
from surface import ACTIONS, RECOVERY, OUTCOME_RULES, action_id
from workflow import SAVINGS_BALANCE


class Parameters(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    username: str = Field(min_length=1, max_length=128, repr=False)
    password: str = Field(min_length=1, max_length=256, repr=False)


class VerifiedAccount(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    id: str = Field(min_length=1, max_length=128, repr=False)
    type: Literal["checking", "savings", "credit"]
    balance: str = Field(pattern=r"^-?[0-9]+\.[0-9]{2}$", max_length=64, repr=False)
    currency: str = Field(min_length=3, max_length=3)


class VerifiedSession(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    username: str = Field(min_length=1, max_length=128, repr=False)
    member_matches: int = Field(ge=1)
    accounts: list[VerifiedAccount] = Field(max_length=64, repr=False)


class Money(BaseModel):
    amount: Decimal
    currency: Literal["USD"] = "USD"


def parameters(values):
    try:
        result = Parameters.model_validate(values)
        if result.username != result.username.strip() or any(ord(c) < 32 for c in result.username):
            raise ValueError()
        return result
    except (ValidationError, ValueError, TypeError):
        raise HardFailure("invalid_inputs") from None


def parse_money(value):
    if not isinstance(value, str):
        raise HardFailure("missing_output")
    if len(value) > 64:
        raise HardFailure("invalid_money")
    if not value.startswith("$"):
        raise HardFailure("unexpected_currency")
    # USD v1 grammar: optional sign after $, plain digits or US thousands groups.
    if not re.fullmatch(r"\$-?(?:[0-9]+|[1-9][0-9]{0,2}(?:,[0-9]{3})+)\.[0-9]{2}", value):
        raise HardFailure("invalid_money")
    return Money(amount=Decimal(value[1:].replace(",", "")))


def identity(browser, inputs):
    try:
        state = VerifiedSession.model_validate(browser.backend_state()).model_dump()
    except ValidationError:
        raise HardFailure("verification_failed") from None
    if state.get("username") != inputs.username:
        raise HardFailure("wrong_member")
    if state.get("member_matches") != 1:
        raise BusinessOutcome("multiple_members")
    if browser.page.locator("body").get_attribute("data-member") != inputs.username:
        raise HardFailure("wrong_member")
    savings = [a for a in state.get("accounts", []) if a.get("type") == "savings"]
    if not savings:
        raise BusinessOutcome("no_savings")
    if len(savings) != 1:
        raise BusinessOutcome("multiple_savings")
    return savings[0]


def verify_output(browser, inputs, raw):
    if browser._route() != "/account/savings":
        raise HardFailure("checkpoint_failed")
    if browser.visible_dialogs():
        raise RecoverableError("unknown_dialog")
    account = identity(browser, inputs)
    card = browser.resolve('[data-account-id="savings"]')
    if card.get_attribute("data-account-type") != "savings" or account.get("id") != "savings":
        raise HardFailure("verification_failed")
    money = parse_money(raw)
    if account.get("currency") != "USD":
        raise HardFailure("unexpected_currency")
    try:
        expected = Decimal(account["balance"])
    except Exception:
        raise HardFailure("verification_failed") from None
    if not expected.is_finite() or money.amount != expected:
        raise HardFailure("output_mismatch")
    return {"savings_balance": {"amount": format(money.amount, ".2f"), "currency": money.currency}}


def artifact_from(actions, source):
    spec = SAVINGS_BALANCE
    checkpoints = [Checkpoint(a.step, "route_equals", route) for a in actions
                   if (route := {"open_login": "/login", "sign_in": "/", "open_savings": "/account/savings"}.get(action_id(a)))]
    return Artifact(name=spec["name"], version=1, description=spec["description"],
                    success_condition=spec["success_condition"],
                    created_at=datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
                    inputs=copy.deepcopy(spec["inputs"]), outputs=copy.deepcopy(spec["outputs"]), actions=actions,
                    checkpoints=checkpoints,
                    metadata={"surface_version": 1, "source": source, "recovery": copy.deepcopy(RECOVERY),
                              "outcomes": copy.deepcopy(OUTCOME_RULES)}).validate()


class Run:
    def __init__(self, inputs, base_url, headless, timeout, step_limit, deadline, handoff, policy):
        self.inputs = parameters(inputs)
        if (type(timeout) is not int or type(step_limit) is not int
                or type(deadline) not in {int, float}
                or not (0 < timeout <= 30000 and 1 <= step_limit <= 64 and 0 < deadline <= 300)):
            raise HardFailure("invalid_inputs")
        self.browser = Browser(base_url, headless, timeout, policy)
        self.secrets = SecretStore({"secret:username": self.inputs.username, "secret:password": self.inputs.password})
        self.step_limit, self.deadline = step_limit, time.monotonic() + deadline
        self.browser.deadline = self.deadline
        self.handoff = handoff
        self.evidence, self.actions = [], []
        self.repeats = {}
        self.outputs = {}
        self.handoffs = 0

    def budget(self):
        if time.monotonic() >= self.deadline:
            raise HardFailure("deadline_exceeded")
        if len(self.actions) >= self.step_limit:
            raise HardFailure("step_limit")
        # Bound individual browser calls to remaining overall budget.
        self.browser.timeout = min(self.browser.timeout, max(1, int((self.deadline-time.monotonic()) * 1000)))
        if self.browser.context:
            self.browser.context.set_default_timeout(self.browser.timeout)
            self.browser.context.set_default_navigation_timeout(self.browser.timeout)

    def state(self):
        b = self.browser
        b.guard()
        route = b._route()
        logged_in = any(action_id(a) == "sign_in" for a in self.actions)
        if route == "/login" and logged_in:
            raise RecoverableError("unexpected_login")
        if route in {"/", "/account/savings"}:
            identity(b, self.inputs)
        dialogs = b.visible_dialogs()
        if dialogs:
            if len(dialogs) == 1 and dialogs[0].get_attribute("id") == "notice":
                raise RecoverableError("human_required")
            raise RecoverableError("unknown_dialog")
        return b.observe()

    def observed(self):
        # Only observation is retried automatically. No fills, clicks or navigations
        # are retried after they may have executed.
        for attempt in range(3):
            self.budget()
            try:
                snapshot = self.state()
                self.evidence.append({"event": "observe", "snapshot": snapshot})
                return snapshot
            except RecoverableError as exc:
                code = safe_code(exc)
                if code == "human_required" and self.handoff and self.handoffs == 0:
                    expected_route = self.browser._route()
                    def validate():
                        if self.browser._route() != expected_route:
                            raise HardFailure("manual_navigation")
                        if self.browser.visible_dialogs():
                            raise HardFailure("handoff_unresolved")
                        identity(self.browser, self.inputs)
                    self.handoffs += 1
                    self.handoff.timeout = min(self.handoff.timeout, self.deadline - time.monotonic())
                    self.handoff.resolve(self.browser, validate, self.evidence)
                    continue
                if code != "verification_unavailable" or attempt == 2:
                    raise
                self.evidence.append({"event": "retry", "operation": "observe", "attempt": attempt+1})
                self.browser.page.wait_for_timeout(100)
        raise HardFailure("handoff_unresolved")

    def step(self, action):
        self.budget()
        key = action_id(action)
        self.repeats[key] = self.repeats.get(key, 0) + 1
        if self.repeats[key] > (2 if key == "wait_balance" else 1):
            raise HardFailure("repeated_action")
        # The model cannot submit a form with only one reference filled, extract
        # from another account, or replay a fill in an unexpected state.
        if key != "open_login" and key not in self.offered():
            raise HardFailure("malformed_model_action")
        action = replace(action, step=len(self.actions)+1)
        try:
            raw, event = execute(self.browser, action, self.secrets, self.browser.policy)
        except (PlaywrightTimeout, PlaywrightError):
            self.browser.guard()  # translate known policy/network/session errors first
            raise HardFailure("uncertain_action") from None
        self.actions.append(action)
        self.evidence.append(event)
        expected = {"open_login": "/login", "sign_in": "/", "open_savings": "/account/savings"}.get(key)
        if expected and self.browser._route() != expected:
            if key == "sign_in" and self.browser._route() == "/login":
                raise BusinessOutcome("invalid_credentials")
            if self.browser._route() == "/login":
                raise RecoverableError("session_expired")
            raise HardFailure("checkpoint_failed")
        if expected:
            if expected != "/login":
                identity(self.browser, self.inputs)
            self.evidence.append({"event": "checkpoint", "step": action.step, "verified": True})
        if key == "read_balance":
            self.outputs = verify_output(self.browser, self.inputs, raw)
            self.evidence.append({"event": "outcome_verified", "output_ref": "out:savings_balance"})
        self.budget_after_action()

    def budget_after_action(self):
        if time.monotonic() > self.deadline:
            self.outputs = {}
            raise HardFailure("deadline_exceeded")

    def offered(self):
        route = self.browser._route()
        done = [action_id(a) for a in self.actions]
        if route == "/login":
            remaining = [k for k in ["fill_username", "fill_password"] if k not in done]
            return remaining or ["sign_in"]
        if route == "/":
            return ["open_savings"]
        if route == "/account/savings":
            return ["wait_balance", "read_balance"]
        raise HardFailure("checkpoint_failed")

    def result(self, exc=None):
        if exc is None:
            return Result("success", outputs=self.outputs, steps=len(self.actions), evidence=self.evidence)
        if isinstance(exc, BusinessOutcome):
            status = "business_outcome"
        elif isinstance(exc, RecoverableError):
            status = "recoverable_error"
        else:
            status = "hard_failure"
        code = safe_code(exc)
        # Failure snapshot is a semantic observation, never a raster screenshot,
        # DOM dump, HAR or Playwright trace with private data.
        try:
            self.evidence.append({"event": "failure_snapshot", "snapshot": self.browser.observe()})
        except Exception:
            self.evidence.append({"event": "failure_snapshot", "snapshot": {"available": False}})
        self.evidence.append({"event": "stopped", "status": status, "code": code})
        return Result(status, code, steps=len(self.actions), evidence=self.evidence)


def _run(inputs, artifact=None, decider=None, base_url="http://127.0.0.1:8000", headless=True,
         timeout=3000, step_limit=16, deadline=60, handoff=None, policy=None):
    run = None
    try:
        if artifact is not None:
            artifact.validate()
        run = Run(inputs, base_url, headless, timeout, step_limit, deadline, handoff, policy)
        with run.browser:
            try:
                if artifact is not None:
                    # This branch does not import, instantiate, or call any model.
                    for action in artifact.actions:
                        if action_id(action) != "open_login":
                            run.observed()
                        run.step(action)
                    if not run.outputs:
                        raise HardFailure("missing_output")
                    return run.result(), None
                if decider is None:
                    from llm import Decider
                    decider = Decider()
                run.step(ACTIONS["open_login"])
                while not run.outputs:
                    snapshot = run.observed()
                    offered = run.offered()
                    try:
                        key = decider.decide(snapshot, offered, [action_id(a) for a in run.actions],
                                             timeout=run.deadline-time.monotonic())
                    except (RecoverableError, HardFailure):
                        raise
                    except Exception:
                        raise RecoverableError("model_unavailable") from None
                    if not isinstance(key, str) or key not in ACTIONS:
                        raise HardFailure("malformed_model_action")
                    if key in run.repeats and key != "wait_balance":
                        raise HardFailure("repeated_action")
                    if key not in offered:
                        raise HardFailure("malformed_model_action")
                    run.evidence.append({"event": "model_decision", "action": key})
                    run.step(ACTIONS[key])
                saved = artifact_from(run.actions, decider.source)
                return run.result(), saved
            except Exception as exc:
                return run.result(exc), None
    except Exception as exc:
        if run:
            return run.result(exc), None
        return Result("hard_failure", safe_code(exc)), None


def discover(inputs, **kwargs):
    return _run(inputs, **kwargs)


def replay(artifact, inputs, **kwargs):
    if not isinstance(artifact, Artifact):
        return Result("hard_failure", "invalid_artifact")
    result, _ = _run(inputs, artifact=artifact, **kwargs)
    return result
