"""Mock banking data — two members, each with their own accounts. In-memory only.

`password` here is the bank's own credential store (used to validate login). The
*agent* keeps its own copy of credentials in a secret store (see secrets_store.py) and
references them indirectly — it never embeds the raw value in a plan.
"""

import os
import secrets

# Synthetic fixtures only. Credentials are generated at startup or injected by the
# local demo caller; they are never committed, printed, or written to evidence.
MEMBERS = {
    "alex": {
        "display_name": "Alex Johnson",
        "password": os.environ.get("DEMO_MEMBER_ONE_PASSWORD") or secrets.token_urlsafe(24),
        "accounts": {
            "checking": {"name": "Everyday Checking", "type": "checking",
                         "number": "****4821", "balance": 4820.55},
            "savings": {"name": "High-Yield Savings", "type": "savings",
                        "number": "****9930", "balance": 18750.20},
            "credit": {"name": "Platinum Credit Card", "type": "credit",
                       "number": "****1107", "balance": -1245.75,
                       "credit_limit": 10000.00, "payment_due": 250.00,
                       "due_date": "2026-09-28"},
        },
        "transactions": {
            "checking": [
                {"date": "2026-09-08", "description": "Whole Foods Market", "amount": -86.42},
                {"date": "2026-09-06", "description": "Paycheck - Acme Corp", "amount": 3200.00},
                {"date": "2026-09-01", "description": "Rent Payment", "amount": -1650.00},
            ],
            "savings": [
                {"date": "2026-09-01", "description": "Interest Earned", "amount": 31.20},
                {"date": "2026-08-25", "description": "Transfer from Checking", "amount": 500.00},
            ],
            "credit": [
                {"date": "2026-09-07", "description": "Amazon.com", "amount": -64.99},
                {"date": "2026-08-28", "description": "Payment Received - Thank You", "amount": 300.00},
            ],
        },
    },
    "sam": {
        "display_name": "Sam Rivera",
        "password": os.environ.get("DEMO_MEMBER_TWO_PASSWORD") or secrets.token_urlsafe(24),
        "accounts": {
            "checking": {"name": "Everyday Checking", "type": "checking",
                         "number": "****3312", "balance": 2140.10},
            "savings": {"name": "High-Yield Savings", "type": "savings",
                        "number": "****7788", "balance": 9430.00},
            "credit": {"name": "Platinum Credit Card", "type": "credit",
                       "number": "****2255", "balance": -640.20,
                       "credit_limit": 6000.00, "payment_due": 75.00,
                       "due_date": "2026-09-30"},
        },
        "transactions": {
            "checking": [
                {"date": "2026-09-07", "description": "Trader Joe's", "amount": -52.18},
                {"date": "2026-09-05", "description": "Paycheck - Globex", "amount": 2400.00},
            ],
            "savings": [
                {"date": "2026-09-01", "description": "Interest Earned", "amount": 15.70},
            ],
            "credit": [
                {"date": "2026-09-06", "description": "Uber", "amount": -23.40},
            ],
        },
    },
}


def check_login(username, password):
    """Return the username if credentials are valid, else None."""
    member = MEMBERS.get(username)
    if member and member["password"] == password:
        return username
    return None
