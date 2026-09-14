"""Run offline checks and exact demos; retain only sanitized verification evidence."""
from datetime import datetime, timezone
import io
from pathlib import Path
import subprocess
import sys
import unittest


def main():
    root = Path(__file__).parent
    # Test failures can contain library diagnostics; retain only test identifiers,
    # counts and pass/fail flags. Never persist arbitrary traceback strings.
    suite = unittest.defaultTestLoader.discover(str(root / 'tests'))
    stream = io.StringIO()
    result = unittest.TextTestRunner(stream=stream, verbosity=0).run(suite)
    report = ["# Clean verification", "", datetime.now(timezone.utc).replace(microsecond=0).isoformat(), "",
              "Local synthetic bank only; tests and commands ran in the invoking Python environment.", "",
              f"Tests run: {result.testsRun}. Failures: {len(result.failures)}. Errors: {len(result.errors)}.", ""]
    passed = result.wasSuccessful()
    commands = [(['fixture'], 0), (['replay', '--member', 'first'], 0),
                (['replay', '--member', 'second'], 0),
                (['replay', '--member', 'second', '--scenario', 'zero'], 0),
                (['replay', '--scenario', 'no_savings', '--evidence', 'evidence/exceptional-replay.json'], 1)]
    for args, expected in commands:
        process = subprocess.run([sys.executable, str(root / 'demo.py'), *args], cwd=root,
                                 stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=90)
        ok = process.returncode == expected
        passed = passed and ok
        report.append('- `python demo.py ' + ' '.join(args) + '`: ' + ('PASS' if ok else 'FAIL') + '.')
    from audit import scan
    audit = scan(root)
    passed = passed and audit['passed']
    report.extend(['', 'Saved-file privacy audit: ' + ('PASS' if audit['passed'] else 'FAIL') + '.', '',
                   'Live model discovery and real-person handoff are separate checks; this offline run does not claim them.', ''])
    (root / 'evidence' / 'VERIFICATION.md').write_text('\n'.join(report))
    print(f"Offline verification: {'PASS' if passed else 'FAIL'}; {result.testsRun} tests; privacy audit: {'PASS' if audit['passed'] else 'FAIL'}.")
    return 0 if passed else 1


if __name__ == '__main__':
    raise SystemExit(main())
