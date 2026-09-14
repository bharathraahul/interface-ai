"""Real Chromium integration tests; injected deciders/operators are labelled test-only."""
import copy
import json
import logging
import os
from pathlib import Path
import secrets
import sys
import time
import unittest
from unittest.mock import patch

from artifact import Artifact
from browser import Browser, AmbiguousControl
from demo import bank_server, demo_inputs, fixture_artifact, save_result
from handoff import Handoff
from outcomes import HardFailure, PolicyBlocked, RecoverableError, safe_code
from policy import Policy, BLOCK
from privacy import canonical_goal, redact_deep
from runner import discover, replay, parse_money, Run
from surface import ACTIONS

logging.disable(logging.CRITICAL)

class FixtureDecider:
    source = "test_fixture"
    def __init__(self):
        self.payloads = []
    def decide(self, observation, offered, completed, **kwargs):
        self.payloads.append(json.dumps([observation, offered, completed]))
        return next(k for k in offered if k != "wait_balance")


class PrivacyAssertions(unittest.TestCase):
    def assertNotIn(self, member, container, msg=None):
        # A failed privacy check must not print the private value it detected.
        self.assertTrue(member not in container, msg or "privacy boundary violated")


class ContractTests(PrivacyAssertions):
    def test_artifact_roundtrip_and_rejection(self):
        original = fixture_artifact().to_dict()
        self.assertEqual(Artifact.from_dict(original).to_dict(), original)
        mutations = [("schema_version", 2), ("version", True), ("metadata", {}),
                     ("checkpoints", []), ("success_condition", "anything"),
                     ("outputs", []), ("inputs", []), ("created_at", secrets.token_hex(8))]
        for key, value in mutations:
            document = copy.deepcopy(original)
            document[key] = value
            with self.subTest(key=key), self.assertRaises((HardFailure, TypeError)):
                Artifact.from_dict(document)
        for key, value in [("target", "body"), ("value_ref", "literal"), ("risky", True), ("description", "private")]:
            document = copy.deepcopy(original)
            document["actions"][1][key] = value
            with self.subTest(action_key=key), self.assertRaises(HardFailure):
                Artifact.from_dict(document)

    def test_parameters_rejected_before_browser_start(self):
        for params in [{}, {"username": "", "password": "x"}, {"username": 3, "password": "x"},
                       {"username": "x", "password": "x", "extra": True}, {"username": " x ", "password": "x"}]:
            result = replay(fixture_artifact(), params)
            self.assertEqual(result.message, "invalid_inputs")

    def test_invalid_replay_never_loads_model(self):
        with patch.dict(sys.modules, {"llm": None, "anthropic": None}):
            for artifact in [None, {}, "invalid"]:
                self.assertEqual(replay(artifact, demo_inputs()).message, "invalid_artifact")

    def test_evidence_audit_rejects_private_data(self):
        from audit import evidence_safe
        canary = secrets.token_hex(16)
        self.assertFalse(evidence_safe({"snapshot": {"label": canary}}))
        self.assertFalse(evidence_safe({canary: "login"}))
        self.assertFalse(evidence_safe({"steps": 99.99}))
        self.assertFalse(evidence_safe({"snapshot": {"url": "http://private.invalid"}}))

    def test_evidence_sink_blocks_before_writing(self):
        import tempfile
        from outcomes import Result
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "private.json"
            result = Result("success", evidence=[{"snapshot": {"label": secrets.token_hex(16)}}])
            with self.assertRaisesRegex(HardFailure, "sensitive_data_blocked"):
                save_result(path, result, "replay", "normal")
            self.assertFalse(path.exists())

    def test_money(self):
        for raw, expected in [("$0.00", "0.00"), ("$-12.34", "-12.34"), ("$1,234.56", "1234.56")]:
            self.assertEqual(str(parse_money(raw).amount), expected)
        for raw in [None, "EUR 2.00", "$1.234,56", "$1,2.00", "$NaN", "$12", "$1e3.00"]:
            with self.assertRaises(HardFailure):
                parse_money(raw)

    def test_policy(self):
        p = Policy()
        origin = "http://127.0.0.1:8000"
        for suffix in ["/login?password=canary", "/login#private", "/%6cogin", "/transfer", "/logout", "/login/../transfer"]:
            self.assertFalse(p.url_allowed(origin+suffix, origin))
        for url in ["https://127.0.0.1:8000/login", "http://evil.invalid/login", "file:///login", "http://user@127.0.0.1:8000/login"]:
            self.assertFalse(p.url_allowed(url, origin))
        self.assertFalse(p.url_allowed(origin+"/account/savings", origin, "POST"))
        self.assertEqual(Policy(allowed_domains=[]).evaluate("click", "/", "127.0.0.1:8000").verdict, BLOCK)
        self.assertEqual(Policy(allowed_routes=[]).evaluate("click", "/", "127.0.0.1:8000").verdict, BLOCK)

    def test_privacy_canonicalization(self):
        canary = secrets.token_urlsafe(24)
        self.assertNotIn(canary, canonical_goal("Savings balance for " + canary))
        self.assertNotIn(canary, json.dumps(redact_deep({canary: [canary, 123.45]})))
        self.assertEqual(safe_code(RuntimeError(canary)), "internal_error")


