"""Deny-by-default telemetry. No raw page text, goals, errors, URLs or images."""
import json
import re
from pathlib import Path

_PATTERNS = [re.compile(r"(?:\$|€|£)\s*-?[\d,]+(?:\.\d+)?"),
             re.compile(r"\*{2,}\d{3,}"), re.compile(r"\b\d{6,}\b"),
             re.compile(r"(?:sk-ant-|sk-proj-)[A-Za-z0-9_-]+")]


def redact(text):
    # Compatibility helper; arbitrary free text is never safe to retain.
    return "[REDACTED]" if isinstance(text, str) and text else text


def redact_deep(value):
    if isinstance(value, str):
        return redact(value)
    if isinstance(value, dict):
        return {f"field_{i}": redact_deep(v) for i, v in enumerate(value.values())}
    if isinstance(value, (list, tuple)):
        return [redact_deep(v) for v in value]
    return None  # numeric values can also be sensitive


def contains_sensitive(text):
    return isinstance(text, str) and any(p.search(text) for p in _PATTERNS)


def canonical_goal(message):
    """The caller selects this one supported intent; discard the original message."""
    from outcomes import HardFailure
    if not isinstance(message, str) or not 0 < len(message) <= 4096:
        raise HardFailure("invalid_goal")
    if not re.search(r"\bsavings\b", message, re.I) or not re.search(r"\bbalance\b", message, re.I):
        raise HardFailure("unsupported_goal")
    return "Retrieve the authenticated member's savings balance using input references."


def save_json(path, value):
    """Internal sink: accepts only validated artifacts or constructed safe events."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2) + "\n")


def model_payload(observation, offered, completed):
    """Validate the outgoing model boundary independently of the browser adapter."""
    from outcomes import HardFailure
    from surface import ACTIONS, CONTROLS, ROUTES
    try:
        valid = (type(observation) is dict
                 and set(observation) == {"surface_version", "route", "controls", "untrusted_page_data"}
                 and type(observation["surface_version"]) is int and observation["surface_version"] == 1
                 and observation["route"] in ROUTES.values()
                 and observation["untrusted_page_data"] is True
                 and type(observation["controls"]) is list
                 and len(observation["controls"]) <= len(CONTROLS))
        seen = set()
        if not valid:
            raise ValueError()
        for control in observation["controls"]:
            if (type(control) is not dict or set(control) != {"id", "label", "visible", "enabled"}
                    or control["id"] not in CONTROLS or control["id"] in seen
                    or control["label"] != CONTROLS[control["id"]][1]
                    or type(control["visible"]) is not bool or type(control["enabled"]) is not bool):
                raise ValueError()
            seen.add(control["id"])
        if (type(offered) is not list or not offered or len(offered) > len(ACTIONS)
                or type(completed) is not list or len(completed) > 64
                or any(type(key) is not str or key not in ACTIONS for key in offered + completed)):
            raise ValueError()
    except (ValueError, KeyError, TypeError):
        raise HardFailure("sensitive_data_blocked") from None
    return {"goal": "Retrieve savings balance", "observation": observation,
            "offered_actions": offered, "completed": completed,
            "input_references": ["secret:username", "secret:password"]}
