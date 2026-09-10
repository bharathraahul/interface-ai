"""Goal runner — driven by an incoming request, not a fixed script.

A request says which account to open and which values to read back. The same
code serves any account; the browser layer's disambiguation rules pick the
right control for whatever the request names.

    Request:
        {
          "account": "Platinum Credit Card",       # human control to open
          "fields":  {"payment_due": "payment-due",# output_name -> data-field
                      "due_date":    "due-date"}
        }
    Result:
        {"payment_due": 250.0, "due_date": "2026-09-28", "success": True}

Run (with the bank app running on :8000):

    python goal.py                 # default request
    python goal.py savings         # a different, non-credit request
"""

import re
import sys

from browser import Browser, ControlNotFound, AmbiguousControl

# A few example requests to show the goal changes with the input.
REQUESTS = {
    "credit": {
        "account": "Platinum Credit Card",
        "fields": {"payment_due": "payment-due", "due_date": "due-date"},
    },
    "savings": {
        "account": "High-Yield Savings",
        "fields": {},  # savings has no payment due — the request asks for nothing extra
    },
}


def _maybe_money(text):
    """Turn '$250.00' into 250.0; leave other strings untouched."""
    if text and re.fullmatch(r"\$[\d,]+\.\d{2}", text.strip()):
        return float(text.strip().lstrip("$").replace(",", ""))
    return text


def run(request, base_url="http://127.0.0.1:8000", headless=True):
    result = {name: None for name in request.get("fields", {})}
    result["success"] = False

    with Browser(base_url=base_url, headless=headless) as b:
        # 1. OBSERVE — start at the dashboard and see what's actionable.
        b.goto("/")
        state = b.observe()
        print(f"observe: '{state['title']}', {len(state['controls'])} controls")

        # 2. CLICK — open whatever account the request names. The disambiguation
        #    rules resolve the account-card link even though the same name may
        #    appear in non-clickable copy (e.g. the payment-due banner).
        try:
            b.click(request["account"])
        except (ControlNotFound, AmbiguousControl) as e:
            print(f"click: {e}")
            return result

        # 3. WAIT — for the account page to load.
        if not b.wait_for("Transactions"):
            print("wait_for: account page never loaded")
            return result

        # 4. EXTRACT — read back exactly the fields the request asked for.
        for name, field in request.get("fields", {}).items():
            result[name] = _maybe_money(b.extract(f'[data-field="{field}"]'))

        # 5. CHECK — success = we reached an account page and got every field.
        result["success"] = b.check("Transactions") and all(
            result[name] is not None for name in request.get("fields", {})
        )

    return result


if __name__ == "__main__":
    key = sys.argv[1] if len(sys.argv) > 1 else "credit"
    request = REQUESTS.get(key)
    if request is None:
        print(f"unknown request {key!r}; try one of {list(REQUESTS)}")
        sys.exit(1)
    print("request:", request)
    print("result :", run(request))
