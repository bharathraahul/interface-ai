"""Mock banking data for a single user. In-memory only — no database."""

# The single user of this mock app.
USER = {"name": "Alex Johnson", "member_since": "2021"}

# Accounts. `type` is used only for display grouping.
ACCOUNTS = {
    "checking": {
        "name": "Everyday Checking",
        "type": "checking",
        "number": "****4821",
        "balance": 4820.55,
    },
    "savings": {
        "name": "High-Yield Savings",
        "type": "savings",
        "number": "****9930",
        "balance": 18750.20,
    },
    "credit": {
        "name": "Platinum Credit Card",
        "type": "credit",
        "number": "****1107",
        "balance": -1245.75,          # amount owed (negative = you owe)
        "credit_limit": 10000.00,
        "payment_due": 250.00,        # minimum payment due
        "due_date": "2026-09-28",
    },
}

# Transactions per account, newest first.
TRANSACTIONS = {
    "checking": [
        {"date": "2026-09-08", "description": "Whole Foods Market", "amount": -86.42},
        {"date": "2026-09-06", "description": "Paycheck - Acme Corp", "amount": 3200.00},
        {"date": "2026-09-05", "description": "Shell Gas Station", "amount": -54.10},
        {"date": "2026-09-03", "description": "Electric Bill", "amount": -122.35},
        {"date": "2026-09-01", "description": "Rent Payment", "amount": -1650.00},
    ],
    "savings": [
        {"date": "2026-09-01", "description": "Interest Earned", "amount": 31.20},
        {"date": "2026-08-25", "description": "Transfer from Checking", "amount": 500.00},
        {"date": "2026-08-01", "description": "Interest Earned", "amount": 29.85},
    ],
    "credit": [
        {"date": "2026-09-07", "description": "Amazon.com", "amount": -64.99},
        {"date": "2026-09-04", "description": "Starbucks", "amount": -6.75},
        {"date": "2026-09-02", "description": "Delta Airlines", "amount": -412.00},
        {"date": "2026-08-28", "description": "Payment Received - Thank You", "amount": 300.00},
    ],
}
