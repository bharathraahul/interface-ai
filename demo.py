"""Self-contained local demos. Terminal/evidence contain status and references only."""
import argparse
from contextlib import contextmanager
import json
import logging
from pathlib import Path
import socket
import threading
import time

import uvicorn
from artifact import Artifact
from handoff import Handoff
from outcomes import HardFailure, safe_code
from privacy import save_json
from runner import artifact_from, discover, replay
from surface import ACTIONS


@contextmanager
def bank_server(scenario="normal"):
    import main as bank
    if scenario not in bank.SCENARIOS:
        raise HardFailure("invalid_scenario")
    bank.SCENARIO = scenario
    bank.SESSIONS.clear()
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    # No access logs, tracebacks, request bodies or query strings in demo logs.
    config = uvicorn.Config(bank.app, log_config=None, access_log=False, log_level="critical")
    server = uvicorn.Server(config)
    thread = threading.Thread(target=server.run, kwargs={"sockets": [sock]}, daemon=True)
    thread.start()
    deadline = time.monotonic() + 5
    try:
        while not server.started:
            if not thread.is_alive() or time.monotonic() > deadline:
                raise HardFailure("network_failure")
            time.sleep(0.02)
        yield "http://127.0.0.1:" + str(port)
    finally:
        server.should_exit = True
        thread.join(timeout=6)
        sock.close()


def demo_inputs(member="first"):
    import data
    username = list(data.MEMBERS)[0 if member == "first" else 1]
    return {"username": username, "password": data.MEMBERS[username]["password"]}


def fixture_artifact():
    """Explicit manual fixture; never represented as an LLM-discovered artifact."""
    from dataclasses import replace
    keys = ["open_login", "fill_username", "fill_password", "sign_in", "open_savings", "read_balance"]
    return artifact_from([replace(ACTIONS[k], step=i) for i, k in enumerate(keys, 1)], "test_fixture")


def save_result(path, result, source, scenario):
    from main import SCENARIOS
    if source not in {"replay", "llm_discovery", "simulated_handoff"} or scenario not in SCENARIOS:
        raise HardFailure("invalid_inputs")
    # Never asdict(result): result.outputs belong only to the authorized caller.
    document = {"source": source, "scenario": scenario, "status": result.status,
                "code": result.message, "steps": result.steps,
                "output_references": ["out:savings_balance"] if result.ok else [],
                "events": result.evidence}
    from audit import evidence_safe
    if not evidence_safe(document):
        raise HardFailure("sensitive_data_blocked")
    save_json(path, document)
    return document


def load_artifact(path):
    try:
        if Path(path).stat().st_size > 65536:
            raise HardFailure("artifact_too_large")
        return Artifact.load(path)
    except HardFailure:
        raise
    except Exception:
        raise HardFailure("invalid_artifact") from None


class SafeParser(argparse.ArgumentParser):
    def error(self, message):
        self.exit(2, '{"status":"hard_failure","code":"invalid_inputs"}\n')


def main():
    logging.disable(logging.CRITICAL)
    parser = SafeParser(description=__doc__)
    parser.add_argument("command", choices=["fixture", "discover", "replay", "handoff"])
    parser.add_argument("--member", choices=["first", "second"], default="first")
    from main import SCENARIOS
    parser.add_argument("--scenario", choices=sorted(SCENARIOS), default="normal")
    parser.add_argument("--artifact", default="evidence/example-artifact.json")
    parser.add_argument("--evidence", default=None)
    args = parser.parse_args()
    try:
        if args.command == "fixture":
            artifact = fixture_artifact()
            artifact.save(args.artifact)
            print("Saved validated test fixture (not LLM discovery).")
            return 0
        scenario = "notice" if args.command == "handoff" else args.scenario
        source = "llm_discovery" if args.command == "discover" else "replay"
        output = args.evidence or "evidence/" + args.command + "-" + args.member + "-" + scenario + ".json"
        with bank_server(scenario) as base_url:
            kwargs = {"base_url": base_url}
            if args.command == "handoff":
                kwargs.update(headless=False, handoff=Handoff(timeout=60), deadline=90)
            if args.command == "discover":
                result, artifact = discover(demo_inputs(args.member), **kwargs)
                if artifact:
                    artifact.save(args.artifact)
            else:
                result = replay(load_artifact(args.artifact), demo_inputs(args.member), **kwargs)
        save_result(output, result, source, scenario)
        print(json.dumps({"status": result.status, "code": result.message,
                          "output_ref": "out:savings_balance" if result.ok else None}))
        return 0 if result.ok else 1
    except Exception as exc:
        print(json.dumps({"status": "hard_failure", "code": safe_code(exc)}))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
