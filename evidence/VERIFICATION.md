# Clean verification

2026-09-24T02:57:45+00:00

Local synthetic bank only; tests and commands ran in the invoking Python environment.

Tests run: 43. Failures: 0. Errors: 0.

- `python demo.py fixture`: PASS.
- `python demo.py replay --member first`: PASS.
- `python demo.py replay --member second`: PASS.
- `python demo.py replay --member second --scenario zero`: PASS.
- `python demo.py replay --scenario no_savings --evidence evidence/exceptional-replay.json`: PASS.

Saved-file privacy audit: PASS.

Live model discovery and real-person handoff are separate checks; this offline run does not claim them.
