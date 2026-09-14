"""Fail-closed policy shared by tools and context-wide network interception."""
import re
from dataclasses import dataclass, field
from urllib.parse import urlsplit

ALLOW, CONFIRM, BLOCK = "ALLOW", "CONFIRM", "BLOCK"

@dataclass
class Decision:
    verdict: str
    reason: str = ""

@dataclass
class Policy:
    allowed_domains: list = field(default_factory=lambda: ["127.0.0.1:8000"])
    allowed_routes: list = field(default_factory=lambda: [r"/", r"/login", r"/account/savings"])
    allowed_actions: set = field(default_factory=lambda: {"navigate", "click", "fill", "wait", "extract"})
    blocked_routes: list = field(default_factory=lambda: [r"/transfer", r"/payment", r"/delete", r"/logout"])
    confirm_routes: list = field(default_factory=list)
    risky_labels: list = field(default_factory=lambda: ["transfer", "pay", "delete", "send"])

    def evaluate(self, tool, route=None, domain=None, label=None):
        if tool not in self.allowed_actions or domain not in self.allowed_domains:
            return Decision(BLOCK, "action_or_domain_denied")
        if route is None or any(re.search(p, route) for p in self.blocked_routes):
            return Decision(BLOCK, "route_denied")
        if not any(re.fullmatch(p, route) for p in self.allowed_routes):
            return Decision(BLOCK, "route_denied")
        if any(re.search(p, route) for p in self.confirm_routes):
            return Decision(CONFIRM, "approval_required")
        if label and any(w in label.lower() for w in self.risky_labels):
            return Decision(CONFIRM, "approval_required")
        return Decision(ALLOW)

    def url_allowed(self, url, base_url, method="GET"):
        try:
            parsed, base = urlsplit(url), urlsplit(base_url)
            # Exact origin, no userinfo, fragments, query payloads, alternate schemes,
            # encoded route tricks or ambiguous authorities. Redirects use this too.
            if (parsed.scheme, parsed.netloc) != (base.scheme, base.netloc):
                return False
            if parsed.scheme not in {"http", "https"} or parsed.username or parsed.password:
                return False
            if parsed.query or parsed.fragment or "%" in parsed.path or "\\" in url:
                return False
            if parsed.netloc not in self.allowed_domains:
                return False
            if method == "GET" and parsed.path == "/api/session":
                return True  # backend verification only; never an agent action
            if method not in {"GET", "POST"} or (method == "POST" and parsed.path != "/login"):
                return False
            return self.evaluate("navigate", parsed.path or "/", parsed.netloc).verdict == ALLOW
        except (ValueError, TypeError):
            return False


def route_of(url):
    parsed = urlsplit(url)
    return parsed.path or "/", parsed.netloc
