"""small provenance registry. missing physical inputs never become defaults."""

from dataclasses import asdict, dataclass, field
import hashlib
import json
from math import isfinite
from pathlib import Path

# allowed provenance labels and scientific statuses for a parameter
SOURCE_TYPES = {"directly_reported", "literature_fixed", "derived", "fitted",
                "assumed", "synthetic_verification", "unresolved"}
STATUSES = {"LOCKED", "PROVISIONAL", "UNRESOLVED", "DEFERRED/EXCLUDED"}

# detail keys a non-author-exact replacement must record
REPLACEMENT_DETAIL_KEYS = {"replacement_basis", "parent_parameters",
                           "correlation_version", "verification_status"}


@dataclass(frozen=True)
class Parameter:
    """one physical or numerical input with its value, units and provenance."""

    name: str
    symbol: str
    value: float | None
    units: str
    source: str
    source_type: str
    status: str
    uncertainty: str | None
    notes: str
    details: dict = field(default_factory=dict)

    def __post_init__(self):
        """reject parameters whose provenance is missing or inconsistent."""
        # text fields must be non-empty
        for key in ("name", "symbol", "units", "source"):
            text = getattr(self, key)
            if not isinstance(text, str) or not text.strip():
                raise ValueError(f"Parameter requires {key}")

        # labels must come from the known sets
        if self.source_type not in SOURCE_TYPES or self.status not in STATUSES:
            raise ValueError("Unknown provenance or scientific status")

        # a value is either a finite number or null (bools are not numbers here)
        if self.value is not None:
            if isinstance(self.value, bool) or not isfinite(self.value):
                raise ValueError("Parameter value must be finite or null")

        # unresolved inputs stay null, and null inputs must say they are unresolved
        is_unresolved = self.source_type == "unresolved" or self.status == "UNRESOLVED"
        if is_unresolved and self.value is not None:
            raise ValueError("Unresolved inputs must retain null values")
        if self.value is None and self.status != "UNRESOLVED":
            raise ValueError("A null input must be marked UNRESOLVED")

        # derived and fitted values must say where they came from
        if self.source_type == "derived" and not self.details.get("parent_parameters"):
            raise ValueError("Derived parameters must link parent_parameters")
        if self.source_type == "fitted" and not self.details.get("fitted_data_ids"):
            raise ValueError("Fitted parameters must identify fitted_data_ids")

        # a replacement for an author's exact value needs its full basis
        if self.details.get("author_exact") is False:
            if not REPLACEMENT_DETAIL_KEYS <= self.details.keys():
                raise ValueError("Replacement provenance is incomplete")


@dataclass(frozen=True)
class ParameterRegistry:
    """a named, checked set of parameters for one synthetic or experimental case."""

    identifier: str
    kind: str
    parameters: tuple[Parameter, ...]

    def __post_init__(self):
        """reject registries with bad kinds, duplicates or broken lineage."""
        if not self.identifier or self.kind not in ("synthetic", "experimental"):
            raise ValueError("Registry requires an ID and synthetic/experimental kind")

        names = [parameter.name for parameter in self.parameters]
        if len(set(names)) != len(names):
            raise ValueError("Duplicate parameter names")

        # synthetic coefficients must never leak into experimental runs
        if self.kind == "experimental":
            for parameter in self.parameters:
                if parameter.source_type == "synthetic_verification":
                    raise ValueError("Synthetic coefficients cannot enter an experimental configuration")

        # every derived parameter must point at parents in this registry
        for parameter in self.parameters:
            if parameter.source_type == "derived":
                for parent in parameter.details["parent_parameters"]:
                    if parent not in names:
                        raise ValueError("Derived parameter refers to an unknown parent")

    @classmethod
    def load(cls, path):
        """read a registry from its json file."""
        data = json.loads(Path(path).read_text())
        parameters = []
        for entry in data["parameters"]:
            parameters.append(Parameter(**entry))
        return cls(data["identifier"], data["kind"], tuple(parameters))

    def resolve(self, expected_units):
        """resolve only requested dependencies with exact declared SI unit labels."""
        lookup = {parameter.name: parameter for parameter in self.parameters}

        def available(name, active):
            """return a usable parameter, walking derived parents and catching cycles."""
            if name not in lookup:
                raise ValueError(f"Missing required parameter: {name}")
            if name in active:
                raise ValueError(f"Cyclic derived parameter dependency: {name}")
            parameter = lookup[name]
            if parameter.value is None or parameter.status in ("UNRESOLVED", "DEFERRED/EXCLUDED"):
                raise ValueError(f"Blocked dependent run: {name} is {parameter.status}")
            if parameter.source_type == "derived":
                for parent in parameter.details["parent_parameters"]:
                    available(parent, active | {name})
            return parameter

        resolved = {}
        for name, units in expected_units.items():
            parameter = available(name, set())
            if parameter.units != units:
                raise ValueError(f"{name}: expected {units}, got {parameter.units}")
            resolved[name] = parameter.value
        return resolved

    @property
    def sha256(self):
        """sha-256 of the registry contents as sorted json."""
        text = json.dumps(asdict(self), sort_keys=True, allow_nan=False)
        return hashlib.sha256(text.encode()).hexdigest()