class BrowserTests(PrivacyAssertions):
    @classmethod
    def setUpClass(cls):
        cls.server = bank_server()
        cls.url = cls.server.__enter__()
        cls.artifact = fixture_artifact()

    @classmethod
    def tearDownClass(cls):
        cls.server.__exit__(None, None, None)

    def setUp(self):
        import main
        main.SCENARIO = "normal"
        main.SESSIONS.clear()

    def run_scenario(self, scenario, **kwargs):
        import main
        main.SCENARIO = scenario
        return replay(self.artifact, demo_inputs(), base_url=self.url, **kwargs)

    def test_reuse_fresh_outputs_without_model_access(self):
        import data
        with patch.dict(sys.modules, {"llm": None, "anthropic": None}):
            for member in ["first", "second"]:
                inputs = demo_inputs(member)
                result = replay(self.artifact, inputs, base_url=self.url)
                self.assertTrue(result.ok, result.message)
                self.assertTrue(result.outputs["savings_balance"]["amount"] ==
                                format(data.MEMBERS[inputs["username"]]["accounts"]["savings"]["balance"], ".2f"),
                                "output verification failed")
                save_result("evidence/replay-"+member+".json", result, "replay", "normal")
            result = self.run_scenario("zero")
            self.assertTrue(result.outputs["savings_balance"]["amount"] == "0.00", "output verification failed")
            result = self.run_scenario("negative")
            self.assertTrue(result.outputs["savings_balance"]["amount"] == "-12.34", "output verification failed")

    def test_discovery_privacy_and_prompt_injection(self):
        import main, data
        main.SCENARIO = "injection"
        decider = FixtureDecider()
        result, artifact = discover(demo_inputs(), base_url=self.url, decider=decider)
        self.assertTrue(result.ok, result.message)
        serialized = json.dumps([decider.payloads, result.evidence, artifact.to_dict()])
        for member in data.MEMBERS.values():
            self.assertNotIn(member["password"], serialized)
            self.assertNotIn(member["display_name"], serialized)
            for account in member["accounts"].values():
                self.assertNotIn(account["number"], serialized)
                self.assertNotIn(format(account["balance"], ".2f"), serialized)
        for username in data.MEMBERS:
            self.assertNotIn(username, serialized)
        self.assertNotIn("Ignore previous", serialized)
        self.assertNotIn(self.url, serialized)
        self.assertEqual(artifact.metadata["source"], "test_fixture")

    def test_failures(self):
        expected = {
            "nonexistent_member": "invalid_credentials", "validation_error": "invalid_credentials",
            "multiple_members": "multiple_members", "no_savings": "no_savings", "multiple_savings": "multiple_savings",
            "wrong_member": "wrong_member", "unexpected_currency": "unexpected_currency", "invalid_number": "invalid_money",
            "missing_output": "missing_control", "hidden": "hidden_control", "disabled": "disabled_control",
            "duplicate_label": "ambiguous_control", "changed_layout": "missing_control", "partial": "missing_control",
            "session_expiry": "session_expired", "unexpected_login": "session_expired",
            "permission_denied": "permission_denied", "application_error": "application_error",
            "unknown_dialog": "unknown_dialog", "iframe": "iframe_unsupported",
            "changed_route": "prohibited_navigation", "prohibited_redirect": "prohibited_navigation",
            "new_tab": "new_tab_blocked", "notice": "human_required",
        }
        summaries = []
        for scenario, code in expected.items():
            with self.subTest(scenario=scenario):
                result = self.run_scenario(scenario)
                self.assertFalse(result.ok)
                self.assertFalse(bool(result.outputs), "failure returned private outputs")
                self.assertEqual(result.message, code)
                summaries.append({"scenario": scenario, "status": result.status, "code": result.message})
                if scenario == "no_savings":
                    save_result("evidence/exceptional-replay.json", result, "replay", scenario)
                if scenario in {"wrong_member", "unknown_dialog", "duplicate_label", "prohibited_redirect"}:
                    save_result("evidence/failure-"+scenario+".json", result, "replay", scenario)
        from privacy import save_json
        save_json("evidence/scenario-results.json", summaries)

    def test_slow_and_known_dialog(self):
        for scenario in ["slow", "known_dialog"]:
            result = self.run_scenario(scenario)
            self.assertTrue(result.ok, result.message)

    def test_uncertain_action_not_repeated(self):
        for scenario in ["stale", "network_failure"]:
            result = self.run_scenario(scenario, timeout=600)
            self.assertFalse(result.ok)
            self.assertLessEqual(sum(e.get("action") == "open_savings" for e in result.evidence), 1)
            self.assertFalse(any(e.get("event") == "retry" for e in result.evidence))

    def test_model_errors_limits(self):
        class Bad(FixtureDecider):
            def decide(self, *args, **kwargs):
                return {"action": "read_balance", "private": secrets.token_hex(8)}
        result, _ = discover(demo_inputs(), base_url=self.url, decider=Bad())
        self.assertEqual(result.message, "malformed_model_action")
        class Unavailable(FixtureDecider):
            def decide(self, *args, **kwargs):
                raise RuntimeError(secrets.token_hex(8))
        result, _ = discover(demo_inputs(), base_url=self.url, decider=Unavailable())
        self.assertEqual(result.message, "model_unavailable")
        class Repeat(FixtureDecider):
            def decide(self, *args, **kwargs):
                return "fill_username"
        result, _ = discover(demo_inputs(), base_url=self.url, decider=Repeat())
        self.assertEqual(result.message, "repeated_action")
        result, _ = discover(demo_inputs(), base_url=self.url, decider=FixtureDecider(), step_limit=2)
        self.assertEqual(result.message, "step_limit")
        result, _ = discover(demo_inputs(), base_url=self.url, decider=FixtureDecider(), deadline=0.001)
        self.assertEqual(result.message, "deadline_exceeded")

    def test_exclusive_handoff_resumption(self):
        def operator(browser):
            original = browser.page
            with self.assertRaisesRegex(HardFailure, "automation_paused"):
                browser.fill('#username', "unused")
            browser.page.locator('#dismiss_notice').click()
            self.assertIs(browser.page, original)
            return "resume"
        result = self.run_scenario("notice", handoff=Handoff(operator=operator))
        self.assertTrue(result.ok, result.message)
        events = [e for e in result.evidence if e.get("event") == "human_actions"]
        self.assertTrue(events and any(a["control"] == "dismiss_notice" for a in events[0]["actions"]))
        save_result("evidence/handoff-simulated.json", result, "simulated_handoff", "notice")

    def test_handoff_stops(self):
        def close(browser):
            browser.page.close()
            return "resume"
        def navigate(browser):
            browser.page.goto(self.url + "/login")
            return "resume"
        for operator, code in [(lambda b: "cancel", "handoff_cancelled"),
                               (lambda b: "resume", "handoff_unresolved"),
                               (navigate, "manual_navigation"), (close, "browser_closed")]:
            with self.subTest(code=code):
                result = self.run_scenario("notice", handoff=Handoff(operator=operator))
                self.assertEqual(result.message, code)
                self.assertFalse(result.ok)
        result = self.run_scenario("notice", handoff=Handoff(timeout=0.001, operator=lambda b: "resume"))
        self.assertEqual(result.message, "operator_inactive")

    def test_raw_metadata_and_locator_ambiguity(self):
        with Browser(self.url) as browser:
            browser.goto('/login')
            canary = secrets.token_hex(16)
            browser.page.evaluate("value => {document.title=value; document.body.append(value); document.querySelector('#username').setAttribute('aria-label',value);}", canary)
            self.assertNotIn(canary, json.dumps(browser.observe()))
            with self.assertRaises(HardFailure):
                browser.observe(sanitize=False)
            browser.page.evaluate("document.querySelector('form').append(document.querySelector('#username').cloneNode())")
            with self.assertRaises(AmbiguousControl):
                browser.fill('#username', canary)
            with self.assertRaises(AmbiguousControl):
                browser.observe()

    def test_output_requires_backend_agreement(self):
        from runner import verify_output, parameters
        inputs = demo_inputs()
        run = Run(inputs, self.url, True, 3000, 16, 60, None, None)
        with run.browser:
            for key in ["open_login", "fill_username", "fill_password", "sign_in", "open_savings"]:
                run.step(ACTIONS[key])
            with self.assertRaisesRegex(HardFailure, "output_mismatch"):
                verify_output(run.browser, parameters(inputs), "$0.00")
            run.browser.page.evaluate("document.body.dataset.member = 'unexpected'")
            with self.assertRaisesRegex(HardFailure, "wrong_member"):
                verify_output(run.browser, parameters(inputs), "$0.00")

    def test_read_retry_limit(self):
        from runner import Run
        run = Run(demo_inputs(), self.url, True, 3000, 16, 60, None, None)
        with run.browser:
            run.step(ACTIONS['open_login'])
            with patch.object(run, 'state', side_effect=RecoverableError('verification_unavailable')) as read:
                with self.assertRaises(RecoverableError):
                    run.observed()
                self.assertEqual(read.call_count, 3)
                self.assertEqual(sum(e.get('event') == 'retry' for e in run.evidence), 2)


if __name__ == '__main__':
    unittest.main()
