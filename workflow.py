"""Typed savings balance contract. Username is sensitive too."""
from artifact import InputSpec, OutputSpec
from surface import SUCCESS

SAVINGS_BALANCE = {
    "name": "savings_balance", "version": 1,
    "description": "Sign in as a member and read their savings account balance.",
    "goal": "Retrieve the authenticated member's savings balance using input references.",
    "inputs": [InputSpec(name="username", secret=True), InputSpec(name="password", secret=True)],
    "outputs": [OutputSpec(name="savings_balance", by="css", target='[data-field="balance"]',
                           type="money", sensitive=True)],
    "success_condition": SUCCESS,
}
