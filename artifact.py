"""Typed, versioned workflow artifact.

A successful discovery is frozen into this structure so it can be replayed
deterministically — no LLM. It contains:

  inputs            — typed parameters (secret ones flagged)
  actions           — parameterized steps with STABLE locators and value refs
  outputs           — where/how to read results, and whether they're sensitive
  checkpoints       — assertions that must hold after a given step
  success_condition — human-readable statement of "done"

`value_ref` on an action points at a reference resolved at replay time:
  "input:username"  -> a plain typed input
  "secret:password" -> a backend secret (never stored here)
"""

import json
from dataclasses import dataclass, field, asdict

SCHEMA_VERSION = 1


@dataclass
class InputSpec:
    name: str
    type: str = "string"
    required: bool = True
    secret: bool = False


@dataclass
class ActionSpec:
    step: int
    tool: str                       # navigate | fill | click | wait | extract
    by: str = "css"                 # locator strategy
    target: str = ""                # stable locator, path, or wait text
    value_ref: str = None           # for fill: reference to resolve
    description: str = ""
    risky: bool = False


@dataclass
class OutputSpec:
    name: str
    by: str
    target: str
    type: str = "string"            # string | money
    sensitive: bool = False


@dataclass
class Checkpoint:
    after_step: int
    kind: str                       # route_contains | text_present
    value: str


@dataclass
class Artifact:
    name: str
    version: int
    description: str
    success_condition: str
    created_at: str = ""            # actual UTC discovery timestamp
    schema_version: int = SCHEMA_VERSION
    inputs: list = field(default_factory=list)
    actions: list = field(default_factory=list)
    outputs: list = field(default_factory=list)
    checkpoints: list = field(default_factory=list)
    metadata: dict = field(default_factory=dict)

    # --- serialization ---
    def to_dict(self):
        return asdict(self)

    def save(self, path):
        self.validate()
        with open(path, "w") as f:
            json.dump(self.to_dict(), f, indent=2)

    @staticmethod
    def load(path):
        with open(path) as f:
            return Artifact.from_dict(json.load(f))

    @staticmethod
    def from_dict(d):
        if not isinstance(d, dict) or set(d) != set(Artifact.__dataclass_fields__):
            from outcomes import HardFailure
            raise HardFailure("invalid_artifact")
        artifact = Artifact(
            name=d["name"], version=d["version"], description=d["description"],
            success_condition=d["success_condition"], created_at=d.get("created_at", ""),
            schema_version=d.get("schema_version", SCHEMA_VERSION),
            inputs=[InputSpec(**x) for x in d.get("inputs", [])],
            actions=[ActionSpec(**x) for x in d.get("actions", [])],
            outputs=[OutputSpec(**x) for x in d.get("outputs", [])],
            checkpoints=[Checkpoint(**x) for x in d.get("checkpoints", [])],
            metadata=d.get("metadata", {}),
        )

        artifact.validate()
        return artifact

    def validate(self):
        from outcomes import HardFailure
        from surface import action_id, SURFACE_VERSION, SUCCESS, RECOVERY, OUTCOME_RULES
        from workflow import SAVINGS_BALANCE
        import re
        expected = SAVINGS_BALANCE
        if (any(type(x.required) is not bool or type(x.secret) is not bool for x in self.inputs)
                or any(type(x.sensitive) is not bool for x in self.outputs)):
            raise HardFailure("invalid_artifact_contract")
        if (type(self.schema_version) is not int or self.schema_version != SCHEMA_VERSION
                or type(self.version) is not int or self.version != 1):
            raise HardFailure("unsupported_artifact_version")
        if (self.name != expected["name"] or self.description != expected["description"]
                or self.success_condition != SUCCESS or self.inputs != expected["inputs"]
                or self.outputs != expected["outputs"]):
            raise HardFailure("invalid_artifact_contract")
        if not re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\+00:00", self.created_at):
            raise HardFailure("invalid_artifact_timestamp")
        if (set(self.metadata) != {"surface_version", "source", "recovery", "outcomes"}
                or type(self.metadata["surface_version"]) is not int
                or self.metadata["surface_version"] != SURFACE_VERSION
                or self.metadata["source"] not in {"llm_discovery", "test_fixture"}
                or self.metadata["recovery"] != RECOVERY
                or self.metadata["outcomes"] != OUTCOME_RULES):
            raise HardFailure("invalid_artifact_metadata")
        if not 5 <= len(self.actions) <= 16:
            raise HardFailure("invalid_artifact_steps")
        keys = []
        for i, action in enumerate(self.actions, 1):
            if type(action.step) is not int or action.step != i:
                raise HardFailure("invalid_step_number")
            keys.append(action_id(action))
        # v1 admits optional bounded waits but requires the complete safe sequence.
        core = [k for k in keys if k != "wait_balance"]
        if core not in (["open_login", "fill_username", "fill_password", "sign_in", "open_savings", "read_balance"],
                        ["open_login", "fill_password", "fill_username", "sign_in", "open_savings", "read_balance"]):
            raise HardFailure("invalid_artifact_sequence")
        if keys.count("wait_balance") > 2 or any(k == "wait_balance" and "open_savings" not in keys[:i]
                                                   for i, k in enumerate(keys)):
            raise HardFailure("invalid_wait_sequence")
        required = [Checkpoint(i + 1, "route_equals", route) for i, k in enumerate(keys)
                    if (route := {"open_login": "/login", "sign_in": "/", "open_savings": "/account/savings"}.get(k))]
        if self.checkpoints != required:
            raise HardFailure("invalid_checkpoints")
        return self
