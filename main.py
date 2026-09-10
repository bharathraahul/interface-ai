"""Mock banking app built with FastAPI. Single user, in-memory data."""

from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

import data

app = FastAPI(title="Mock Bank")
templates = Jinja2Templates(directory="templates")


def net_worth() -> float:
    """Sum of all account balances (credit balance is negative)."""
    return sum(acct["balance"] for acct in data.ACCOUNTS.values())


@app.get("/", response_class=HTMLResponse)
def dashboard(request: Request):
    return templates.TemplateResponse(
        "dashboard.html",
        {
            "request": request,
            "user": data.USER,
            "accounts": data.ACCOUNTS,
            "net_worth": net_worth(),
            "credit": data.ACCOUNTS["credit"],
        },
    )


@app.get("/account/{account_id}", response_class=HTMLResponse)
def account_detail(request: Request, account_id: str):
    account = data.ACCOUNTS.get(account_id)
    if account is None:
        raise HTTPException(status_code=404, detail="Account not found")
    return templates.TemplateResponse(
        "account.html",
        {
            "request": request,
            "user": data.USER,
            "account_id": account_id,
            "account": account,
            "transactions": data.TRANSACTIONS.get(account_id, []),
        },
    )


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="127.0.0.1", port=8000)
