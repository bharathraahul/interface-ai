"""Mock banking app with login and two members. In-memory sessions."""

import secrets as _secrets
import os
import copy
import time
from pathlib import Path

from fastapi import FastAPI, Request, Form, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

import data

app = FastAPI(title="Mock Bank")
templates = Jinja2Templates(directory=str(Path(__file__).parent / "templates"))

# session_id -> username. Cookie name below.
SESSIONS = {}
COOKIE = "mockbank_session"
SCENARIOS = {"normal", "nonexistent_member", "multiple_members", "no_savings", "multiple_savings",
             "zero", "negative", "unexpected_currency", "invalid_number", "missing_output",
             "wrong_member", "validation_error", "permission_denied", "session_expiry",
             "unexpected_login", "known_dialog", "unknown_dialog", "disabled", "hidden",
             "duplicate_label", "stale", "iframe", "changed_route", "changed_layout", "slow",
             "partial", "network_failure", "application_error", "prohibited_redirect", "new_tab",
             "injection", "notice"}
SCENARIO = os.environ.get("BANK_SCENARIO", "normal")
if SCENARIO not in SCENARIOS:
    raise RuntimeError("invalid_scenario")


def member_view(username):
    member = copy.deepcopy(data.MEMBERS[username])
    member["username"] = username
    savings = member["accounts"].get("savings")
    if SCENARIO == "no_savings":
        member["accounts"].pop("savings", None)
    elif SCENARIO == "multiple_savings":
        member["accounts"]["savings_extra"] = copy.deepcopy(savings)
    elif SCENARIO in {"zero", "negative"}:
        savings["balance"] = 0.0 if SCENARIO == "zero" else -12.34
    return member



def current_user(request: Request):
    """Return the logged-in username, or None."""
    return SESSIONS.get(request.cookies.get(COOKIE))


def net_worth(accounts):
    return sum(a["balance"] for a in accounts.values())


@app.get("/login", response_class=HTMLResponse)
def login_form(request: Request, error: str = ""):
    return templates.TemplateResponse(request=request, name="login.html", context={"error": "Sign in could not be completed" if error else ""})


@app.post("/login")
def login_submit(request: Request, username: str = Form(...), password: str = Form(...)):
    if SCENARIO in {"nonexistent_member", "validation_error"}:
        return templates.TemplateResponse(request=request, name="login.html",
                                          context={"error": "Sign in could not be completed"}, status_code=200)
    user = data.check_login(username, password)
    if not user:
        return templates.TemplateResponse(request=request, name="login.html", context={"error": "Sign in could not be completed"}, status_code=200)
    sid = _secrets.token_urlsafe(16)
    SESSIONS[sid] = ("sam" if user == "alex" else "alex") if SCENARIO == "wrong_member" else user
    resp = RedirectResponse("/", status_code=303)
    resp.set_cookie(COOKIE, sid, httponly=True, samesite="lax")
    return resp


@app.get("/logout")
def logout(request: Request):
    SESSIONS.pop(request.cookies.get(COOKIE), None)
    resp = RedirectResponse("/login", status_code=303)
    resp.delete_cookie(COOKIE)
    return resp


@app.get("/", response_class=HTMLResponse)
def dashboard(request: Request):
    user = current_user(request)
    if not user:
        return RedirectResponse("/login", status_code=303)
    member = member_view(user)
    return templates.TemplateResponse(request=request, name="dashboard.html", context={
        "request": request,
        "scenario": SCENARIO,
        "user": member,
        "accounts": member["accounts"],
        "net_worth": net_worth(member["accounts"]),
        "credit": member["accounts"]["credit"],
    })


@app.get("/account/{account_id}", response_class=HTMLResponse)
def account_detail(request: Request, account_id: str):
    user = current_user(request)
    if not user:
        return RedirectResponse("/login", status_code=303)
    if SCENARIO in {"session_expiry", "unexpected_login"}:
        if SCENARIO == "session_expiry":
            SESSIONS.pop(request.cookies.get(COOKIE), None)
        return RedirectResponse("/login", status_code=303)
    if SCENARIO == "permission_denied":
        return HTMLResponse("Unavailable", status_code=403)
    if SCENARIO == "application_error":
        return HTMLResponse("Unavailable", status_code=500)
    if SCENARIO == "prohibited_redirect":
        return RedirectResponse("https://example.invalid/", status_code=303)
    if SCENARIO == "changed_route":
        return RedirectResponse("/moved", status_code=303)
    if SCENARIO == "slow":
        time.sleep(0.5)
    if SCENARIO == "network_failure":
        time.sleep(4)
    member = member_view(user)
    account = member["accounts"].get(account_id)
    if account is None:
        raise HTTPException(status_code=404, detail="Account not found")
    return templates.TemplateResponse(request=request, name="account.html", context={
        "request": request,
        "scenario": SCENARIO,
        "user": member,
        "account_id": account_id,
        "account": account,
        "transactions": member["transactions"].get(account_id, []),
    })



@app.get("/api/session")
def verified_session(request: Request):
    """Trusted verification endpoint; raw response is only consumed in backend memory."""
    username = current_user(request)
    if not username:
        return HTMLResponse("Unavailable", status_code=401)
    member = member_view(username)
    return {"username": username, "member_matches": 2 if SCENARIO == "multiple_members" else 1,
            "accounts": [{"id": key, "type": account["type"],
                          "balance": format(account["balance"], ".2f"), "currency": "USD"}
                         for key, account in member["accounts"].items()]}

if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="127.0.0.1", port=8000, access_log=False, log_level="critical")
