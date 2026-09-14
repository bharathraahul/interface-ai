"""Exclusive control of the existing live page; bounded local operator handoff."""
import queue
import threading
import time
from outcomes import HardFailure

class Handoff:
    def __init__(self, timeout=60, operator=None):
        self.timeout = timeout
        self.operator = operator  # injected test operator; production uses local console

    def resolve(self, browser, validate, evidence):
        browser.guard()
        browser.owner = "human"
        before = len(browser.human_events)
        evidence.append({"event": "handoff_started", "owner": "human", "same_session": True,
                         "snapshot": browser.observe()})
        started = time.monotonic()
        commands = queue.Queue()
        try:
            if self.operator:
                command = self.operator(browser)
                commands.put(command)
            else:
                # Console input is consumed once, never logged or sent to the model.
                print("Automation paused. Resolve the notice in the live browser; enter resume or cancel.")
                def read_command():
                    try:
                        commands.put(input().strip())
                    except (EOFError, OSError):
                        commands.put("cancel")
                threading.Thread(target=read_command, daemon=True).start()
            while True:
                if time.monotonic() - started >= self.timeout:
                    raise HardFailure("operator_inactive")
                browser.guard()
                browser.page.wait_for_timeout(50)  # pump browser events while automation is paused
                browser.guard()
                if time.monotonic() - started >= self.timeout:
                    raise HardFailure("operator_inactive")
                if any(event["kind"] == "navigation" for event in browser.human_events[before:]):
                    raise HardFailure("manual_navigation")
                try:
                    command = commands.get_nowait()
                except queue.Empty:
                    continue
                if command != "resume":
                    raise HardFailure("handoff_cancelled")
                validate()  # route, identity, modal and expected checkpoint must all hold
                evidence.append({"event": "handoff_resumed", "state_verified": True})
                browser.owner = "automation"
                return
        except Exception:
            # Failure is terminal: the runner closes the browser, never silently resumes.
            browser.owner = "stopped"
            evidence.append({"event": "handoff_stopped"})
            raise
        finally:
            evidence.append({"event": "human_actions", "actions": browser.human_events[before:]})
