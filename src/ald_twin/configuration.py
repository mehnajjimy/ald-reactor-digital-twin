"""Small provenance registry; missing physical inputs never become defaults."""

from dataclasses import asdict, dataclass, field
import hashlib
import json
from math import isfinite
from pathlib import Path


SOURCE_TYPES = {"directly_reported", "literature_fixed", "derived", "fitted",
                "assumed", "synthetic_verification", "unresolved"}
STATUSES = {"LOCKED", "PROVISIONAL", "UNRESOLVED", "DEFERRED/EXCLUDED"}


@dataclass(frozen=True)
class Parameter:
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
        for key in ("name", "symbol", "units", "source"):
            if not isinstance(getattr(self, key), str) or not getattr(self, key).strip():
                raise ValueError(f"Parameter requires {key}")
        if self.source_type not in SOURCE_TYPES or self.status not in STATUSES:
            raise ValueError("Unknown provenance or scientific status")
        if self.value is not None and (isinstance(self.value, bool) or not isfinite(self.value)):
            raise ValueError("Parameter value must be finite or null")
        if self.source_type == "unresolved" or self.status == "UNRESOLVED":
            if self.value is not None:
                raise ValueError("Unresolved inputs must retain null values")
        if self.value is None and self.status != "UNRESOLVED":
            raise ValueError("A null input must be marked UNRESOLVED")
        if self.source_type == "derived" and not self.details.get("parent_parameters"):
            raise ValueError("Derived parameters must link parent_parameters")
        if self.source_type == "fitted" and not self.details.get("fitted_data_ids"):
            raise ValueError("Fitted parameters must identify fitted_data_ids")
        if self.details.get("author_exact") is False:
            required = {"replacement_basis", "parent_parameters", "correlation_version", "verification_status"}
            if not required <= self.details.keys():
                raise ValueError("Replacement provenance is incomplete")


@dataclass(frozen=True)
class ParameterRegistry:
    identifier: str
    kind: str
    parameters: tuple[Parameter, ...]

    def __post_init__(self):
        if not self.identifier or self.kind not in ("synthetic", "experimental"):
            raise ValueError("Registry requires an ID and synthetic/experimental kind")
        names = [p.name for p in self.parameters]
        if len(set(names)) != len(names):
            raise ValueError("Duplicate parameter names")
        if self.kind == "experimental" and any(p.source_type == "synthetic_verification" for p in self.parameters):
            raise ValueError("Synthetic coefficients cannot enter an experimental configuration")
        for p in self.parameters:
            if p.source_type == "derived":
                if any(parent not in names for parent in p.details["parent_parameters"]):
                    raise ValueError("Derived parameter refers to an unknown parent")

    @classmethod
    def load(cls, path):
        data = json.loads(Path(path).read_text())
        return cls(data["identifier"], data["kind"], tuple(Parameter(**p) for p in data["parameters"]))

    def resolve(self, expected_units):
        """Resolve only requested dependencies with exact declared SI unit labels."""
        lookup = {p.name: p for p in self.parameters}

        def available(name, active):
            if name not in lookup:
                raise ValueError(f"Missing required parameter: {name}")
            if name in active:
                raise ValueError(f"Cyclic derived parameter dependency: {name}")
            p = lookup[name]
            if p.value is None or p.status in ("UNRESOLVED", "DEFERRED/EXCLUDED"):
                raise ValueError(f"Blocked dependent run: {name} is {p.status}")
            if p.source_type == "derived":
                for parent in p.details["parent_parameters"]:
                    available(parent, active | {name})
            return p

        resolved = {}
        for name, units in expected_units.items():
            p = available(name, set())
            if p.units != units:
                raise ValueError(f"{name}: expected {units}, got {p.units}")
            resolved[name] = p.value
        return resolved

    @property
    def sha256(self):
        return hashlib.sha256(json.dumps(asdict(self), sort_keys=True, allow_nan=False).encode()).hexdigest()
