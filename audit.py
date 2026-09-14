"""Scan saved project/evidence files without printing matches or private values."""
import json
import os
from pathlib import Path
import re

from artifact import Artifact
from outcomes import CODES
from surface import ACTIONS, CONTROLS

IGNORED = {'.git', '.claude', '.venv', 'venv', '__pycache__', '.pytest_cache', 'node_modules'}
# Catch actual assigned credentials, private keys and provider tokens. The source
# fixture data is synthetic and deliberately retained; no fixture password is literal.
PATTERNS = [re.compile(r'-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----'),
            re.compile(r'\bsk-(?:ant-|proj-)[A-Za-z0-9_-]{20,}'),
            re.compile(r'(?i)["\']?(?:api_key|password|token)["\']?\s*[:=]\s*["\'][A-Za-z0-9+/=_-]{12,}["\']')]

# Evidence is a small typed vocabulary, not arbitrary redactable prose. A raw
# string, URL, account number, balance or prompt inserted anywhere must fail.
SAFE_STRINGS = set(ACTIONS) | set(CONTROLS) | set(CODES) | {
    '', 'success', 'business_outcome', 'recoverable_error', 'hard_failure',
    'llm_discovery', 'replay', 'simulated_handoff', 'test_fixture',
    'observe', 'model_decision', 'checkpoint', 'outcome_verified', 'out:savings_balance',
    'ALLOW', 'retry', 'failure_snapshot', 'stopped', 'handoff_started', 'handoff_resumed',
    'handoff_stopped', 'human_actions', 'human', 'automation', 'click', 'change',
    'navigation', 'route', 'unknown', 'login', 'dashboard', 'savings',
}
SAFE_STRINGS.update(label for _, label in CONTROLS.values())
SAFE_KEYS = set('source scenario status code steps output_references events event snapshot surface_version route controls untrusted_page_data id label visible enabled step action decision operation attempt verified output_ref available owner same_session state_verified actions kind control'.split())


def evidence_safe(value):
    import main
    if isinstance(value, str):
        return value in SAFE_STRINGS or value in main.SCENARIOS
    if isinstance(value, bool) or value is None:
        return True
    if type(value) is int:
        return 0 <= value <= 64
    if isinstance(value, list):
        return all(evidence_safe(item) for item in value)
    if isinstance(value, dict):
        return all(key in SAFE_KEYS and evidence_safe(item) for key, item in value.items())
    return False


def scan(root=Path(__file__).parent):
    issues, count = [], 0
    runtime_values = [v for k, v in os.environ.items()
                      if (k in {'ANTHROPIC_API_KEY', 'DEMO_MEMBER_ONE_PASSWORD', 'DEMO_MEMBER_TWO_PASSWORD'}) and len(v) > 8]
    for path in sorted(Path(root).rglob('*')):
        if any(part in IGNORED for part in path.relative_to(root).parts) or path.is_symlink() or not path.is_file():
            continue
        if path.name == '.env' or path.name.startswith('.env.'):
            continue  # caller-owned secret material is intentionally not an artifact
        if path.suffix in {'.pyc'}:
            continue
        count += 1
        if path.suffix in {'.png', '.jpg', '.jpeg', '.zip', '.har'}:
            issues.append('raw_diagnostic_file')
            continue
        try:
            content = path.read_text()
        except (UnicodeError, OSError):
            issues.append('uninspectable_file')
            continue
        if any(pattern.search(content) for pattern in PATTERNS) or any(v in content for v in runtime_values):
            issues.append('sensitive_value_detected')
        if path.parent.name == 'evidence' and path.suffix == '.json':
            try:
                value = json.loads(content)
                if isinstance(value, dict) and 'schema_version' in value:
                    Artifact.from_dict(value)
                elif not evidence_safe(value):
                    issues.append('evidence_vocabulary_violation')
            except Exception:
                issues.append('invalid_evidence')
    return {'files_checked': count, 'passed': not issues, 'issue_codes': sorted(set(issues))}


if __name__ == '__main__':
    result = scan()
    print(json.dumps(result))
    raise SystemExit(0 if result['passed'] else 1)
