"""Reference-based handling of sensitive values.

Two directions of secrecy:

  SecretStore  — values that go INTO the page (passwords). The LLM only ever
                 emits a reference like "secret:password"; the backend resolves
                 it to the real value at execution time. The raw secret never
                 appears in a prompt, a plan, or an artifact.

  OutputVault  — sensitive values read OUT of the page (a balance). During an
                 LLM-driven run these are captured to the vault and the model is
                 told only "captured out:savings_balance". The authorized caller
                 of a deterministic replay gets the real number directly.
"""


class UnknownReference(KeyError):
    """A reference had no backing value."""


class SecretStore:
    """Resolves inbound secret references. Never serialize this."""

    def __init__(self, values=None):
        # keys like "secret:password"; also holds non-secret "input:username"
        self._values = dict(values or {})

    def put(self, ref, value):
        self._values[ref] = value

    def has(self, ref):
        return ref in self._values

    def resolve(self, ref):
        if ref not in self._values:
            raise UnknownReference(ref)
        return self._values[ref]

    def is_secret(self, ref):
        return ref.startswith("secret:")

    def references(self):
        """Reference names only — safe to show the model."""
        return sorted(self._values.keys())


class OutputVault:
    """Holds sensitive outputs behind references; caller reads reals out."""

    def __init__(self):
        self._values = {}

    def store(self, ref, value):
        self._values[ref] = value
        return ref

    def reveal(self, ref):
        return self._values.get(ref)

    def all(self):
        return dict(self._values)
