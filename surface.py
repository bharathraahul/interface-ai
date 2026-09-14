"""Versioned, tenant-owned surface contract; page strings never become instructions."""
from artifact import ActionSpec

SURFACE_VERSION = 1
# These identifiers, labels and selectors are trusted application configuration.
CONTROLS = {
    "dismiss_notice": ('#dismiss_notice', 'Dismiss notice'),
    "username": ('#username', 'Username'),
    "password": ('#password', 'Password'),
    "sign_in": ('button[type="submit"]', 'Sign in'),
    "savings": ('a[href="/account/savings"]', 'Savings account'),
    "balance": ('[data-field="balance"]', 'Savings balance'),
}
ACTIONS = {
    "open_login": ActionSpec(0, "navigate", target="/login"),
    "fill_username": ActionSpec(0, "fill", target=CONTROLS["username"][0], value_ref="secret:username"),
    "fill_password": ActionSpec(0, "fill", target=CONTROLS["password"][0], value_ref="secret:password"),
    "sign_in": ActionSpec(0, "click", target=CONTROLS["sign_in"][0]),
    "open_savings": ActionSpec(0, "click", target=CONTROLS["savings"][0]),
    "wait_balance": ActionSpec(0, "wait", target=CONTROLS["balance"][0]),
    "read_balance": ActionSpec(0, "extract", target=CONTROLS["balance"][0]),
}
ROUTES = {"/login": "login", "/": "dashboard", "/account/savings": "savings"}
SUCCESS = "Authenticated member matches input; exactly one savings account; USD balance matches backend."
RECOVERY = {"observation_retries": 2, "uncertain_action": "stop", "known_notice": "handoff", "unknown_state": "stop"}
OUTCOME_RULES = {
    "success": "backend_verified",
    "business_outcome": ["invalid_credentials", "multiple_members", "no_savings", "multiple_savings"],
    "recoverable_error": ["session_expired", "unexpected_login", "verification_unavailable",
                          "network_failure", "model_unavailable", "human_required", "unknown_dialog",
                          "missing_control", "hidden_control", "disabled_control", "wait_timeout",
                          "application_error"],
    "hard_failure": "all_other_conditions",
}


def action_id(action):
    for key, template in ACTIONS.items():
        if (action.tool, action.by, action.target, action.value_ref, action.risky, action.description) == (
                template.tool, template.by, template.target, template.value_ref, False, ""):
            return key
    from outcomes import HardFailure
    raise HardFailure("invalid_action")
