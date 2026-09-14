"""Shared, validated executor. Only backend references enter fill operations."""
from urllib.parse import urlsplit
from outcomes import HardFailure, RecoverableError, PolicyBlocked
from policy import ALLOW, CONFIRM
from surface import action_id


def execute(browser, action, secrets, policy, confirm_fn=None):
    key = action_id(action)  # reject arbitrary selectors, literals and tools
    browser.guard(acting=True)
    route = action.target if action.tool == "navigate" else browser._route()
    label = None
    if action.tool == "click":
        loc = browser.resolve(action.target, action.by)
        href = loc.get_attribute("href")
        if href is not None:
            if not href.startswith("/") or href.startswith("//"):
                raise PolicyBlocked("prohibited_navigation")
            route = href
        else:
            # Only the expected read-only login submit is permitted.
            if key != "sign_in" or loc.evaluate("e => e.form && e.form.getAttribute('action')") != "/login":
                raise PolicyBlocked("unsafe_submit")
        label = loc.inner_text()  # used locally for risk checks, never logged
    decision = policy.evaluate(action.tool, route, urlsplit(browser.base_url).netloc, label)
    if decision.verdict == CONFIRM:
        # This read-only workflow deliberately blocks risky writes, even if a
        # caller supplies an approval callback. Handoff is for resolving state.
        raise PolicyBlocked("approval_required")
    if decision.verdict != ALLOW:
        raise PolicyBlocked("policy_blocked")
    value = None
    if action.tool == "navigate":
        browser.goto(action.target)
    elif action.tool == "fill":
        browser.fill(action.target, secrets.resolve(action.value_ref), by=action.by)
    elif action.tool == "click":
        browser.click(action.target, by=action.by)
    elif action.tool == "wait":
        if not browser.wait_for(action.target, by=action.by):
            raise RecoverableError("wait_timeout")
    elif action.tool == "extract":
        value = browser.extract(action.target, by=action.by)
    browser.guard()
    return value, {"step": action.step, "action": key, "decision": "ALLOW"}
