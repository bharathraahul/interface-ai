"""Regression checks for boundary failures; model responses/operators remain test doubles."""
import copy
import io
import json
import os
from pathlib import Path
import secrets
import tempfile
import time
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from artifact import Artifact
from browser import Browser, AmbiguousControl
from demo import bank_server, demo_inputs, fixture_artifact
from handoff import Handoff
from llm import Decider
from outcomes import HardFailure, RecoverableError, PolicyBlocked
from policy import Policy
from privacy import model_payload
from runner import Run, discover, identity, parameters, parse_money, replay
from surface import ACTIONS
from test_workflow import FixtureDecider

OBSERVATION = {"surface_version": 1, "route": "login", "controls": [], "untrusted_page_data": True}


class EdgeContractTests(unittest.TestCase):
    def test_artifact_nested_types_and_wait_order(self):
        original = fixture_artifact().to_dict()
        mutations = [lambda d: d['actions'][0].update(risky=0),
                     lambda d: d['checkpoints'][0].update(after_step=True),
                     lambda d: d['metadata']['recovery'].update(observation_retries=2.0),
                     lambda d: d.update(created_at='2026-99-99T00:00:00+00:00'),
                     lambda d: d['actions'][0].pop('risky'),
                     lambda d: d.update(actions=None)]
        for change in mutations:
            d = copy.deepcopy(original)
            change(d)
            with self.assertRaises(HardFailure):
                Artifact.from_dict(d)
        d = copy.deepcopy(original)
        d['actions'].append({**d['actions'][-1], 'step': 7, 'tool': 'wait'})
        with self.assertRaisesRegex(HardFailure, 'invalid_wait_sequence'):
            Artifact.from_dict(d)

    def test_artifact_file_errors_do_not_echo_contents(self):
        canary = secrets.token_hex(20)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'artifact.json'
            for content in [canary, '{"schema_version":1,"schema_version":2}', 'x' * 65537]:
                path.write_text(content)
                with self.assertRaises(HardFailure) as failure:
                    Artifact.load(path)
                self.assertTrue(canary not in str(failure.exception), 'private error escaped')

    def test_numeric_limits_are_strict(self):
        for options in [{'timeout': True}, {'step_limit': 2.5}, {'deadline': float('nan')}, {'deadline': float('inf')}]:
            self.assertEqual(replay(fixture_artifact(), demo_inputs(), **options).message, 'invalid_inputs')
        for value in ['$' + '1' * 70 + '.00', '$１２.００', '$١٢.٠٠']:
            with self.assertRaises(HardFailure):
                parse_money(value)

    def test_model_boundary_rejects_untrusted_metadata(self):
        for key in ['url', 'title', 'text', 'screenshots', 'trace']:
            observation = {**OBSERVATION, key: secrets.token_hex(20)}
            with self.assertRaisesRegex(HardFailure, 'sensitive_data_blocked'):
                model_payload(observation, ['fill_username'], [])
        for controls in [[{'id': 'username', 'label': secrets.token_hex(20), 'visible': True, 'enabled': True}],
                         [{'id': 'username', 'label': 'Username', 'visible': 'private', 'enabled': True}]]:
            with self.assertRaises(HardFailure):
                model_payload({**OBSERVATION, 'controls': controls}, ['fill_username'], [])
        with self.assertRaises(HardFailure):
            model_payload(OBSERVATION, ['fill_username'], [secrets.token_hex(20)])

    def model(self):
        # Use the production parser/request builder, replacing only the transport.
        with patch.dict(os.environ, {'ANTHROPIC_API_KEY': secrets.token_hex(20), 'ANTHROPIC_MODEL': 'test-model'}), \
                patch('anthropic.Anthropic') as client:
            decider = Decider()
            decider.client = client.return_value
            return decider

    def test_provider_payload_and_valid_response(self):
        decider = self.model()
        decider.client.messages.create.return_value = SimpleNamespace(stop_reason='tool_use', content=[
            SimpleNamespace(type='tool_use', name='next_action', input={'action': 'fill_username'})])
        self.assertEqual(decider.decide(OBSERVATION, ['fill_username'], [], timeout=2), 'fill_username')
        request = decider.client.messages.create.call_args.kwargs
        self.assertEqual(request['timeout'], 2)
        payload = json.loads(request['messages'][0]['content'])
        self.assertEqual(payload, model_payload(OBSERVATION, ['fill_username'], []))

    def test_provider_malformed_responses(self):
        decider = self.model()
        good = SimpleNamespace(type='tool_use', name='next_action', input={'action': 'fill_username'})
        responses = [None, SimpleNamespace(stop_reason='tool_use', content=None),
                     SimpleNamespace(stop_reason='max_tokens', content=[good]),
                     SimpleNamespace(stop_reason='tool_use', content=[]),
                     SimpleNamespace(stop_reason='tool_use', content=[good, good])]
        for data in [{'action': 'read_balance'}, {'action': 'fill_username', 'value': secrets.token_hex(20)},
                     {'action': 1}, {}, 'invalid']:
            responses.append(SimpleNamespace(stop_reason='tool_use', content=[
                SimpleNamespace(type='tool_use', name='next_action', input=data)]))
        responses.append(SimpleNamespace(stop_reason='tool_use', content=[
            SimpleNamespace(type='tool_use', name='unexpected', input={'action': 'fill_username'})]))
        for response in responses:
            decider.client.messages.create.return_value = response
            with self.assertRaisesRegex(HardFailure, 'malformed_model_action'):
                decider.decide(OBSERVATION, ['fill_username'], [])

    def test_provider_unavailable_and_deadline(self):
        decider = self.model()
        decider.client.messages.create.side_effect = RuntimeError(secrets.token_hex(20))
        with self.assertRaisesRegex(RecoverableError, 'model_unavailable'):
            decider.decide(OBSERVATION, ['fill_username'], [])
        self.assertEqual(decider.client.messages.create.call_count, 1)
        with self.assertRaisesRegex(HardFailure, 'deadline_exceeded'):
            decider.decide(OBSERVATION, ['fill_username'], [], timeout=0)
        self.assertEqual(decider.client.messages.create.call_count, 1)
        with patch.dict(os.environ, {}, clear=True), self.assertRaisesRegex(RecoverableError, 'model_unavailable'):
            Decider()

    def test_failed_browser_start_cleans_up_driver(self):
        with patch('browser.sync_playwright') as factory:
            driver = factory.return_value.start.return_value
            driver.chromium.launch.side_effect = RuntimeError(secrets.token_hex(20))
            with self.assertRaisesRegex(HardFailure, 'browser_unavailable'):
                Browser().start()
            driver.stop.assert_called_once()

    def test_request_guard_never_sends_denied_requests(self):
        browser = Browser()
        for url, method in [('https://example.invalid/login', 'GET'),
                            ('http://127.0.0.1:8000/login?private=' + secrets.token_hex(20), 'GET'),
                            ('http://127.0.0.1:8000/account/savings', 'POST')]:
            route = Mock(request=SimpleNamespace(url=url, method=method))
            browser._guard_request(route)
            route.fetch.assert_not_called()
            route.abort.assert_called_once()

    def test_network_transport_failure_aborts_without_retry(self):
        browser = Browser()
        route = Mock(request=SimpleNamespace(url=browser.base_url + '/login', method='GET'))
        route.fetch.side_effect = TimeoutError(secrets.token_hex(20))
        browser._guard_request(route)
        self.assertEqual(browser.problem, 'network_failure')
        route.fetch.assert_called_once()
        route.abort.assert_called_once()

    def test_sdk_diagnostics_do_not_emit_private_values(self):
        import logging
        stream = io.StringIO()
        root = logging.getLogger()
        handlers, disabled = root.handlers[:], logging.root.manager.disable
        try:
            root.handlers = [logging.StreamHandler(stream)]
            logging.disable(logging.NOTSET)
            self.model()
            canary = secrets.token_hex(20)
            for name in ['anthropic', 'anthropic._base_client', 'httpx', 'httpcore', 'httpcore.future_child']:
                logging.getLogger(name).critical(canary)
            self.assertTrue(canary not in stream.getvalue(), 'SDK diagnostics leaked private data')
        finally:
            root.handlers = handlers
            logging.disable(disabled)

    def test_handoff_snapshot_failure_never_leaves_human_ownership(self):
        browser = SimpleNamespace(guard=lambda: None, owner='automation', human_events=[],
                                  observe=Mock(side_effect=HardFailure('ambiguous_control')))
        evidence = []
        with self.assertRaisesRegex(HardFailure, 'ambiguous_control'):
            Handoff(operator=lambda b: 'resume').resolve(browser, lambda: None, evidence)
        self.assertEqual(browser.owner, 'stopped')
        self.assertTrue(any(e.get('event') == 'handoff_stopped' for e in evidence))

    def test_console_reader_handles_partial_input_and_eof(self):
        read_fd, write_fd = os.pipe()
        try:
            with os.fdopen(read_fd, 'r') as stream, patch('sys.stdin', stream):
                handoff = Handoff()
                self.assertIsNone(handoff.read_command())
                os.write(write_fd, b'resu')
                self.assertIsNone(handoff.read_command())
                os.write(write_fd, b'me\n')
                self.assertEqual(handoff.read_command(), 'resume')
                os.write(write_fd, secrets.token_bytes(16) + b'\n')
                self.assertEqual(handoff.read_command(), 'cancel')
                os.close(write_fd)
                write_fd = None
                self.assertEqual(handoff.read_command(), 'cancel')
        finally:
            if write_fd is not None:
                os.close(write_fd)


class EdgeBrowserTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = bank_server()
        cls.url = cls.server.__enter__()

    @classmethod
    def tearDownClass(cls):
        cls.server.__exit__(None, None, None)

    def setUp(self):
        import main
        main.SCENARIO = 'normal'
        main.SESSIONS.clear()

    def run_to_dashboard(self):
        run = Run(demo_inputs(), self.url, True, 1500, 16, 30, None, None)
        run.browser.start()
        for key in ['open_login', 'fill_username', 'fill_password', 'sign_in']:
            run.step(ACTIONS[key])
        self.addCleanup(run.browser.stop)
        return run

    def test_discovery_scenario_matrix(self):
        import main
        expected = {
            'normal': '', 'zero': '', 'negative': '', 'known_dialog': '', 'slow': '', 'injection': '',
            'nonexistent_member': 'invalid_credentials', 'validation_error': 'invalid_credentials',
            'multiple_members': 'multiple_members', 'no_savings': 'no_savings', 'multiple_savings': 'multiple_savings',
            'wrong_member': 'wrong_member', 'unexpected_currency': 'unexpected_currency', 'invalid_number': 'invalid_money',
            'missing_output': 'missing_control', 'hidden': 'hidden_control', 'disabled': 'disabled_control',
            'duplicate_label': 'ambiguous_control', 'changed_layout': 'missing_control', 'partial': 'missing_control',
            'session_expiry': 'session_expired', 'unexpected_login': 'session_expired',
            'permission_denied': 'permission_denied', 'application_error': 'application_error',
            'unknown_dialog': 'unknown_dialog', 'iframe': 'iframe_unsupported',
            'changed_route': 'prohibited_navigation', 'prohibited_redirect': 'prohibited_navigation',
            'new_tab': 'new_tab_blocked', 'notice': 'human_required',
            'stale': {'checkpoint_failed', 'uncertain_action'},
            'network_failure': {'network_failure', 'uncertain_action'},
        }
        self.assertEqual(set(expected), main.SCENARIOS)
        for scenario, code in expected.items():
            with self.subTest(scenario=scenario):
                main.SCENARIO = scenario
                result, artifact = discover(demo_inputs(), base_url=self.url, decider=FixtureDecider(), timeout=1500)
                # A network timer and a browser-action timer can race. Neither
                # permits retry when the action's effects cannot be established.
                self.assertIn(result.message, code if isinstance(code, set) else {code})
                self.assertEqual(result.ok, code == '')
                if scenario in {'stale', 'network_failure'}:
                    self.assertFalse(any(e.get('event') == 'retry' for e in result.evidence))
                if code:
                    self.assertIsNone(artifact)
                    self.assertFalse(bool(result.outputs), 'failure returned private outputs')

    def test_html_dialog_variants_and_hidden_dialog(self):
        run = self.run_to_dashboard()
        for markup in ['<dialog open>Untrusted</dialog>', '<div role="alertdialog">Untrusted</div>',
                       '<div aria-modal="true">Untrusted</div>']:
            run.browser.page.evaluate('html => document.body.insertAdjacentHTML("beforeend", html)', markup)
            with self.assertRaisesRegex(RecoverableError, 'unknown_dialog'):
                run.state()
            run.browser.page.evaluate("document.body.lastElementChild.remove()")
        run.browser.page.evaluate('document.body.insertAdjacentHTML("beforeend", \'<div role="dialog" hidden>Hidden</div>\')')
        self.assertEqual(run.state()['route'], 'dashboard')

    def test_backend_schema_rejects_ambiguous_types(self):
        run = self.run_to_dashboard()
        original = run.browser.backend_state()
        cases = [None, [], {}, {**original, 'member_matches': True}, {**original, 'member_matches': '1'},
                 {**original, 'accounts': [None]}, {**original, 'accounts': 'private'},
                 {**original, 'extra': secrets.token_hex(20)}]
        for state in cases:
            with patch.object(run.browser, 'backend_state', return_value=state), \
                    self.assertRaisesRegex(HardFailure, 'verification_failed'):
                identity(run.browser, run.inputs)

    def test_verification_http_errors_and_recovery(self):
        run = self.run_to_dashboard()
        for status, code in [(401, 'session_expired'), (403, 'permission_denied'), (503, 'verification_unavailable'),
                             (429, 'verification_unavailable'), (302, 'verification_failed')]:
            with patch.object(run.browser.context.request, 'get', return_value=Mock(status=status)), \
                    self.assertRaisesRegex((HardFailure, RecoverableError), code):
                run.browser.backend_state()
        state = run.browser.backend_state()
        completed = len(run.actions)
        with patch.object(run.browser, 'backend_state', side_effect=[RecoverableError('verification_unavailable'), state]) as read:
            self.assertEqual(run.observed()['route'], 'dashboard')
            self.assertEqual(read.call_count, 2)
            self.assertEqual(len(run.actions), completed)
        response = Mock(status=200)
        response.json.side_effect = ValueError(secrets.token_hex(20))
        with patch.object(run.browser.context.request, 'get', return_value=response), \
                self.assertRaisesRegex(HardFailure, 'verification_failed'):
            run.browser.backend_state()

    def test_native_prompt_and_confirm_stop(self):
        with Browser(self.url) as browser:
            browser.goto('/login')
            for kind in ['prompt', 'confirm']:
                browser.page.evaluate('kind => window[kind]("Unexpected request")', kind)
                with self.assertRaisesRegex(RecoverableError, 'unknown_dialog'):
                    browser.guard()
                browser.problem = None  # test isolation between the two independent dialogs

    def test_optional_wait_replay_and_repetition_bound(self):
        from dataclasses import replace
        from runner import artifact_from
        actions = fixture_artifact().actions
        actions.insert(-1, ACTIONS['wait_balance'])
        artifact = artifact_from([replace(action, step=i) for i, action in enumerate(actions, 1)], 'test_fixture')
        self.assertTrue(replay(artifact, demo_inputs(), base_url=self.url).ok)
        class Wait(FixtureDecider):
            def decide(self, observation, offered, completed, **kwargs):
                return 'wait_balance' if 'wait_balance' in offered else offered[0]
        result, artifact = discover(demo_inputs(), base_url=self.url, decider=Wait())
        self.assertEqual(result.message, 'repeated_action')
        self.assertIsNone(artifact)
        self.assertEqual(sum(e.get('action') == 'wait_balance' and 'step' in e for e in result.evidence), 2)
        with Browser(self.url) as browser:
            browser.goto('/login')
            self.assertFalse(browser.wait_for('[data-field="balance"]', by='css', timeout=50))

    def test_locator_labels_and_hidden_duplicates(self):
        with Browser(self.url) as browser:
            browser.goto('/login')
            browser.page.evaluate('''document.querySelector('form').insertAdjacentHTML('beforeend',
                '<label for="other">Username</label><input id="other">');''')
            with self.assertRaises(AmbiguousControl):
                browser.resolve('Username', by='label')
            browser.page.evaluate('''let copy = document.querySelector('#password').cloneNode();
                                    copy.hidden = true; document.body.append(copy);''')
            with self.assertRaises(AmbiguousControl):
                browser.resolve('#password')

    def test_policy_applies_to_both_execution_modes(self):
        from urllib.parse import urlsplit
        domain = urlsplit(self.url).netloc
        cases = [Policy(allowed_domains=[]), Policy(allowed_domains=[domain], allowed_routes=[]),
                 Policy(allowed_domains=[domain], allowed_actions={'navigate'}),
                 Policy(allowed_domains=[domain], confirm_routes=['/login'])]
        for policy in cases:
            for mode in ['discovery', 'replay']:
                with self.subTest(mode=mode):
                    if mode == 'discovery':
                        result, _ = discover(demo_inputs(), base_url=self.url, policy=policy, decider=FixtureDecider())
                    else:
                        result = replay(fixture_artifact(), demo_inputs(), base_url=self.url, policy=policy)
                    self.assertEqual(result.status, 'hard_failure')
                    self.assertFalse(bool(result.outputs), 'denied policy returned private outputs')

    def test_risky_label_and_tampered_login_form(self):
        from executor import execute
        run = Run(demo_inputs(), self.url, True, 1500, 16, 30, None, None)
        with run.browser:
            for key in ['open_login', 'fill_username', 'fill_password']:
                run.step(ACTIONS[key])
            run.browser.page.evaluate("document.querySelector('form').action='/transfer'")
            with self.assertRaisesRegex(PolicyBlocked, 'unsafe_submit'):
                execute(run.browser, ACTIONS['sign_in'], run.secrets, run.browser.policy)
            run.browser.page.evaluate("document.querySelector('form').action='/login'; document.querySelector('button').textContent='Transfer'")
            with self.assertRaisesRegex(PolicyBlocked, 'approval_required'):
                execute(run.browser, ACTIONS['sign_in'], run.secrets, run.browser.policy)

    def test_operator_idle_and_wrong_member(self):
        import main
        main.SCENARIO = 'notice'
        result = replay(fixture_artifact(), demo_inputs(), base_url=self.url,
                        handoff=Handoff(timeout=0.15, command_reader=lambda: None))
        self.assertEqual(result.message, 'operator_inactive')
        def operator(browser):
            browser.page.locator('#dismiss_notice').click()
            browser.page.evaluate("document.body.dataset.member='unexpected'")
            return 'resume'
        result = replay(fixture_artifact(), demo_inputs(), base_url=self.url, handoff=Handoff(operator=operator))
        self.assertEqual(result.message, 'wrong_member')

    def test_model_returning_after_deadline_cannot_act(self):
        class Late(FixtureDecider):
            def decide(self, observation, offered, completed, **kwargs):
                time.sleep(0.15)
                return offered[0]
        # Expire the run precisely when deciding, independently of startup timing.
        from runner import Run as ActualRun
        def make_run(*args, **kwargs):
            run = ActualRun(*args, **kwargs)
            original_observed = run.observed
            def observed():
                snapshot = original_observed()
                run.deadline = time.monotonic() + 0.05
                run.browser.deadline = run.deadline
                return snapshot
            run.observed = observed
            return run
        with patch('runner.Run', side_effect=make_run):
            result, artifact = discover(demo_inputs(), base_url=self.url, decider=Late())
        self.assertEqual(result.message, 'deadline_exceeded')
        self.assertEqual(result.steps, 1)
        self.assertIsNone(artifact)
