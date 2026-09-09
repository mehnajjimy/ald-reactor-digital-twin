"""SI outputs and precursor-equivalent accounting, never film-mass accounting."""

from dataclasses import dataclass
import hashlib
import json
import platform
from pathlib import Path

import numpy as np
import scipy


def json_native(value):
    """Canonicalize accepted NumPy scalars without discarding configuration fields."""
    if isinstance(value, np.ndarray):
        return value.tolist()
    if isinstance(value, np.generic):
        return value.item()
    if isinstance(value, dict):
        return {key: json_native(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [json_native(item) for item in value]
    return value


@dataclass(frozen=True)
class SimulationResult:
    t: np.ndarray
    z: np.ndarray
    c: np.ndarray
    theta: np.ndarray
    gas_moles: np.ndarray
    captured_moles: np.ndarray
    entered_moles: np.ndarray
    escaped_moles: np.ndarray
    source_moles: np.ndarray
    ledger_error_moles: np.ndarray
    metadata: dict
    solver_status: tuple[dict, ...]

    def save(self, stem):
        """Save arrays plus a configuration snapshot and solver diagnostics."""
        stem = Path(stem)
        stem.parent.mkdir(parents=True, exist_ok=True)
        arrays = {name: getattr(self, name) for name in (
            "t", "z", "c", "theta", "gas_moles", "captured_moles",
            "entered_moles", "escaped_moles", "source_moles", "ledger_error_moles")}
        np.savez_compressed(Path(str(stem) + ".npz"), **arrays)
        Path(str(stem) + ".json").write_text(json.dumps(
            {"metadata": self.metadata, "solver_status": self.solver_status},
            indent=2, allow_nan=False) + "\n")


def assemble_result(*, integrated, c, theta, z, cell_volumes, cell_areas, capacity,
                    initial_c, initial_theta, entered_moles, escaped_moles,
                    metadata, source_moles=None):
    c, theta = np.asarray(c), np.asarray(theta)
    gas = c @ np.asarray(cell_volumes)
    captured = (theta - np.asarray(initial_theta)) @ (capacity * np.asarray(cell_areas))
    initial_gas = float(np.asarray(initial_c) @ np.asarray(cell_volumes))
    sources = np.zeros_like(gas) if source_moles is None else np.asarray(source_moles)
    residual = initial_gas + entered_moles + sources - gas - captured - escaped_moles
    metadata = json_native(dict(metadata))
    metadata["runtime"] = {"python": platform.python_version(), "numpy": np.__version__,
                           "scipy": scipy.__version__, "platform": platform.platform()}
    metadata["units"] = {"t": "s", "z": "m", "c": "mol m^-3", "theta": "1",
                         "accounting": "mol precursor-equivalents"}
    metadata["initial_gas_moles"] = initial_gas
    metadata["configuration_sha256"] = hashlib.sha256(json.dumps(
        metadata, sort_keys=True, allow_nan=False).encode()).hexdigest()
    return SimulationResult(integrated.t, np.asarray(z), c, theta, gas, captured,
                            entered_moles, escaped_moles, sources, residual,
                            metadata, integrated.segments)
