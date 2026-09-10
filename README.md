# Mock Bank

A simple mock banking web app for a single user, built with FastAPI.
Shows checking, savings, and credit card accounts with transactions and the
credit card payment due. All data is in-memory (`data.py`) — no database.

## Run

```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
python main.py
```

Then open http://127.0.0.1:8000

## Files

- `main.py` — FastAPI app and routes
- `data.py` — mock user, accounts, and transactions
- `templates/` — HTML pages (dashboard + account detail)
