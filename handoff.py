"""Exclusive control of the existing live page; bounded local operator handoff."""
import queue
import os
import select
import sys
import time
from outcomes import HardFailure

class Handoff:
    def __init__(self, timeout=60, operator=None, command_reader=None):
        self.timeout = timeout
        self.operator = operator  # injected test operator; production uses local console
        self.command_reader = command_reader
        self._pending = b""

    def read_command(self):
        """Poll a Unix terminal/pipe without a background reader surviving timeout."""
        if self.command_reader:
            return self.command_reader()
        try:
            fd = sys.stdin.fileno()
            if not select.select([fd], [], [], 0)[0]:
                return None
            chunk = os.read(fd, 1024)
            if not chunk or len(self._pending) + len(chunk) > 1024:
                self._pending = b""
                return "cancel"
            self._pending += chunk
            if b"\n" not in self._pending:
                return None
            command = self._pending.split(b"\n", 1)[0].strip()
            self._pending = b""
            return "resume" if command == b"resume" else "cancel"
        except (OSError, ValueError, AttributeError):
            return "cancel"

    def resolve(self, browser, validate, evidence):
        browser.guard()
        if type(self.timeout) not in {int, float} or not 0 < self.timeout <= 300:
            raise HardFailure("invalid_inputs")
        browser.owner = "human"
        before = len(browser.human_events)
        started = time.monotonic()
        commands = queue.Queue()
        try:
            evidence.append({"event": "handoff_started", "owner": "human", "same_session": True,
                             "snapshot": browser.observe()})
            if self.operator:
                command = self.operator(browser)
                commands.put(command)
            else:
                # Console input is consumed once, never logged or sent to the model.
                print("Automation paused. Resolve the notice in the live browser; enter resume or cancel.")
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
                if not self.operator:
                    pending = self.read_command()
                    if pending is not None:
                        commands.put(pending)
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
            self._pending = b""
            evidence.append({"event": "human_actions", "actions": browser.human_events[before:]})
