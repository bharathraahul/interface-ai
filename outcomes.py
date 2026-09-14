"""Explicit result taxonomy.

Every run ends in exactly one of these categories:

  success           — the workflow reached its goal and produced outputs.
  business_outcome  — a legitimate non-happy-path end state (e.g. the member has
                      no savings account). Not an error; the caller must handle it.
  recoverable_error — a transient failure we retried (e.g. a slow page). Surfaced
                      only if retries are exhausted.
  hard_failure      — a structural failure: missing locator, policy block, timeout,
                      step-limit. No automatic recovery.
"""

from dataclasses import dataclass, field


@dataclass
class Result:
    status: str                       # success | business_outcome | recoverable_error | hard_failure
    message: str = ""
    outputs: dict = field(default_factory=dict, repr=False)   # authorized caller's real values
    steps: int = 0
    evidence: list = field(default_factory=list)  # sanitized step log

    @property
    def ok(self):
        return self.status == "success"


class RecoverableError(Exception):
    """Transient — the executor may retry before giving up."""


class HardFailure(Exception):
    """Structural — stop and report."""


class PolicyBlocked(HardFailure):
    """A proposed action was denied by the allowlist / risk rules."""


class BusinessOutcome(Exception):
    """A legitimate non-happy-path end state, carried as control flow."""

    def __init__(self, message, outputs=None):
        super().__init__(message)
        self.outputs = outputs or {}

# Exceptions from libraries or pages are never serialized. Unknown messages become
# a fixed code; even a malicious exception containing credentials is discarded.
CODES = set("""invalid_goal unsupported_goal invalid_action invalid_locator
invalid_inputs invalid_artifact invalid_artifact_contract unsupported_artifact_version
invalid_artifact_timestamp invalid_artifact_metadata invalid_artifact_steps
invalid_step_number invalid_artifact_sequence invalid_wait_sequence invalid_checkpoints
action_or_domain_denied route_denied policy_blocked approval_required unsafe_submit
prohibited_navigation new_tab_blocked iframe_unsupported application_error
permission_denied network_failure verification_failed verification_unavailable
session_expired unexpected_login browser_closed automation_paused ambiguous_control
missing_control hidden_control disabled_control raw_observation_disabled
positional_locator_denied wait_timeout model_unavailable malformed_model_action
step_limit deadline_exceeded repeated_action invalid_credentials member_not_found
multiple_members no_savings multiple_savings wrong_member missing_output invalid_money
unexpected_currency output_mismatch checkpoint_failed human_required unknown_dialog
sensitive_data_blocked browser_unavailable operator_inactive handoff_cancelled handoff_unresolved manual_navigation
uncertain_action invalid_scenario internal_error artifact_too_large""".split())


def safe_code(exc):
    message = str(exc)
    return message if message in CODES else "internal_error"
